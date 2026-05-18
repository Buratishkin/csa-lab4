from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from isa import Instruction, read_code
from microcode import MicroOp, get_microprogram

DEFAULT_DATA_MEMORY_SIZE = 4096
DEFAULT_TICK_LIMIT = 100_000

INPUT_PORT = 0
OUTPUT_PORT = 1

INTERRUPT_VECTOR_ADDR = 0x00
INTERRUPT_DEVICE_CELL = 0x01

# DataPath
@dataclass
class DataPath:
    data_memory_size: int = DEFAULT_DATA_MEMORY_SIZE
    input_text: str = ""
    initial_data_memory: list[int] | None = None

    data_memory: list[int] = field(init=False)

    data_stack: list[int] = field(default_factory=list)
    return_stack: list[int] = field(default_factory=list)

    input_buffer: list[int] = field(init=False)
    output_buffer: list[int] = field(default_factory=list)

    reg_a: int = 0
    reg_b: int = 0
    alu_result: int = 0

    zero_flag: bool = False
    negative_flag: bool = False

    def __post_init__(self) -> None:
        self.data_memory = [0] * self.data_memory_size

        if self.initial_data_memory is not None:
            if len(self.initial_data_memory) > self.data_memory_size:
                raise RuntimeError(
                    f"Initial data memory is too large: "
                    f"{len(self.initial_data_memory)} > {self.data_memory_size}"
                )

            for address, value in enumerate(self.initial_data_memory):
                self.data_memory[address] = self.normalize_word(value)

        self.input_buffer = [ord(ch) for ch in self.input_text]

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

    # data stack
    def push(self, value: int) -> None:
        """
        Push value to the data stack.
        """
        self.data_stack.append(self.normalize_word(value))

    def pop(self) -> int:
        """
        Pop value from the data stack.
        """
        if not self.data_stack:
            raise RuntimeError("Data stack underflow")

        return self.data_stack.pop()

    def peek(self) -> int:
        if not self.data_stack:
            raise RuntimeError("Data stack is empty")

        return self.data_stack[-1]

    def stack_snapshot(self) -> list[int]:
        """
        Return stack content from bottom to top.
        """
        return self.data_stack.copy()

    def stack_top_snapshot(self, limit: int = 6) -> list[int]:
        return self.stack_snapshot()[-limit:]

    # return stack
    def push_return(self, address: int) -> None:
        self.return_stack.append(address)

    def pop_return(self) -> int:
        if not self.return_stack:
            raise RuntimeError("Return stack underflow")

        return self.return_stack.pop()

    # data memory
    def check_data_addr(self, address: int) -> None:
        if not 0 <= address < len(self.data_memory):
            raise RuntimeError(f"Data memory address out of range: {address}")

    def read_memory(self, address: int) -> int:
        self.check_data_addr(address)
        return self.data_memory[address]

    def write_memory(self, address: int, value: int) -> None:
        self.check_data_addr(address)
        self.data_memory[address] = self.normalize_word(value)

    # ports
    def read_port(self, port: int) -> int:
        if port != INPUT_PORT:
            raise RuntimeError(f"Unknown input port: {port}")

        if not self.input_buffer:
            raise StopIteration("Input stream exhausted")

        return self.input_buffer.pop(0)

    def write_port(self, port: int, value: int) -> None:
        if port != OUTPUT_PORT:
            raise RuntimeError(f"Unknown output port: {port}")

        self.output_buffer.append(value & 0xFF)

    def output_text(self) -> str:
        return "".join(chr(value) for value in self.output_buffer)


