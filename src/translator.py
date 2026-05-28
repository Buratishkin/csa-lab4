from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from src.isa import DATA_WORD_SIZE_BYTES, INSTRUCTION_SIZE_BYTES, Instruction, Opcode, write_code, write_disasm
from src.lisp_parser import Expression, is_string_literal, parse, string_literal_value

INPUT_PORT = 0
OUTPUT_CHAR_PORT = 1
OUTPUT_INT_PORT = 2

# Backward-compatible alias: old code used OUTPUT_PORT for character output.
OUTPUT_PORT = OUTPUT_CHAR_PORT

INTERRUPT_VECTOR_ADDR = 0x00
INTERRUPT_DEVICE_CELL = DATA_WORD_SIZE_BYTES
RESERVED_DATA_CELLS = 2 * DATA_WORD_SIZE_BYTES

SPECIAL_FORM_NAMES = {
    "load-at",
    "store-at",
    "read-int",
    "call",
    "enable-interrupts",
    "disable-interrupts",
    "int",
    "+",
    "-",
    "*",
    "/",
    "%",
    "=",
    "!=",
    "<",
    ">",
    "<=",
    ">=",
    "print",
    "print-pstr",
    "pstr-len",
    "pstr-get",
    "pstr-set",
    "setq",
    "if",
    "loop",
    "begin",
    "print-char",
    "print-int",
    "read-char",
}

class TranslationError(Exception):
    pass

