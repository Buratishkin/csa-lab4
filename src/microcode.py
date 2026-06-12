from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeAlias

from src.isa import Opcode


class MuxSignal(Enum):
    # SP mux
    SEL_SP_NEXT = auto()                 # SP + 4
    SEL_SP_PREV = auto()                 # SP - 4

    # stack write address selector
    SEL_STACK_ADDR_CURRENT = auto()      # Stack[SP]
    SEL_STACK_ADDR_NEXT = auto()         # Stack[SP + 4]

    # stack mux sources
    SEL_STACK_IMM = auto()               # IR.operand
    SEL_STACK_MEMORY = auto()            # DataMemory[AR]
    SEL_STACK_ALU = auto()               # ALU result
    SEL_STACK_INPUT = auto()             # input port value
    SEL_STACK_T = auto()                 # cached top T, for DUP

    # T mux sources
    SEL_T_STACK_MUX = auto()             # output of stack mux
    SEL_T_STACK_PREV = auto()            # Stack[SP - 4]

    # F mux sources
    SEL_F_T = auto()                     # old T, used only by ALU operations

    # addr mux sources, latched into AR by LATCH_AR
    SEL_ADDR_OPERAND = auto()            # IR.operand
    SEL_ADDR_T = auto()                  # old T, used by LOADI / STOREI

    # data memory write-data mux
    SEL_DATA_IN_T = auto()               # old T

    # PC mux
    SEL_PC_NEXT = auto()                 # PC + 4
    SEL_PC_OPERAND = auto()              # IR.operand
    SEL_PC_JZ_BY_T = auto()              # IR.operand if T == 0 else PC + 4
    SEL_PC_JNZ_BY_T = auto()             # IR.operand if T != 0 else PC + 4
    SEL_PC_RETURN_STACK = auto()         # ReturnStack[R]

    # mPC mux
    SEL_MPC_NEXT = auto()
    SEL_MPC_FETCH = auto()
    SEL_MPC_OPCODE = auto()

    # return stack / R mux
    SEL_RETURN_STACK_NEXT = auto()       # ReturnStack[R + 4]
    SEL_RETURN_STACK_CURRENT = auto()    # ReturnStack[R]
    SEL_RETURN_INPUT_PC_NEXT = auto()    # PC + 4
    SEL_R_NEXT = auto()                  # R + 4
    SEL_R_PREV = auto()                  # R - 4

    # I/O port selector
    SEL_PORT_OPERAND = auto()


class ALUSignal(Enum):
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()

    EQ = auto()
    NE = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()


class Signal(Enum):
    # instruction/control registers
    LATCH_IR = auto()
    LATCH_MPC = auto()
    LATCH_PC = auto()

    # datapath registers
    LATCH_SP = auto()
    LATCH_T = auto()
    LATCH_F = auto()
    LATCH_AR = auto()

    # stack and memory
    SELECT_STACK_ADDR = auto()
    WRITE_STACK = auto()
    SELECT_DATA_ADDRESS = auto()
    WRITE_DATA_MEMORY = auto()

    # ALU and flags
    ALU = auto()
    LATCH_NZ = auto()

    # return stack
    SELECT_RETURN_STACK_ADDR = auto()
    WRITE_RETURN_STACK = auto()
    LATCH_R = auto()

    # I/O
    READ_IO = auto()
    WRITE_IO = auto()

    # system
    HALT = auto()


Selector: TypeAlias = MuxSignal | ALUSignal | None


@dataclass(frozen=True)
class ControlSignal:
    signal: Signal
    selector: Selector = None

    def __str__(self) -> str:
        if self.selector is None:
            return self.signal.name.lower()
        return f"{self.signal.name.lower()}({self.selector.name.lower()})"


@dataclass(frozen=True)
class MicroInstruction:
    signals: tuple[ControlSignal, ...]
    comment: str = ""

    def __iter__(self):
        return iter(self.signals)

    def __str__(self) -> str:
        body = ", ".join(str(signal) for signal in self.signals)
        if self.comment:
            return f"{body}  # {self.comment}"
        return body


def CS(signal: Signal, selector: Selector = None) -> ControlSignal:
    return ControlSignal(signal, selector)


def MI(*signals: ControlSignal, comment: str = "") -> MicroInstruction:
    return MicroInstruction(tuple(signals), comment)