@dataclass
class ControlUnit:
    instruction_memory: list[Instruction]
    datapath: DataPath

    pc: int = 0
    ir: Instruction | None = None
    mpc: int = 0

    tick: int = 0
    halted: bool = False
    halt_reason: str = ""

    current_microprogram: list[MicroOp] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    interrupt_ticks: list[int] = field(default_factory=list)
    interrupt_device_symbol: int = ord("!")
    interrupt_enable: bool = False
    inside_interrupt: bool = False
    interrupt_stack: list[dict[str, object]] = field(default_factory=list)
    next_interrupt_index: int = 0
    interrupts_handled: int = 0
    last_interrupt_event: str = "-"

    def __post_init__(self) -> None:
        self.interrupt_ticks = sorted(int(tick) for tick in self.interrupt_ticks)

    def run(self, tick_limit: int = DEFAULT_TICK_LIMIT) -> None:
        while not self.halted and self.tick < tick_limit:
            self.step_tick()

        if self.tick >= tick_limit and not self.halted:
            self.halted = True
            self.halt_reason = f"Tick limit exceeded: {tick_limit}"

    def step_tick(self) -> None:
        self.tick += 1
        self.last_interrupt_event = "-"
        if self.ir is None and self.should_fire_hardware_interrupt():
            self.enter_interrupt(event_name="HW_INTERRUPT", return_pc=self.pc)
            self.write_log("HW_INTERRUPT")
            return

        if self.ir is None:
            self.fetch_instruction()
            self.write_log("FETCH")
            return

        if self.mpc < 0 or self.mpc >= len(self.current_microprogram):
            raise RuntimeError(f"MPC out of range: {self.mpc}")

        micro_op = self.current_microprogram[self.mpc]
        self.execute_micro_op(micro_op)
        self.write_log(micro_op.value)

    def should_fire_hardware_interrupt(self) -> bool:
        if not self.interrupt_enable or self.inside_interrupt:
            return False

        if self.next_interrupt_index >= len(self.interrupt_ticks):
            return False

        scheduled_tick = self.interrupt_ticks[self.next_interrupt_index]

        if self.tick < scheduled_tick:
            return False

        self.next_interrupt_index += 1
        return True

    def enter_interrupt(self, event_name: str, return_pc: int) -> None:
        dp = self.datapath
        handler_addr = dp.read_memory(INTERRUPT_VECTOR_ADDR)

        if handler_addr == 0:
            raise RuntimeError(
                "Interrupt vector is not set: "
                f"data_memory[{INTERRUPT_VECTOR_ADDR:#04x}] == 0"
            )

        if not 0 <= handler_addr < len(self.instruction_memory):
            raise RuntimeError(f"Interrupt handler address out of range: {handler_addr}")

        self.interrupt_stack.append(
            {
                "pc": return_pc,
                "reg_a": dp.reg_a,
                "reg_b": dp.reg_b,
                "alu_result": dp.alu_result,
                "zero_flag": dp.zero_flag,
                "negative_flag": dp.negative_flag,
                "data_stack": dp.data_stack.copy(),
                "return_stack": dp.return_stack.copy(),
                "interrupt_enable": self.interrupt_enable,
            }
        )

        self.interrupt_enable = False
        self.inside_interrupt = True
        self.interrupts_handled += 1
        self.last_interrupt_event = f"{event_name}->handler@{handler_addr}"

        dp.write_memory(INTERRUPT_DEVICE_CELL, self.interrupt_device_symbol)

        self.pc = handler_addr
        self.finish_instruction()

    def return_from_interrupt(self) -> None:
        if not self.interrupt_stack:
            raise RuntimeError("Interrupt stack underflow")

        state = self.interrupt_stack.pop()
        dp = self.datapath

        self.pc = int(state["pc"])
        dp.reg_a = int(state["reg_a"])
        dp.reg_b = int(state["reg_b"])
        dp.alu_result = int(state["alu_result"])
        dp.zero_flag = bool(state["zero_flag"])
        dp.negative_flag = bool(state["negative_flag"])
        dp.data_stack = list(state["data_stack"])  # type: ignore[arg-type]
        dp.return_stack = list(state["return_stack"])  # type: ignore[arg-type]

        self.interrupt_enable = bool(state["interrupt_enable"])
        self.inside_interrupt = False
        self.last_interrupt_event = "IRET"

        self.finish_instruction()

    # fetch/decode
    def fetch_instruction(self) -> None:
        if not 0 <= self.pc < len(self.instruction_memory):
            raise RuntimeError(f"PC out of instruction memory: {self.pc}")

        self.ir = self.instruction_memory[self.pc]
        self.current_microprogram = get_microprogram(self.ir.opcode)
        self.mpc = 0

    def finish_instruction(self) -> None:
        self.ir = None
        self.current_microprogram = []
        self.mpc = 0

    # micro-op execution
    def execute_micro_op(self, micro_op: MicroOp) -> None:
        if self.ir is None:
            raise RuntimeError("IR is empty")

        dp = self.datapath

        match micro_op:
            # Stack
            case MicroOp.PUSH_IR_OPERAND:
                dp.push(self.ir.operand)
                self.mpc += 1

            case MicroOp.DROP:
                dp.pop()
                self.mpc += 1

            case MicroOp.DUP:
                dp.push(dp.peek())
                self.mpc += 1

            case MicroOp.SWAP:
                first = dp.pop()
                second = dp.pop()
                dp.push(first)
                dp.push(second)
                self.mpc += 1

            # Data memory
            case MicroOp.LOAD_DIRECT:
                address = self.ir.operand
                value = dp.read_memory(address)
                dp.push(value)
                self.mpc += 1

            case MicroOp.STORE_DIRECT:
                address = self.ir.operand
                value = dp.pop()
                dp.write_memory(address, value)
                self.mpc += 1

            case MicroOp.LOAD_INDIRECT:
                address = dp.pop()
                value = dp.read_memory(address)
                dp.push(value)
                self.mpc += 1

            case MicroOp.STORE_INDIRECT:
                value = dp.pop()
                address = dp.pop()
                dp.write_memory(address, value)
                self.mpc += 1

            # ALU input
            case MicroOp.POP_A:
                dp.reg_a = dp.pop()
                self.mpc += 1

            case MicroOp.POP_B:
                dp.reg_b = dp.pop()
                self.mpc += 1

            # ALU operations
            case MicroOp.ALU_ADD:
                self.write_alu_result(dp.reg_b + dp.reg_a)

            case MicroOp.ALU_SUB:
                self.write_alu_result(dp.reg_b - dp.reg_a)

            case MicroOp.ALU_MUL:
                self.write_alu_result(dp.reg_b * dp.reg_a)

            case MicroOp.ALU_DIV:
                if dp.reg_a == 0:
                    raise RuntimeError("Division by zero")
                self.write_alu_result(int(dp.reg_b / dp.reg_a))

            case MicroOp.ALU_MOD:
                if dp.reg_a == 0:
                    raise RuntimeError("Modulo by zero")
                self.write_alu_result(dp.reg_b % dp.reg_a)

            case MicroOp.ALU_EQ:
                self.write_alu_result(int(dp.reg_b == dp.reg_a))

            case MicroOp.ALU_NE:
                self.write_alu_result(int(dp.reg_b != dp.reg_a))

            case MicroOp.ALU_LT:
                self.write_alu_result(int(dp.reg_b < dp.reg_a))

            case MicroOp.ALU_GT:
                self.write_alu_result(int(dp.reg_b > dp.reg_a))

            case MicroOp.ALU_LE:
                self.write_alu_result(int(dp.reg_b <= dp.reg_a))

            case MicroOp.ALU_GE:
                self.write_alu_result(int(dp.reg_b >= dp.reg_a))

            case MicroOp.PUSH_ALU:
                dp.push(dp.alu_result)
                self.mpc += 1

            # Control flow
            case MicroOp.JMP:
                self.pc = self.ir.operand
                self.finish_instruction()

            case MicroOp.JZ:
                condition = dp.pop()
                if condition == 0:
                    self.pc = self.ir.operand
                else:
                    self.pc += 1
                self.finish_instruction()

            case MicroOp.JNZ:
                condition = dp.pop()
                if condition != 0:
                    self.pc = self.ir.operand
                else:
                    self.pc += 1
                self.finish_instruction()

            case MicroOp.CALL:
                dp.push_return(self.pc + 1)
                self.pc = self.ir.operand
                self.finish_instruction()

            case MicroOp.RET:
                self.pc = dp.pop_return()
                self.finish_instruction()

            case MicroOp.INC_PC:
                self.pc += 1
                self.mpc += 1

            # Interrupts
            case MicroOp.INT:
                if self.ir.operand != 0:
                    raise RuntimeError(
                        f"Only interrupt number 0 is supported, got {self.ir.operand}"
                    )
                self.enter_interrupt(
                    event_name=f"SW_INT_{self.ir.operand}",
                    return_pc=self.pc + 1,
                )

            case MicroOp.IRET:
                self.return_from_interrupt()

            case MicroOp.EI:
                self.interrupt_enable = True
                self.pc += 1
                self.finish_instruction()

            case MicroOp.DI:
                self.interrupt_enable = False
                self.pc += 1
                self.finish_instruction()

            # Port-mapped I/O
            case MicroOp.PORT_IN:
                try:
                    value = dp.read_port(self.ir.operand)
                except StopIteration:
                    self.halted = True
                    self.halt_reason = "Input stream exhausted"
                    return

                dp.push(value)
                self.mpc += 1

            case MicroOp.PORT_OUT:
                value = dp.pop()
                dp.write_port(self.ir.operand, value)
                self.mpc += 1

            # System
            case MicroOp.HALT:
                self.halted = True
                self.halt_reason = "HALT instruction"
                self.mpc += 1

            case MicroOp.END_INSTRUCTION:
                self.finish_instruction()

            case _:
                raise RuntimeError(f"Unknown micro-op: {micro_op}")

    def write_alu_result(self, value: int) -> None:
        value = self.datapath.normalize_word(value)
        self.datapath.alu_result = value
        self.datapath.set_flags(value)
        self.mpc += 1

    # Logging
    def write_log(self, micro_op_name: str) -> None:
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

        line = " | ".join(
            [
                f"TICK={self.tick:06d}",
                f"PC={self.pc:04d}",
                f"MPC={self.mpc:02d}",
                f"IR={fit(ir_text, 32)}",
                f"MICRO={fit(micro_op_name, 16)}",
                f"A={self.datapath.reg_a:>11d}",
                f"B={self.datapath.reg_b:>11d}",
                f"ALU={self.datapath.alu_result:>11d}",
                f"ZF={int(self.datapath.zero_flag)}",
                f"NF={int(self.datapath.negative_flag)}",
                f"STACK={fit(stack_text, 24)}",
                f"IE={int(self.interrupt_enable)}",
                f"IN_INT={int(self.inside_interrupt)}",
                f"INT={fit(self.last_interrupt_event, 24)}",
                f"INT_COUNT={self.interrupts_handled:03d}",
                f"DEV={self.datapath.read_memory(INTERRUPT_DEVICE_CELL):>4d}",
                f"RET={fit(ret_text, 16)}",
                f"OUT={fit(out_text, 40)}",
            ]
        )

        self.log.append(line.rstrip())