@dataclass
class Compiler:
    instructions: list[Instruction] = field(default_factory=list)
    variables: dict[str, int] = field(default_factory=dict)
    next_data_addr: int = RESERVED_DATA_CELLS
    data_initial: dict[int, int] = field(default_factory=dict)
    procedures: dict[str, int] = field(default_factory=dict)
    pending_calls: list[tuple[int, str]] = field(default_factory=list)
    procedure_params: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    local_scopes: list[dict[str, int]] = field(default_factory=list)
    call_result_addr: int | None = None

    def compile_program(self, expressions: list[Expression]) -> list[Instruction]:
        procedure_expressions: list[list[Expression]] = []
        interrupt_expression: list[Expression] | None = None
        main_expressions: list[Expression] = []

        for expression in expressions:
            if self.is_proc_definition(expression):
                procedure_expressions.append(expression)
            elif self.is_interrupt_definition(expression):
                if interrupt_expression is not None:
                    raise TranslationError("Only one interrupt handler is allowed")
                interrupt_expression = expression
            else:
                main_expressions.append(expression)

        jmp_main_index = self.emit_placeholder(Opcode.JMP)

        for procedure in procedure_expressions:
            self.declare_proc_signature(procedure)

        for procedure in procedure_expressions:
            self.compile_proc(procedure)

        if interrupt_expression is not None:
            self.compile_interrupt_handler(interrupt_expression)

        main_start = self.current_address()
        self.patch_operand(jmp_main_index, main_start)

        if interrupt_expression is not None:
            self.emit(Opcode.EI)

        for expression in main_expressions:
            self.compile_expr(expression)
            self.emit(Opcode.DROP)

        self.emit(Opcode.HALT)

        self.patch_pending_calls()

        return self.instructions

    # Main expression compiler
    def compile_expr(self, expression: Expression) -> None:
        if isinstance(expression, int):
            self.emit(Opcode.PUSHI, expression)
            return

        if isinstance(expression, str):
            if is_string_literal(expression):
                string_addr = self.allocate_pstr(string_literal_value(expression))
                self.emit(Opcode.PUSHI, string_addr)
                return

            address = self.get_variable_address(expression)
            self.emit(Opcode.LOAD, address)
            return

        if not expression:
            raise TranslationError("Empty list expression is not allowed")

        head = expression[0]

        if not isinstance(head, str) or is_string_literal(head):
            raise TranslationError("First element of list must be a symbol")

        name = head
        args = expression[1:]

        match name:
            case "load-at":
                self.compile_load_at(args)

            case "store-at":
                self.compile_store_at(args)

            case "read-int":
                self.compile_read_int(args)

            case "call":
                self.compile_call(args)

            case "enable-interrupts":
                self.compile_enable_interrupts(args)

            case "disable-interrupts":
                self.compile_disable_interrupts(args)

            case "int":
                self.compile_software_interrupt(args)

            case "+" | "-" | "*" | "/" | "%":
                self.compile_arithmetic(name, args)

            case "=" | "!=" | "<" | ">" | "<=" | ">=":
                self.compile_comparison(name, args)

            case "print":
                self.compile_print(args)

            case "print-pstr":
                self.compile_print_pstr(args)

            case "pstr-len":
                self.compile_pstr_len(args)

            case "pstr-get":
                self.compile_pstr_get(args)

            case "pstr-set":
                self.compile_pstr_set(args)

            case "setq":
                self.compile_setq(args)

            case "if":
                self.compile_if(args)

            case "loop":
                self.compile_loop(args)

            case "begin":
                self.compile_begin(args)

            case "print-char":
                self.compile_print_char(args)

            case "print-int":
                self.compile_print_int(args)

            case "read-char":
                self.compile_read_char(args)

            case _:
                raise TranslationError(f"Unknown form or function: {name}")

    # Forms
    def compile_interrupt_handler(self, expression: list[Expression]) -> None:
        body = expression[1:]

        if not body:
            raise TranslationError("interrupt requires handler body")

        handler_address = self.current_address()
        self.data_initial[INTERRUPT_VECTOR_ADDR] = handler_address
        self.data_initial.setdefault(INTERRUPT_DEVICE_CELL, 0)

        for body_expr in body:
            self.compile_expr(body_expr)
            self.emit(Opcode.DROP)

        self.emit(Opcode.IRET)

    def compile_enable_interrupts(self, args: list[Expression]) -> None:
        self.require_arg_count("enable-interrupts", args, 0)
        self.emit(Opcode.EI)
        self.emit(Opcode.PUSHI, 0)

    def compile_disable_interrupts(self, args: list[Expression]) -> None:
        self.require_arg_count("disable-interrupts", args, 0)
        self.emit(Opcode.DI)
        self.emit(Opcode.PUSHI, 0)

    def compile_software_interrupt(self, args: list[Expression]) -> None:
        self.require_arg_count("int", args, 0)
        self.emit(Opcode.INT)
        self.emit(Opcode.PUSHI, 0)

    def compile_setq(self, args: list[Expression]) -> None:
        self.require_arg_count("setq", args, 2)

        target = args[0]

        if not isinstance(target, str) or is_string_literal(target):
            raise TranslationError("First argument of setq must be a symbol")

        address = self.get_variable_address(target)

        self.compile_expr(args[1])
        self.emit(Opcode.DUP)
        self.emit(Opcode.STORE, address)

    def compile_if(self, args: list[Expression]) -> None:
        self.require_arg_count("if", args, 3)

        condition, then_expr, else_expr = args

        self.compile_expr(condition)

        jz_index = self.emit_placeholder(Opcode.JZ)

        self.compile_expr(then_expr)

        jmp_end_index = self.emit_placeholder(Opcode.JMP)

        else_address = self.current_address()
        self.patch_operand(jz_index, else_address)

        self.compile_expr(else_expr)

        end_address = self.current_address()
        self.patch_operand(jmp_end_index, end_address)

    def compile_loop(self, args: list[Expression]) -> None:
        if len(args) < 1:
            raise TranslationError("loop requires condition and optional body")

        condition = args[0]
        body = args[1:]

        loop_start = self.current_address()

        self.compile_expr(condition)
        jz_end_index = self.emit_placeholder(Opcode.JZ)

        for body_expr in body:
            self.compile_expr(body_expr)
            self.emit(Opcode.DROP)

        self.emit(Opcode.JMP, loop_start)

        loop_end = self.current_address()
        self.patch_operand(jz_end_index, loop_end)

        self.emit(Opcode.PUSHI, 0)

    def compile_proc(self, expression: list[Expression]) -> None:
        name, _, body = self.parse_proc_definition(expression)

        if name in self.procedures:
            raise TranslationError(f"Procedure already defined: {name}")

        self.procedures[name] = self.current_address()

        local_scope = {
            param_name: address
            for param_name, address in self.procedure_params.get(name, [])
        }
        self.local_scopes.append(local_scope)

        try:
            if not body:
                self.emit(Opcode.PUSHI, 0)
                self.emit(Opcode.RET)
                return

            for body_expr in body[:-1]:
                self.compile_expr(body_expr)
                self.emit(Opcode.DROP)

            self.compile_expr(body[-1])
            self.emit(Opcode.RET)
        finally:
            self.local_scopes.pop()

    def compile_call(self, args: list[Expression]) -> None:
        if len(args) < 1:
            raise TranslationError("call requires procedure name")

        target = args[0]

        if not isinstance(target, str) or is_string_literal(target):
            raise TranslationError("call argument must be a procedure name")

        name = target
        actual_args = args[1:]

        if name not in self.procedure_params:
            raise TranslationError(f"Undefined procedure: {name}")

        params = self.procedure_params[name]

        if len(actual_args) != len(params):
            raise TranslationError(
                f"Procedure {name} requires {len(params)} arguments, "
                f"got {len(actual_args)}"
            )

        for _, param_addr in params:
            self.emit(Opcode.LOAD, param_addr)

        for actual_expr in actual_args:
            self.compile_expr(actual_expr)

        for _, param_addr in reversed(params):
            self.emit(Opcode.STORE, param_addr)

        if name in self.procedures:
            self.emit(Opcode.CALL, self.procedures[name])
        else:
            call_index = self.emit_placeholder(Opcode.CALL)
            self.pending_calls.append((call_index, name))

        if not params:
            return

        result_addr = self.get_call_result_address()

        self.emit(Opcode.STORE, result_addr)

        for _, param_addr in reversed(params):
            self.emit(Opcode.STORE, param_addr)

        self.emit(Opcode.LOAD, result_addr)

    def compile_begin(self, args: list[Expression]) -> None:
        if not args:
            self.emit(Opcode.PUSHI, 0)
            return

        for expression in args[:-1]:
            self.compile_expr(expression)
            self.emit(Opcode.DROP)

        self.compile_expr(args[-1])

    def compile_print_char(self, args: list[Expression]) -> None:
        self.require_arg_count("print-char", args, 1)

        self.compile_expr(args[0])
        self.emit(Opcode.DUP)
        self.emit(Opcode.OUT, OUTPUT_CHAR_PORT)

    def compile_load_at(self, args: list[Expression]) -> None:
        self.require_arg_count("load-at", args, 1)

        self.compile_expr(args[0])
        self.emit(Opcode.LOADI)

    def compile_store_at(self, args: list[Expression]) -> None:
        self.require_arg_count("store-at", args, 2)

        self.compile_expr(args[0])  # address
        self.compile_expr(args[1])  # value
        self.emit(Opcode.STOREI)

        self.emit(Opcode.PUSHI, 0)

    def compile_read_int(self, args: list[Expression]) -> None:
        self.require_arg_count("read-int", args, 0)

        ch_addr = self.get_variable_address("__read_int_ch")
        value_addr = self.get_variable_address("__read_int_value")
        sign_addr = self.get_variable_address("__read_int_sign")

        self.emit(Opcode.PUSHI, 0)
        self.emit(Opcode.STORE, value_addr)

        self.emit(Opcode.PUSHI, 1)
        self.emit(Opcode.STORE, sign_addr)

        self.emit(Opcode.IN, INPUT_PORT)
        self.emit(Opcode.STORE, ch_addr)

        skip_loop_start = self.current_address()

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord(" "))
        self.emit(Opcode.EQ)
        jnz_read_next_space = self.emit_placeholder(Opcode.JNZ)

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord("\n"))
        self.emit(Opcode.EQ)
        jnz_read_next_newline = self.emit_placeholder(Opcode.JNZ)

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord("\t"))
        self.emit(Opcode.EQ)
        jnz_read_next_tab = self.emit_placeholder(Opcode.JNZ)

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord("\r"))
        self.emit(Opcode.EQ)
        jnz_read_next_cr = self.emit_placeholder(Opcode.JNZ)

        jmp_after_skip = self.emit_placeholder(Opcode.JMP)

        read_next_whitespace_addr = self.current_address()

        self.patch_operand(jnz_read_next_space, read_next_whitespace_addr)
        self.patch_operand(jnz_read_next_newline, read_next_whitespace_addr)
        self.patch_operand(jnz_read_next_tab, read_next_whitespace_addr)
        self.patch_operand(jnz_read_next_cr, read_next_whitespace_addr)

        self.emit(Opcode.IN, INPUT_PORT)
        self.emit(Opcode.STORE, ch_addr)
        self.emit(Opcode.JMP, skip_loop_start)

        after_skip_addr = self.current_address()
        self.patch_operand(jmp_after_skip, after_skip_addr)

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord("-"))
        self.emit(Opcode.EQ)
        jz_no_minus = self.emit_placeholder(Opcode.JZ)

        self.emit(Opcode.PUSHI, -1)
        self.emit(Opcode.STORE, sign_addr)

        # ch = read-char()
        self.emit(Opcode.IN, INPUT_PORT)
        self.emit(Opcode.STORE, ch_addr)

        no_minus_addr = self.current_address()
        self.patch_operand(jz_no_minus, no_minus_addr)
        digit_loop_start = self.current_address()

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord("0"))
        self.emit(Opcode.LT)
        jnz_digit_loop_end_1 = self.emit_placeholder(Opcode.JNZ)

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord("9"))
        self.emit(Opcode.GT)
        jnz_digit_loop_end_2 = self.emit_placeholder(Opcode.JNZ)

        self.emit(Opcode.LOAD, value_addr)
        self.emit(Opcode.PUSHI, 10)
        self.emit(Opcode.MUL)

        self.emit(Opcode.LOAD, ch_addr)
        self.emit(Opcode.PUSHI, ord("0"))
        self.emit(Opcode.SUB)

        self.emit(Opcode.ADD)
        self.emit(Opcode.STORE, value_addr)

        self.emit(Opcode.IN, INPUT_PORT)
        self.emit(Opcode.STORE, ch_addr)

        self.emit(Opcode.JMP, digit_loop_start)

        digit_loop_end_addr = self.current_address()
        self.patch_operand(jnz_digit_loop_end_1, digit_loop_end_addr)
        self.patch_operand(jnz_digit_loop_end_2, digit_loop_end_addr)

        self.emit(Opcode.LOAD, value_addr)
        self.emit(Opcode.LOAD, sign_addr)
        self.emit(Opcode.MUL)

    def compile_read_char(self, args: list[Expression]) -> None:
        self.require_arg_count("read-char", args, 0)

        self.emit(Opcode.IN, INPUT_PORT)

    def compile_print_int(self, args: list[Expression]) -> None:
        self.require_arg_count("print-int", args, 1)
        self.compile_expr(args[0])
        self.emit(Opcode.DUP)
        self.emit(Opcode.OUT, OUTPUT_INT_PORT)


    # Arithmetic and comparison
    def compile_arithmetic(self, operator: str, args: list[Expression]) -> None:
        if len(args) < 2:
            raise TranslationError(f"{operator} requires at least 2 arguments")

        # (+ 1 2 3) => ((1 + 2) + 3)
        self.compile_expr(args[0])

        for arg in args[1:]:
            self.compile_expr(arg)

            match operator:
                case "+":
                    self.emit(Opcode.ADD)
                case "-":
                    self.emit(Opcode.SUB)
                case "*":
                    self.emit(Opcode.MUL)
                case "/":
                    self.emit(Opcode.DIV)
                case "%":
                    self.emit(Opcode.MOD)
                case _:
                    raise AssertionError(f"Unknown arithmetic operator: {operator}")

    def compile_comparison(self, operator: str, args: list[Expression]) -> None:
        self.require_arg_count(operator, args, 2)

        self.compile_expr(args[0])
        self.compile_expr(args[1])

        match operator:
            case "=":
                self.emit(Opcode.EQ)
            case "!=":
                self.emit(Opcode.NE)
            case "<":
                self.emit(Opcode.LT)
            case ">":
                self.emit(Opcode.GT)
            case "<=":
                self.emit(Opcode.LE)
            case ">=":
                self.emit(Opcode.GE)
            case _:
                raise AssertionError(f"Unknown comparison operator: {operator}")

    def compile_print(self, args: list[Expression]) -> None:
        self.require_arg_count("print", args, 1)

        self.compile_expr(args[0])
        self.compile_print_pstr_from_stack()

    def compile_print_pstr(self, args: list[Expression]) -> None:
        self.require_arg_count("print-pstr", args, 1)

        self.compile_expr(args[0])
        self.compile_print_pstr_from_stack()

    def compile_pstr_len(self, args: list[Expression]) -> None:
        self.require_arg_count("pstr-len", args, 1)

        self.compile_expr(args[0])
        self.emit(Opcode.LOADI)

    def compile_pstr_get(self, args: list[Expression]) -> None:
        self.require_arg_count("pstr-get", args, 2)

        self.compile_expr(args[0])  # pstr address
        self.compile_expr(args[1])  # zero-based index
        self.emit(Opcode.PUSHI, DATA_WORD_SIZE_BYTES)
        self.emit(Opcode.MUL)
        self.emit(Opcode.ADD)
        self.emit(Opcode.PUSHI, DATA_WORD_SIZE_BYTES)
        self.emit(Opcode.ADD)
        self.emit(Opcode.LOADI)

    def compile_pstr_set(self, args: list[Expression]) -> None:
        self.require_arg_count("pstr-set", args, 3)

        self.compile_expr(args[0])  # pstr address
        self.compile_expr(args[1])  # zero-based index
        self.emit(Opcode.PUSHI, DATA_WORD_SIZE_BYTES)
        self.emit(Opcode.MUL)
        self.emit(Opcode.ADD)
        self.emit(Opcode.PUSHI, DATA_WORD_SIZE_BYTES)
        self.emit(Opcode.ADD)
        self.compile_expr(args[2])  # value
        self.emit(Opcode.STOREI)
        self.emit(Opcode.PUSHI, 0)

    def allocate_pstr(self, value: str) -> int:
        chars = [ord(ch) for ch in value]

        if len(chars) > 255:
            raise TranslationError("String is too long for pstr")

        start_addr = self.next_data_addr

        words = [len(chars), *chars]

        for offset, word in enumerate(words):
            self.data_initial[start_addr + offset * DATA_WORD_SIZE_BYTES] = word

        self.next_data_addr += len(words) * DATA_WORD_SIZE_BYTES

        return start_addr

    def compile_print_pstr_from_stack(self) -> None:
        ptr_addr = self.get_variable_address("__pstr_ptr")
        len_addr = self.get_variable_address("__pstr_len")

        # ptr = pstr_addr
        self.emit(Opcode.STORE, ptr_addr)

        # len = memory[ptr]
        self.emit(Opcode.LOAD, ptr_addr)
        self.emit(Opcode.LOADI)
        self.emit(Opcode.STORE, len_addr)

        # ptr = ptr + DATA_WORD_SIZE_BYTES
        self.emit(Opcode.LOAD, ptr_addr)
        self.emit(Opcode.PUSHI, DATA_WORD_SIZE_BYTES)
        self.emit(Opcode.ADD)
        self.emit(Opcode.STORE, ptr_addr)

        loop_start = self.current_address()

        # while len > 0
        self.emit(Opcode.LOAD, len_addr)
        self.emit(Opcode.PUSHI, 0)
        self.emit(Opcode.GT)

        jz_end_index = self.emit_placeholder(Opcode.JZ)

        # OUT memory[ptr]
        self.emit(Opcode.LOAD, ptr_addr)
        self.emit(Opcode.LOADI)
        self.emit(Opcode.OUT, OUTPUT_CHAR_PORT)

        # ptr = ptr + DATA_WORD_SIZE_BYTES
        self.emit(Opcode.LOAD, ptr_addr)
        self.emit(Opcode.PUSHI, DATA_WORD_SIZE_BYTES)
        self.emit(Opcode.ADD)
        self.emit(Opcode.STORE, ptr_addr)

        # len = len - 1
        self.emit(Opcode.LOAD, len_addr)
        self.emit(Opcode.PUSHI, 1)
        self.emit(Opcode.SUB)
        self.emit(Opcode.STORE, len_addr)

        self.emit(Opcode.JMP, loop_start)

        loop_end = self.current_address()
        self.patch_operand(jz_end_index, loop_end)

        # print/print-pstr возвращает 0
        self.emit(Opcode.PUSHI, 0)

    # Helpers
    def allocate_words(self, count: int) -> int:
        if count < 0:
            raise TranslationError(f"Cannot allocate negative number of words: {count}")

        start_addr = self.next_data_addr
        self.next_data_addr += count * DATA_WORD_SIZE_BYTES

        return start_addr

    def parse_proc_definition(
        self,
        expression: list[Expression],
    ) -> tuple[str, list[str], list[Expression]]:
        if len(expression) < 2:
            raise TranslationError("proc requires name and body")

        name_expr = expression[1]

        if not isinstance(name_expr, str) or is_string_literal(name_expr):
            raise TranslationError("proc name must be a symbol")

        name = name_expr
        params: list[str] = []
        body_start = 2

        if len(expression) >= 3 and self.is_parameter_list(expression[2]):
            raw_params = expression[2]
            assert isinstance(raw_params, list)
            params = list(raw_params)  # type: ignore[arg-type]
            body_start = 3

        if len(set(params)) != len(params):
            raise TranslationError(f"Duplicate parameter name in procedure {name}")

        return name, params, expression[body_start:]

    @staticmethod
    def is_parameter_list(expression: Expression) -> bool:
        if not isinstance(expression, list):
            return False

        if expression and isinstance(expression[0], str) and expression[0] in SPECIAL_FORM_NAMES:
            return False

        return all(
            isinstance(param, str) and not is_string_literal(param)
            for param in expression
        )

    def declare_proc_signature(self, expression: list[Expression]) -> None:
        name, params, _ = self.parse_proc_definition(expression)

        if name in self.procedure_params:
            raise TranslationError(f"Procedure already defined: {name}")

        param_cells: list[tuple[str, int]] = []

        for param in params:
            address = self.get_global_variable_address(f"__proc_{name}_{param}")
            param_cells.append((param, address))

        self.procedure_params[name] = param_cells

    def get_call_result_address(self) -> int:
        if self.call_result_addr is None:
            self.call_result_addr = self.get_global_variable_address("__call_result")

        return self.call_result_addr

    def patch_pending_calls(self) -> None:
        for instruction_index, name in self.pending_calls:
            if name not in self.procedures:
                raise TranslationError(f"Undefined procedure: {name}")

            self.patch_operand(instruction_index, self.procedures[name])

    @staticmethod
    def is_proc_definition(expression: Expression) -> bool:
        if not isinstance(expression, list):
            return False

        if not expression:
            return False

        head = expression[0]

        return isinstance(head, str) and head == "proc"

    @staticmethod
    def is_interrupt_definition(expression: Expression) -> bool:
        if not isinstance(expression, list):
            return False

        if not expression:
            return False

        head = expression[0]

        return isinstance(head, str) and head == "interrupt"

    def build_initial_data_memory(self) -> list[int]:
        if self.next_data_addr == 0:
            return []

        data = bytearray(self.next_data_addr)

        for address, value in self.data_initial.items():
            self.write_word_to_initial_data(data, address, value)

        return list(data)

    @staticmethod
    def write_word_to_initial_data(data: bytearray, address: int, value: int) -> None:
        if address % DATA_WORD_SIZE_BYTES != 0:
            raise TranslationError(f"Unaligned data address: {address}")

        if address < 0 or address + DATA_WORD_SIZE_BYTES > len(data):
            raise TranslationError(f"Data address out of range: {address}")

        value &= 0xFFFFFFFF
        data[address:address + DATA_WORD_SIZE_BYTES] = value.to_bytes(
            DATA_WORD_SIZE_BYTES,
            byteorder="little",
            signed=False,
        )

    def get_variable_address(self, name: str) -> int:
        for scope in reversed(self.local_scopes):
            if name in scope:
                return scope[name]

        return self.get_global_variable_address(name)

    def get_global_variable_address(self, name: str) -> int:
        if name not in self.variables:
            self.variables[name] = self.next_data_addr
            self.next_data_addr += DATA_WORD_SIZE_BYTES

        return self.variables[name]

    def emit(self, opcode: Opcode, operand: int = 0) -> int:
        self.instructions.append(Instruction(opcode, operand))
        return len(self.instructions) - 1

    def emit_placeholder(self, opcode: Opcode) -> int:
        return self.emit(opcode, 0)

    def patch_operand(self, instruction_index: int, operand: int) -> None:
        old_instruction = self.instructions[instruction_index]
        self.instructions[instruction_index] = Instruction(
            old_instruction.opcode,
            operand,
        )

    def current_address(self) -> int:
        return len(self.instructions) * INSTRUCTION_SIZE_BYTES

    @staticmethod
    def require_arg_count(name: str, args: list[Expression], expected: int) -> None:
        if len(args) != expected:
            raise TranslationError(
                f"{name} requires {expected} arguments, got {len(args)}"
            )