# Common control fragments.
MPC_NEXT = CS(Signal.LATCH_MPC, MuxSignal.SEL_MPC_NEXT)
MPC_FETCH = CS(Signal.LATCH_MPC, MuxSignal.SEL_MPC_FETCH)
PC_NEXT = CS(Signal.LATCH_PC, MuxSignal.SEL_PC_NEXT)
SP_NEXT = CS(Signal.LATCH_SP, MuxSignal.SEL_SP_NEXT)
SP_PREV = CS(Signal.LATCH_SP, MuxSignal.SEL_SP_PREV)

STACK_ADDR_NEXT = CS(Signal.SELECT_STACK_ADDR, MuxSignal.SEL_STACK_ADDR_NEXT)
STACK_ADDR_CURRENT = CS(Signal.SELECT_STACK_ADDR, MuxSignal.SEL_STACK_ADDR_CURRENT)

LATCH_T_FROM_STACK_MUX = CS(Signal.LATCH_T, MuxSignal.SEL_T_STACK_MUX)
LATCH_T_FROM_STACK_PREV = CS(Signal.LATCH_T, MuxSignal.SEL_T_STACK_PREV)
LATCH_F_FROM_T = CS(Signal.LATCH_F, MuxSignal.SEL_F_T)
LATCH_AR = CS(Signal.LATCH_AR)


class MicrocodeBuilder:
    def __init__(self) -> None:
        self.program: list[MicroInstruction] = []
        self.entry_points: dict[Opcode, int] = {}
        self.labels: dict[str, int] = {}

    def label(self, name: str) -> int:
        address = len(self.program)
        self.labels[name] = address
        return address

    def add_raw(self, name: str, *microinstructions: MicroInstruction) -> int:
        start = self.label(name)
        self.program.extend(microinstructions)
        return start

    def add_opcode(self, opcode: Opcode, *microinstructions: MicroInstruction) -> int:
        start = len(self.program)
        self.entry_points[opcode] = start
        self.program.extend(microinstructions)
        return start


def _push_from_stack_mux(source: MuxSignal, comment: str) -> MicroInstruction:
    """Push stack_mux(source) and update T cache."""

    return MI(
        STACK_ADDR_NEXT,
        CS(Signal.WRITE_STACK, source),
        LATCH_T_FROM_STACK_MUX,
        SP_NEXT,
        PC_NEXT,
        MPC_FETCH,
        comment=comment,
    )


def _pop_top_and_refresh_t() -> tuple[ControlSignal, ...]:
    """Signals for removing current T/Stack[SP] and loading new top into T."""

    return (
        LATCH_T_FROM_STACK_PREV,
        SP_PREV,
        PC_NEXT,
        MPC_FETCH,
    )


def _latch_ar_from_addr_mux(source: MuxSignal, comment: str) -> MicroInstruction:
    return MI(
        CS(Signal.SELECT_DATA_ADDRESS, source),
        LATCH_AR,
        MPC_NEXT,
        comment=comment,
    )


def _binary_alu_microinstructions(alu_signal: ALUSignal, name: str) -> tuple[MicroInstruction, ...]:
    """Microcode for binary stack operations."""

    return (
        MI(
            LATCH_F_FROM_T,
            LATCH_T_FROM_STACK_PREV,
            SP_PREV,
            MPC_NEXT,
            comment=f"{name}: F = right(old T), T = left(Stack[SP-4]), SP -= 4",
        ),
        MI(
            CS(Signal.ALU, alu_signal),
            STACK_ADDR_CURRENT,
            CS(Signal.WRITE_STACK, MuxSignal.SEL_STACK_ALU),
            LATCH_T_FROM_STACK_MUX,
            CS(Signal.LATCH_NZ),
            PC_NEXT,
            MPC_FETCH,
            comment=f"{name}: Stack[SP] = T op F, T = result",
        ),
    )