# Simulation API
@dataclass(frozen=True)
class SimulationResult:
    output: str
    log: list[str]
    ticks: int
    halt_reason: str
    data_stack: list[int]
    return_stack: list[int]
    data_memory: list[int]
    interrupts_handled: int


def simulation(
    instructions: list[Instruction],
    input_text: str = "",
    data_memory_size: int = DEFAULT_DATA_MEMORY_SIZE,
    tick_limit: int = DEFAULT_TICK_LIMIT,
    initial_data_memory: list[int] | None = None,
    interrupt_ticks: list[int] | None = None,
    interrupt_device_symbol: int = ord("!"),
) -> SimulationResult:
    datapath = DataPath(
        data_memory_size=data_memory_size,
        input_text=input_text,
        initial_data_memory=initial_data_memory,
    )

    control_unit = ControlUnit(
        instruction_memory=instructions,
        datapath=datapath,
        interrupt_ticks=interrupt_ticks or [],
        interrupt_device_symbol=interrupt_device_symbol,
    )

    control_unit.run(tick_limit=tick_limit)

    return SimulationResult(
        output=datapath.output_text(),
        log=control_unit.log,
        ticks=control_unit.tick,
        halt_reason=control_unit.halt_reason,
        data_stack=datapath.stack_snapshot(),
        return_stack=datapath.return_stack.copy(),
        data_memory=datapath.data_memory.copy(),
        interrupts_handled=control_unit.interrupts_handled,
    )