@dataclass(frozen=True)
class TranslationResult:
    instructions: list[Instruction]
    variables: dict[str, int]
    data_memory: list[int]


def translate_source(source: str) -> TranslationResult:
    expressions = parse(source)

    compiler = Compiler()
    instructions = compiler.compile_program(expressions)

    return TranslationResult(
        instructions=instructions,
        variables=compiler.variables.copy(),
        data_memory=compiler.build_initial_data_memory(),
    )


def translate_file(input_filename: str | Path) -> TranslationResult:
    source = Path(input_filename).read_text(encoding="utf-8")
    return translate_source(source)


# CLI
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate Mini Lisp source code to stack machine binary code."
    )

    parser.add_argument(
        "--data",
        help="Path to output initial data memory JSON file.",
        default=None,
    )
    parser.add_argument(
        "source",
        help="Path to source .lisp file.",
    )
    parser.add_argument(
        "output",
        help="Path to output binary file.",
    )
    parser.add_argument(
        "--disasm",
        help="Path to output disassembly file.",
        default=None,
    )
    parser.add_argument(
        "--vars",
        help="Path to output variable map file.",
        default=None,
    )

    args = parser.parse_args()

    result = translate_file(args.source)

    write_code(args.output, result.instructions)

    if args.disasm is not None:
        write_disasm(args.disasm, result.instructions)

    if args.data is not None:
        Path(args.data).write_text(
            json.dumps(result.data_memory, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.vars is not None:
        lines = [
            f"{name}: {address}"
            for name, address in sorted(result.variables.items(), key=lambda item: item[1])
        ]
        Path(args.vars).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()