def build_microprogram() -> tuple[list[MicroInstruction], dict[Opcode, int], dict[str, int]]:
    b = MicrocodeBuilder()

    # 0. Instruction Fetch.
    b.add_raw(
        "FETCH",
        MI(
            CS(Signal.LATCH_IR),
            CS(Signal.LATCH_MPC, MuxSignal.SEL_MPC_OPCODE),
            comment="IR = InstructionMemory[PC]; mPC = opcode_to_mpc[IR.opcode]",
        ),
    )

    # System.
    b.add_opcode(
        Opcode.HALT,
        MI(CS(Signal.HALT), comment="stop simulation"),
    )

    # Stack.
    b.add_opcode(
        Opcode.PUSHI,
        _push_from_stack_mux(
            MuxSignal.SEL_STACK_IMM,
            "PUSHI: Stack[SP+4] = IR.operand; T = IR.operand; SP += 4",
        ),
    )
    b.add_opcode(
        Opcode.DROP,
        MI(
            *_pop_top_and_refresh_t(),
            comment="DROP: T = Stack[SP-4]; SP -= 4",
        ),
    )
    b.add_opcode(
        Opcode.DUP,
        MI(
            STACK_ADDR_NEXT,
            CS(Signal.WRITE_STACK, MuxSignal.SEL_STACK_T),
            SP_NEXT,
            PC_NEXT,
            MPC_FETCH,
            comment="DUP: Stack[SP+4] = T; SP += 4; T is unchanged",
        ),
    )

    # Data memory. Address selection is always separated from memory access by AR.
    b.add_opcode(
        Opcode.LOAD,
        _latch_ar_from_addr_mux(
            MuxSignal.SEL_ADDR_OPERAND,
            "LOAD/1: AR = IR.operand",
        ),
        MI(
            STACK_ADDR_NEXT,
            CS(Signal.WRITE_STACK, MuxSignal.SEL_STACK_MEMORY),
            LATCH_T_FROM_STACK_MUX,
            SP_NEXT,
            PC_NEXT,
            MPC_FETCH,
            comment="LOAD/2: Stack[SP+4] = DataMemory[AR]; T = loaded value",
        ),
    )
    b.add_opcode(
        Opcode.STORE,
        _latch_ar_from_addr_mux(
            MuxSignal.SEL_ADDR_OPERAND,
            "STORE/1: AR = IR.operand",
        ),
        MI(
            CS(Signal.WRITE_DATA_MEMORY, MuxSignal.SEL_DATA_IN_T),
            LATCH_T_FROM_STACK_PREV,
            SP_PREV,
            PC_NEXT,
            MPC_FETCH,
            comment="STORE/2: DataMemory[AR] = T; pop value; T = Stack[SP-4]",
        ),
    )
    b.add_opcode(
        Opcode.LOADI,
        _latch_ar_from_addr_mux(
            MuxSignal.SEL_ADDR_T,
            "LOADI/1: AR = T",
        ),
        MI(
            STACK_ADDR_CURRENT,
            CS(Signal.WRITE_STACK, MuxSignal.SEL_STACK_MEMORY),
            LATCH_T_FROM_STACK_MUX,
            PC_NEXT,
            MPC_FETCH,
            comment="LOADI/2: Stack[SP] = DataMemory[AR]; T = loaded value",
        ),
    )
    b.add_opcode(
        Opcode.STOREI,
        MI(
            CS(Signal.SELECT_DATA_ADDRESS, MuxSignal.SEL_ADDR_T),
            LATCH_AR,
            LATCH_T_FROM_STACK_PREV,
            SP_PREV,
            MPC_NEXT,
            comment="STOREI/1: AR = T(address); pop address; T = value",
        ),
        MI(
            CS(Signal.WRITE_DATA_MEMORY, MuxSignal.SEL_DATA_IN_T),
            LATCH_T_FROM_STACK_PREV,
            SP_PREV,
            PC_NEXT,
            MPC_FETCH,
            comment="STOREI/2: DataMemory[AR] = T(value); pop value; T = Stack[SP-4]",
        ),
    )

    # Arithmetic.
    b.add_opcode(Opcode.ADD, *_binary_alu_microinstructions(ALUSignal.ADD, "ADD"))
    b.add_opcode(Opcode.SUB, *_binary_alu_microinstructions(ALUSignal.SUB, "SUB"))
    b.add_opcode(Opcode.MUL, *_binary_alu_microinstructions(ALUSignal.MUL, "MUL"))
    b.add_opcode(Opcode.DIV, *_binary_alu_microinstructions(ALUSignal.DIV, "DIV"))
    b.add_opcode(Opcode.MOD, *_binary_alu_microinstructions(ALUSignal.MOD, "MOD"))

    # Comparisons.
    b.add_opcode(Opcode.EQ, *_binary_alu_microinstructions(ALUSignal.EQ, "EQ"))
    b.add_opcode(Opcode.NE, *_binary_alu_microinstructions(ALUSignal.NE, "NE"))
    b.add_opcode(Opcode.LT, *_binary_alu_microinstructions(ALUSignal.LT, "LT"))
    b.add_opcode(Opcode.GT, *_binary_alu_microinstructions(ALUSignal.GT, "GT"))
    b.add_opcode(Opcode.LE, *_binary_alu_microinstructions(ALUSignal.LE, "LE"))
    b.add_opcode(Opcode.GE, *_binary_alu_microinstructions(ALUSignal.GE, "GE"))

    # Control flow.
    b.add_opcode(
        Opcode.JMP,
        MI(
            CS(Signal.LATCH_PC, MuxSignal.SEL_PC_OPERAND),
            MPC_FETCH,
            comment="JMP: PC = IR.operand",
        ),
    )
    b.add_opcode(
        Opcode.JZ,
        MI(
            CS(Signal.LATCH_PC, MuxSignal.SEL_PC_JZ_BY_T),
            LATCH_T_FROM_STACK_PREV,
            SP_PREV,
            MPC_FETCH,
            comment="JZ: branch by T == 0; pop condition; T = Stack[SP-4]",
        ),
    )
    b.add_opcode(
        Opcode.JNZ,
        MI(
            CS(Signal.LATCH_PC, MuxSignal.SEL_PC_JNZ_BY_T),
            LATCH_T_FROM_STACK_PREV,
            SP_PREV,
            MPC_FETCH,
            comment="JNZ: branch by T != 0; pop condition; T = Stack[SP-4]",
        ),
    )

    # Procedures.
    b.add_opcode(
        Opcode.CALL,
        MI(
            CS(Signal.SELECT_RETURN_STACK_ADDR, MuxSignal.SEL_RETURN_STACK_NEXT),
            CS(Signal.WRITE_RETURN_STACK, MuxSignal.SEL_RETURN_INPUT_PC_NEXT),
            CS(Signal.LATCH_R, MuxSignal.SEL_R_NEXT),
            CS(Signal.LATCH_PC, MuxSignal.SEL_PC_OPERAND),
            MPC_FETCH,
            comment="CALL: ReturnStack[R+4] = PC+4; R += 4; PC = IR.operand",
        ),
    )
    b.add_opcode(
        Opcode.RET,
        MI(
            CS(Signal.LATCH_PC, MuxSignal.SEL_PC_RETURN_STACK),
            CS(Signal.LATCH_R, MuxSignal.SEL_R_PREV),
            MPC_FETCH,
            comment="RET: PC = ReturnStack[R]; R -= 4",
        ),
    )

    # Port-mapped I/O.
    b.add_opcode(
        Opcode.IN,
        MI(
            CS(Signal.READ_IO, MuxSignal.SEL_PORT_OPERAND),
            STACK_ADDR_NEXT,
            CS(Signal.WRITE_STACK, MuxSignal.SEL_STACK_INPUT),
            LATCH_T_FROM_STACK_MUX,
            SP_NEXT,
            PC_NEXT,
            MPC_FETCH,
            comment="IN: read input[IR.operand]; push value; T = value",
        ),
    )
    b.add_opcode(
        Opcode.OUT,
        MI(
            CS(Signal.WRITE_IO, MuxSignal.SEL_PORT_OPERAND),
            LATCH_T_FROM_STACK_PREV,
            SP_PREV,
            PC_NEXT,
            MPC_FETCH,
            comment="OUT: output[IR.operand] = T; pop value; T = Stack[SP-4]",
        ),
    )

    return b.program, b.entry_points, b.labels


