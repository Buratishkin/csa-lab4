from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import src.isa as _isa

import src.microcode as _microcode


DATA_WORD_SIZE_BYTES = _isa.DATA_WORD_SIZE_BYTES
INSTRUCTION_SIZE_BYTES = _isa.INSTRUCTION_SIZE_BYTES
Instruction = _isa.Instruction
Opcode = _isa.Opcode
read_code = _isa.read_code

ALUSignal = _microcode.ALUSignal
ControlSignal = _microcode.ControlSignal
FETCH_ADDR = _microcode.FETCH_ADDR
MICROPROGRAM = _microcode.MICROPROGRAM
MPC_OF_OPCODE = _microcode.MPC_OF_OPCODE
MicroInstruction = _microcode.MicroInstruction
MuxSignal = _microcode.MuxSignal
Signal = _microcode.Signal

DEFAULT_DATA_MEMORY_SIZE = 4096 * DATA_WORD_SIZE_BYTES
DEFAULT_TICK_LIMIT = 10_000_000

INPUT_PORT = 0
OUTPUT_CHAR_PORT = 1
OUTPUT_INT_PORT = 2
OUTPUT_PORT = OUTPUT_CHAR_PORT

EMPTY_SP = -DATA_WORD_SIZE_BYTES
EMPTY_R = -DATA_WORD_SIZE_BYTES