# CLI
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

def parse_interrupt_ticks(value: str | None) -> list[int]:
    if value is None or value.strip() == "":
        return []

    result: list[int] = []

    for item in value.split(","):
        item = item.strip()

        if not item:
            continue

        tick = int(item)

        if tick <= 0:
            raise RuntimeError(f"Interrupt tick must be positive: {tick}")

        result.append(tick)

    return result


def parse_interrupt_symbol(value: str) -> int:
    if len(value) != 1:
        raise RuntimeError("--interrupt-symbol must contain exactly one character")

    return ord(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stack processor simulator with microcoded Control Unit."
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
        help="Data memory size in 32-bit words.",
    )
    parser.add_argument(
        "--interrupt-ticks",
        default="",
        help="Comma-separated hardware interrupt schedule, for example: 40 or 40,120.",
    )

    parser.add_argument(
        "--interrupt-symbol",
        default="!",
        help="One character placed into data_memory[0x04] when interrupt fires.",
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
        interrupt_ticks=parse_interrupt_ticks(args.interrupt_ticks),
        interrupt_device_symbol=parse_interrupt_symbol(args.interrupt_symbol),
    )

    write_output_file(args.output, result.output)
    write_log_file(args.log, result.log)
    write_data_memory_file(args.data_output, result.data_memory)

    print(result.output, end="")
    print(f"\n\nTicks: {result.ticks}")
    print(f"Halt reason: {result.halt_reason}")
    print(f"Interrupts handled: {result.interrupts_handled}")


if __name__ == "__main__":
    main()