MICROPROGRAM, MPC_OF_OPCODE, LABELS = build_microprogram()

FETCH_ADDR = LABELS["FETCH"]


def microinstructions_for_opcode(opcode: Opcode) -> list[MicroInstruction]:
    """Return execution microinstructions for an ISA opcode, excluding FETCH."""

    if opcode not in MPC_OF_OPCODE:
        raise KeyError(f"Opcode has no microcode: {opcode}")

    start = MPC_OF_OPCODE[opcode]

    starts = sorted(MPC_OF_OPCODE.values()) + [len(MICROPROGRAM)]
    end_candidates = [address for address in starts if address > start]
    end = min(end_candidates)

    return MICROPROGRAM[start:end]


def ticks_for_opcode(opcode: Opcode, *, include_fetch: bool = False) -> int:
    ticks = len(microinstructions_for_opcode(opcode))
    return ticks + (1 if include_fetch else 0)


def dump_microprogram() -> str:
    opcode_by_mpc = {mpc: opcode.name for opcode, mpc in MPC_OF_OPCODE.items()}
    label_by_mpc = {mpc: label for label, mpc in LABELS.items()}

    lines: list[str] = []

    for address, microinstruction in enumerate(MICROPROGRAM):
        marks: list[str] = []

        if address in label_by_mpc:
            marks.append(label_by_mpc[address])
        if address in opcode_by_mpc:
            marks.append(opcode_by_mpc[address])

        prefix = f"{address:03d}"
        if marks:
            prefix += " <" + ", ".join(marks) + ">"

        lines.append(f"{prefix}: {microinstruction}")

    return "\n".join(lines)


if __name__ == "__main__":
    print(dump_microprogram())