@dataclass
class DataPath:
    data_memory_size: int = DEFAULT_DATA_MEMORY_SIZE
    input_text: str = ""
    initial_data_memory: list[int] | None = None

    data_memory: bytearray = field(init=False)

    data_stack: list[int] = field(default_factory=list)
    return_stack: list[int] = field(default_factory=list)

    input_buffer: list[int] = field(init=False)
    output_buffer: list[int] = field(default_factory=list)

    zero_flag: bool = False
    negative_flag: bool = False

    sp: int = EMPTY_SP
    t: int = 0
    f: int = 0
    ar: int = 0

    selected_stack_addr: int = EMPTY_SP
    addr_mux_value: int = 0
    stack_mux_value: int = 0
    input_latch: int = 0
    alu_result: int = 0

    next_sp: int | None = None
    next_t: int | None = None
    next_f: int | None = None
    next_ar: int | None = None

    def __post_init__(self) -> None:
        self.data_memory = bytearray(self.data_memory_size)

        if self.initial_data_memory is not None:
            if len(self.initial_data_memory) > self.data_memory_size:
                raise RuntimeError(
                    f"Initial data memory is too large: "
                    f"{len(self.initial_data_memory)} > {self.data_memory_size}"
                )

            for address, value in enumerate(self.initial_data_memory):
                if not 0 <= int(value) <= 0xFF:
                    raise RuntimeError(f"Initial data byte out of range at {address}: {value}")
                self.data_memory[address] = int(value)

        self.input_buffer = [ord(ch) for ch in self.input_text]
        self._resync_signal_stack_from_list()

    @staticmethod
    def normalize_word(value: int) -> int:
        value &= 0xFFFFFFFF

        if value & 0x80000000:
            return value - 0x100000000

        return value

    def set_flags(self, value: int) -> None:
        value = self.normalize_word(value)
        self.zero_flag = value == 0
        self.negative_flag = value < 0

    def push(self, value: int) -> None:
        self.data_stack.append(self.normalize_word(value))
        self._resync_signal_stack_from_list()

    def pop(self) -> int:
        if not self.data_stack:
            raise RuntimeError("Data stack underflow")

        value = self.data_stack.pop()
        self._resync_signal_stack_from_list()
        return value

    def peek(self) -> int:
        if not self.data_stack:
            raise RuntimeError("Data stack is empty")

        return self.data_stack[-1]

    def stack_snapshot(self) -> list[int]:
        return self.data_stack.copy()

    def stack_top_snapshot(self, limit: int = 6) -> list[int]:
        return self.stack_snapshot()[-limit:]

    def _resync_signal_stack_from_list(self) -> None:
        self.sp = (len(self.data_stack) - 1) * DATA_WORD_SIZE_BYTES if self.data_stack else EMPTY_SP
        self.t = self.data_stack[-1] if self.data_stack else 0

    def start_cycle(self) -> None:
        self.next_sp = self.sp
        self.next_t = self.t
        self.next_f = self.f
        self.next_ar = self.ar
        self.selected_stack_addr = self.sp
        self.addr_mux_value = self.ar
        self.stack_mux_value = 0
        self.input_latch = 0

    def update(self) -> None:
        assert self.next_sp is not None
        assert self.next_t is not None
        assert self.next_f is not None
        assert self.next_ar is not None

        self.sp = self.next_sp
        self.t = self.normalize_word(self.next_t)
        self.f = self.normalize_word(self.next_f)
        self.ar = self.next_ar

        self._truncate_stack_to_sp()

        if self.sp == EMPTY_SP:
            self.t = 0
        elif self.data_stack:
            top_index = self.sp_to_index(self.sp)
            self.ensure_stack_index(top_index)
            self.data_stack[top_index] = self.normalize_word(self.t)

        self.next_sp = None
        self.next_t = None
        self.next_f = None
        self.next_ar = None

    def _truncate_stack_to_sp(self) -> None:
        if self.sp == EMPTY_SP:
            self.data_stack.clear()
            return

        if self.sp < EMPTY_SP or self.sp % DATA_WORD_SIZE_BYTES != 0:
            raise RuntimeError(f"Invalid SP value: {self.sp}")

        new_len = self.sp_to_index(self.sp) + 1
        del self.data_stack[new_len:]

    @staticmethod
    def sp_to_index(address: int) -> int:
        if address % DATA_WORD_SIZE_BYTES != 0:
            raise RuntimeError(f"Unaligned stack address: {address}")
        return address // DATA_WORD_SIZE_BYTES

    def ensure_stack_index(self, index: int) -> None:
        if index < 0:
            raise RuntimeError(f"Stack address is below zero: {index * DATA_WORD_SIZE_BYTES}")
        while len(self.data_stack) <= index:
            self.data_stack.append(0)

    def read_stack_address(self, address: int, *, allow_empty_previous: bool = True) -> int:
        if address == EMPTY_SP and allow_empty_previous:
            return 0

        index = self.sp_to_index(address)
        if not 0 <= index < len(self.data_stack):
            if allow_empty_previous:
                return 0
            raise RuntimeError(f"Stack address out of range: {address}")

        return self.data_stack[index]

    # data memory
    def check_data_addr(self, address: int) -> None:
        if address % DATA_WORD_SIZE_BYTES != 0:
            raise RuntimeError(f"Unaligned data memory address: {address}")

        if not 0 <= address <= len(self.data_memory) - DATA_WORD_SIZE_BYTES:
            raise RuntimeError(f"Data memory address out of range: {address}")

    def read_memory(self, address: int) -> int:
        self.check_data_addr(address)
        return int.from_bytes(
            self.data_memory[address:address + DATA_WORD_SIZE_BYTES],
            byteorder="little",
            signed=True,
        )

    def write_memory(self, address: int, value: int) -> None:
        self.check_data_addr(address)
        value = self.normalize_word(value)
        self.data_memory[address:address + DATA_WORD_SIZE_BYTES] = value.to_bytes(
            DATA_WORD_SIZE_BYTES,
            byteorder="little",
            signed=True,
        )

    # ports
    def read_port(self, port: int) -> int:
        if port != INPUT_PORT:
            raise RuntimeError(f"Unknown input port: {port}")

        if not self.input_buffer:
            raise StopIteration("Input stream exhausted")

        return self.input_buffer.pop(0)

    def write_port(self, port: int, value: int) -> None:
        if port == OUTPUT_CHAR_PORT:
            self.output_buffer.append(value & 0xFF)
            return

        if port == OUTPUT_INT_PORT:
            text = str(self.normalize_word(value))

            for ch in text:
                self.output_buffer.append(ord(ch))

            return

        raise RuntimeError(f"Unknown output port: {port}")

    def output_text(self) -> str:
        return "".join(chr(value) for value in self.output_buffer)

    # selectors / latches used by microinstructions
    def select_stack_addr(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_STACK_ADDR_CURRENT:
            self.selected_stack_addr = self.sp
        elif selector == MuxSignal.SEL_STACK_ADDR_NEXT:
            self.selected_stack_addr = self.sp + DATA_WORD_SIZE_BYTES
        else:
            raise RuntimeError(f"Invalid stack address selector: {selector}")

    def select_data_address(self, selector: Any, operand: int) -> None:
        if selector == MuxSignal.SEL_ADDR_OPERAND:
            self.addr_mux_value = operand
        elif selector == MuxSignal.SEL_ADDR_T:
            self.addr_mux_value = self.t
        else:
            raise RuntimeError(f"Invalid data address selector: {selector}")

    def latch_ar(self) -> None:
        self.next_ar = self.addr_mux_value

    def stack_mux(self, selector: Any, operand: int) -> int:
        if selector == MuxSignal.SEL_STACK_IMM:
            return operand
        if selector == MuxSignal.SEL_STACK_MEMORY:
            return self.read_memory(self.ar)
        if selector == MuxSignal.SEL_STACK_ALU:
            return self.alu_result
        if selector == MuxSignal.SEL_STACK_INPUT:
            return self.input_latch
        if selector == MuxSignal.SEL_STACK_T:
            return self.t

        raise RuntimeError(f"Invalid stack mux selector: {selector}")

    def write_stack(self, selector: Any, operand: int) -> None:
        value = self.normalize_word(self.stack_mux(selector, operand))
        index = self.sp_to_index(self.selected_stack_addr)
        self.ensure_stack_index(index)
        self.data_stack[index] = value
        self.stack_mux_value = value

    def latch_sp(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_SP_NEXT:
            self.next_sp = self.sp + DATA_WORD_SIZE_BYTES
        elif selector == MuxSignal.SEL_SP_PREV:
            self.next_sp = self.sp - DATA_WORD_SIZE_BYTES
        else:
            raise RuntimeError(f"Invalid SP selector: {selector}")

    def latch_t(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_T_STACK_MUX:
            self.next_t = self.stack_mux_value
        elif selector == MuxSignal.SEL_T_STACK_PREV:
            self.next_t = self.read_stack_address(self.sp - DATA_WORD_SIZE_BYTES)
        else:
            raise RuntimeError(f"Invalid T selector: {selector}")

    def latch_f(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_F_T:
            self.next_f = self.t
        else:
            raise RuntimeError(f"Invalid F selector: {selector}")

    def write_data_memory_by_selector(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_DATA_IN_T:
            value = self.t
        else:
            raise RuntimeError(f"Invalid data input selector: {selector}")

        self.write_memory(self.ar, value)

    def alu(self, selector: Any) -> None:
        left = self.t
        right = self.f

        match selector:
            case ALUSignal.ADD:
                result = left + right
            case ALUSignal.SUB:
                result = left - right
            case ALUSignal.MUL:
                result = left * right
            case ALUSignal.DIV:
                if right == 0:
                    raise RuntimeError("Division by zero")
                result = int(left / right)
            case ALUSignal.MOD:
                if right == 0:
                    raise RuntimeError("Modulo by zero")
                result = left % right
            case ALUSignal.EQ:
                result = int(left == right)
            case ALUSignal.NE:
                result = int(left != right)
            case ALUSignal.LT:
                result = int(left < right)
            case ALUSignal.GT:
                result = int(left > right)
            case ALUSignal.LE:
                result = int(left <= right)
            case ALUSignal.GE:
                result = int(left >= right)
            case _:
                raise RuntimeError(f"Unknown ALU selector: {selector}")

        self.alu_result = self.normalize_word(result)


@dataclass
class ControlUnit:
    instruction_memory: list[Instruction]
    datapath: DataPath

    pc: int = 0
    ir: Instruction | None = None
    mpc: int = FETCH_ADDR
    r: int = EMPTY_R

    tick: int = 0
    halted: bool = False
    halt_reason: str = ""

    log: list[str] = field(default_factory=list)

    last_alu_result: int = 0

    selected_return_addr: int = EMPTY_R
    next_pc: int | None = None
    next_mpc: int | None = None
    next_ir: Instruction | None = None
    next_r: int | None = None

    def run(self, tick_limit: int = DEFAULT_TICK_LIMIT) -> None:
        while not self.halted and self.tick < tick_limit:
            self.step_tick()

        if self.tick >= tick_limit and not self.halted:
            self.halted = True
            self.halt_reason = f"Tick limit exceeded: {tick_limit}"

    def step_tick(self) -> None:
        self.tick += 1
        current_mpc = self.mpc

        if current_mpc < 0 or current_mpc >= len(MICROPROGRAM):
            raise RuntimeError(f"MPC out of range: {current_mpc}")

        microinstruction = MICROPROGRAM[current_mpc]
        self.start_cycle(current_mpc)

        try:
            for control_signal in microinstruction:
                self.dispatch(control_signal)
        except StopIteration:
            self.halted = True
            self.halt_reason = "Input stream exhausted"

        self.update_after_cycle()
        self.write_log(current_mpc, microinstruction)

    def start_cycle(self, current_mpc: int) -> None:
        self.datapath.start_cycle()
        self.selected_return_addr = self.r
        self.next_pc = self.pc
        self.next_mpc = current_mpc
        self.next_ir = self.ir
        self.next_r = self.r

    def update_after_cycle(self) -> None:
        assert self.next_pc is not None
        assert self.next_mpc is not None
        assert self.next_r is not None

        self.datapath.update()
        self.pc = self.next_pc
        self.mpc = self.next_mpc
        self.r = self.next_r
        self.truncate_return_stack_to_r()

        # Returning to FETCH means that the previous instruction is complete.
        if self.mpc == FETCH_ADDR and self.next_ir is self.ir:
            self.ir = None
        else:
            self.ir = self.next_ir

        self.next_pc = None
        self.next_mpc = None
        self.next_ir = None
        self.next_r = None
        self.last_alu_result = self.datapath.alu_result

    # signal dispatch
    def dispatch(self, control_signal: ControlSignal) -> None:
        signal = control_signal.signal
        selector = control_signal.selector
        dp = self.datapath

        match signal:
            case Signal.LATCH_IR:
                self.next_ir = self.fetch_instruction_at_pc()

            case Signal.LATCH_MPC:
                self.latch_mpc(selector)

            case Signal.LATCH_PC:
                self.latch_pc(selector)

            case Signal.LATCH_SP:
                dp.latch_sp(selector)

            case Signal.LATCH_T:
                dp.latch_t(selector)

            case Signal.LATCH_F:
                dp.latch_f(selector)

            case Signal.LATCH_AR:
                dp.latch_ar()

            case Signal.SELECT_STACK_ADDR:
                dp.select_stack_addr(selector)

            case Signal.WRITE_STACK:
                if self.next_ir is None:
                    raise RuntimeError("IR is empty for WRITE_STACK")
                dp.write_stack(selector, self.next_ir.operand)

            case Signal.SELECT_DATA_ADDRESS:
                if self.next_ir is None:
                    raise RuntimeError("IR is empty for SELECT_DATA_ADDRESS")
                dp.select_data_address(selector, self.next_ir.operand)

            case Signal.WRITE_DATA_MEMORY:
                dp.write_data_memory_by_selector(selector)

            case Signal.ALU:
                dp.alu(selector)

            case Signal.LATCH_NZ:
                dp.set_flags(dp.alu_result)

            case Signal.SELECT_RETURN_STACK_ADDR:
                self.select_return_stack_addr(selector)

            case Signal.WRITE_RETURN_STACK:
                self.write_return_stack(selector)

            case Signal.LATCH_R:
                self.latch_r(selector)

            case Signal.READ_IO:
                if self.next_ir is None:
                    raise RuntimeError("IR is empty for READ_IO")
                port = self.port_from_selector(selector, self.next_ir.operand)
                dp.input_latch = dp.read_port(port)

            case Signal.WRITE_IO:
                if self.next_ir is None:
                    raise RuntimeError("IR is empty for WRITE_IO")
                port = self.port_from_selector(selector, self.next_ir.operand)
                dp.write_port(port, dp.t)

            case Signal.HALT:
                self.halted = True
                self.halt_reason = "HALT instruction"

            case _:
                raise RuntimeError(f"Unknown control signal: {control_signal}")

    def fetch_instruction_at_pc(self) -> Instruction:
        if self.pc % INSTRUCTION_SIZE_BYTES != 0:
            raise RuntimeError(f"Unaligned PC: {self.pc}")

        code_size = len(self.instruction_memory) * INSTRUCTION_SIZE_BYTES
        if not 0 <= self.pc < code_size:
            raise RuntimeError(f"PC out of instruction memory: {self.pc}")

        instruction_index = self.pc // INSTRUCTION_SIZE_BYTES
        return self.instruction_memory[instruction_index]

    def current_instruction_for_decode(self) -> Instruction:
        instruction = self.next_ir or self.ir
        if instruction is None:
            raise RuntimeError("Cannot decode opcode: IR is empty")
        return instruction

    def latch_mpc(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_MPC_NEXT:
            assert self.next_mpc is not None
            self.next_mpc = self.next_mpc + 1
            return

        if selector == MuxSignal.SEL_MPC_FETCH:
            self.next_mpc = FETCH_ADDR
            return

        if selector == MuxSignal.SEL_MPC_OPCODE:
            instruction = self.current_instruction_for_decode()
            if instruction.opcode not in MPC_OF_OPCODE:
                raise RuntimeError(f"Opcode has no microcode: {instruction.opcode}")
            self.next_mpc = MPC_OF_OPCODE[instruction.opcode]
            return

        raise RuntimeError(f"Invalid MPC selector: {selector}")

    def latch_pc(self, selector: Any) -> None:
        instruction = self.next_ir or self.ir
        operand = instruction.operand if instruction is not None else 0
        dp = self.datapath

        if selector == MuxSignal.SEL_PC_NEXT:
            self.next_pc = self.pc + INSTRUCTION_SIZE_BYTES
        elif selector == MuxSignal.SEL_PC_OPERAND:
            self.next_pc = operand
        elif selector == MuxSignal.SEL_PC_JZ_BY_T:
            self.next_pc = operand if dp.t == 0 else self.pc + INSTRUCTION_SIZE_BYTES
        elif selector == MuxSignal.SEL_PC_JNZ_BY_T:
            self.next_pc = operand if dp.t != 0 else self.pc + INSTRUCTION_SIZE_BYTES
        elif selector == MuxSignal.SEL_PC_RETURN_STACK:
            self.next_pc = self.read_return_stack_address(self.r)
        else:
            raise RuntimeError(f"Invalid PC selector: {selector}")

    # return stack / R
    @staticmethod
    def r_to_index(address: int) -> int:
        if address % DATA_WORD_SIZE_BYTES != 0:
            raise RuntimeError(f"Unaligned return stack address: {address}")
        return address // DATA_WORD_SIZE_BYTES

    def ensure_return_stack_index(self, index: int) -> None:
        if index < 0:
            raise RuntimeError(f"Return stack address is below zero: {index * DATA_WORD_SIZE_BYTES}")
        while len(self.datapath.return_stack) <= index:
            self.datapath.return_stack.append(0)

    def read_return_stack_address(self, address: int) -> int:
        if address == EMPTY_R:
            raise RuntimeError("Return stack underflow")

        index = self.r_to_index(address)
        if not 0 <= index < len(self.datapath.return_stack):
            raise RuntimeError(f"Return stack address out of range: {address}")

        return self.datapath.return_stack[index]

    def truncate_return_stack_to_r(self) -> None:
        if self.r == EMPTY_R:
            self.datapath.return_stack.clear()
            return

        if self.r < EMPTY_R or self.r % DATA_WORD_SIZE_BYTES != 0:
            raise RuntimeError(f"Invalid R value: {self.r}")

        new_len = self.r_to_index(self.r) + 1
        del self.datapath.return_stack[new_len:]

    def select_return_stack_addr(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_RETURN_STACK_NEXT:
            self.selected_return_addr = self.r + DATA_WORD_SIZE_BYTES
        elif selector == MuxSignal.SEL_RETURN_STACK_CURRENT:
            self.selected_return_addr = self.r
        else:
            raise RuntimeError(f"Invalid return stack address selector: {selector}")

    def write_return_stack(self, selector: Any) -> None:
        if selector != MuxSignal.SEL_RETURN_INPUT_PC_NEXT:
            raise RuntimeError(f"Invalid return stack input selector: {selector}")

        value = self.pc + INSTRUCTION_SIZE_BYTES
        index = self.r_to_index(self.selected_return_addr)
        self.ensure_return_stack_index(index)
        self.datapath.return_stack[index] = value

    def latch_r(self, selector: Any) -> None:
        if selector == MuxSignal.SEL_R_NEXT:
            self.next_r = self.r + DATA_WORD_SIZE_BYTES
            return

        if selector == MuxSignal.SEL_R_PREV:
            if self.r == EMPTY_R:
                raise RuntimeError("Return stack underflow")
            self.next_r = self.r - DATA_WORD_SIZE_BYTES
            return

        raise RuntimeError(f"Invalid R selector: {selector}")

    @staticmethod
    def port_from_selector(selector: Any, operand: int) -> int:
        if selector == MuxSignal.SEL_PORT_OPERAND:
            return operand
        raise RuntimeError(f"Invalid port selector: {selector}")

    # Logging
    def write_log(self, mpc_before: int, microinstruction: MicroInstruction) -> None:
        if self.ir is None:
            ir_text = "None"
        else:
            ir_text = self.ir.disasm(self.pc)

        stack_top = self.datapath.stack_top_snapshot()

        def fit(value: object, width: int, align: str = "<") -> str:
            text = str(value)

            if len(text) > width:
                if width <= 3:
                    text = text[:width]
                else:
                    text = text[: width - 3] + "..."

            return f"{text:{align}{width}}"

        out_text = repr(self.datapath.output_text())
        ret_text = repr(self.datapath.return_stack)
        stack_text = repr(stack_top)
        micro_text = "; ".join(str(signal) for signal in microinstruction.signals)

        line = " | ".join(
            [
                f"TICK={self.tick:06d}",
                f"PC={self.pc:04d}",
                f"MPC={mpc_before:03d}->{self.mpc:03d}",
                f"IR={fit(ir_text, 32)}",
                f"SIGNALS={fit(micro_text, 56)}",
                f"SP={self.datapath.sp:>5d}",
                f"T={self.datapath.t:>11d}",
                f"F={self.datapath.f:>11d}",
                f"AR={self.datapath.ar:>5d}",
                f"R={self.r:>5d}",
                f"ALU={self.last_alu_result:>11d}",
                f"ZF={int(self.datapath.zero_flag)}",
                f"NF={int(self.datapath.negative_flag)}",
                f"STACK={fit(stack_text, 24)}",
                f"RET={fit(ret_text, 16)}",
                f"OUT={fit(out_text, 40)}",
            ]
        )

        self.log.append(line.rstrip())


@dataclass(frozen=True)
class SimulationResult:
    output: str
    log: list[str]
    ticks: int
    halt_reason: str
    data_stack: list[int]
    return_stack: list[int]
    data_memory: list[int]


def simulation(
    instructions: list[Instruction],
    input_text: str = "",
    data_memory_size: int = DEFAULT_DATA_MEMORY_SIZE,
    tick_limit: int = DEFAULT_TICK_LIMIT,
    initial_data_memory: list[int] | None = None,
) -> SimulationResult:
    datapath = DataPath(
        data_memory_size=data_memory_size,
        input_text=input_text,
        initial_data_memory=initial_data_memory,
    )

    control_unit = ControlUnit(
        instruction_memory=instructions,
        datapath=datapath,
    )

    control_unit.run(tick_limit=tick_limit)

    return SimulationResult(
        output=datapath.output_text(),
        log=control_unit.log,
        ticks=control_unit.tick,
        halt_reason=control_unit.halt_reason,
        data_stack=datapath.stack_snapshot(),
        return_stack=datapath.return_stack.copy(),
        data_memory=list(datapath.data_memory),
    )

def read_data_file(filename: str | None) -> list[int] | None:
    if filename is None:
        return None

    data = json.loads(Path(filename).read_text(encoding="utf-8"))

    if not isinstance(data, list):
        raise RuntimeError("Data memory file must contain JSON array")

    return [int(value) for value in data]


def read_input_file(filename: str | None) -> str:
    if filename is None:
        return ""

    return Path(filename).read_text(encoding="utf-8")


def write_output_file(filename: str | None, output: str) -> None:
    if filename is not None:
        Path(filename).write_text(output, encoding="utf-8")


def write_log_file(filename: str | None, log: list[str]) -> None:
    if filename is not None:
        Path(filename).write_text("\n".join(log) + "\n", encoding="utf-8")


def write_data_memory_file(filename: str | None, data_memory: list[int]) -> None:
    if filename is not None:
        Path(filename).write_text(
            json.dumps(data_memory, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stack processor simulator with signal-level microcoded Control Unit."
    )

    parser.add_argument(
        "--data",
        help="Path to initial data memory JSON file.",
        default=None,
    )
    parser.add_argument(
        "code",
        help="Path to binary machine code file.",
    )
    parser.add_argument(
        "--input",
        help="Path to input stream file.",
        default=None,
    )
    parser.add_argument(
        "--output",
        help="Path to output file.",
        default=None,
    )
    parser.add_argument(
        "--log",
        help="Path to machine log file.",
        default=None,
    )
    parser.add_argument(
        "--data-output",
        help="Path to output final data memory JSON file.",
        default=None,
    )
    parser.add_argument(
        "--tick-limit",
        type=int,
        default=DEFAULT_TICK_LIMIT,
        help="Maximum number of ticks.",
    )
    parser.add_argument(
        "--data-memory-size",
        type=int,
        default=DEFAULT_DATA_MEMORY_SIZE,
        help="Data memory size in bytes.",
    )
    args = parser.parse_args()

    instructions = read_code(args.code)
    input_text = read_input_file(args.input)
    initial_data_memory = read_data_file(args.data)

    result = simulation(
        instructions=instructions,
        input_text=input_text,
        data_memory_size=args.data_memory_size,
        tick_limit=args.tick_limit,
        initial_data_memory=initial_data_memory,
    )

    write_output_file(args.output, result.output)
    write_log_file(args.log, result.log)
    write_data_memory_file(args.data_output, result.data_memory)

    print(result.output, end="")
    print(f"\n\nTicks: {result.ticks}")
    print(f"Halt reason: {result.halt_reason}")


if __name__ == "__main__":
    main()
