from __future__ import annotations

from enum import StrEnum

from isa import Opcode

class MicroOp(StrEnum):
    PUSH_IR_OPERAND = "PUSH_IR_OPERAND"
    DROP = "DROP"
    DUP = "DUP"
    SWAP = "SWAP"

    LOAD_DIRECT = "LOAD_DIRECT"
    STORE_DIRECT = "STORE_DIRECT"
    LOAD_INDIRECT = "LOAD_INDIRECT"
    STORE_INDIRECT = "STORE_INDIRECT"

    POP_A = "POP_A"
    POP_B = "POP_B"
    PUSH_ALU = "PUSH_ALU"

    ALU_ADD = "ALU_ADD"
    ALU_SUB = "ALU_SUB"
    ALU_MUL = "ALU_MUL"
    ALU_DIV = "ALU_DIV"
    ALU_MOD = "ALU_MOD"
    ALU_EQ = "ALU_EQ"
    ALU_NE = "ALU_NE"
    ALU_LT = "ALU_LT"
    ALU_GT = "ALU_GT"
    ALU_LE = "ALU_LE"
    ALU_GE = "ALU_GE"

    JMP = "JMP"
    JZ = "JZ"
    JNZ = "JNZ"
    CALL = "CALL"
    RET = "RET"
    INC_PC = "INC_PC"

    PORT_IN = "PORT_IN"
    PORT_OUT = "PORT_OUT"

    INT = "INT"
    IRET = "IRET"
    EI = "EI"
    DI = "DI"

    HALT = "HALT"
    END_INSTRUCTION = "END_INSTRUCTION"


def seq(*ops: MicroOp) -> list[MicroOp]:
    return list(ops)


def normal(op: MicroOp) -> list[MicroOp]:
    return [op, MicroOp.INC_PC, MicroOp.END_INSTRUCTION]


def branch(op: MicroOp) -> list[MicroOp]:
    return [op, MicroOp.END_INSTRUCTION]


def bin_alu(op: MicroOp) -> list[MicroOp]:
    return [
        MicroOp.POP_A,
        MicroOp.POP_B,
        op,
        MicroOp.PUSH_ALU,
        MicroOp.INC_PC,
        MicroOp.END_INSTRUCTION,
    ]


MICROPROGRAM_MEMORY: dict[Opcode, list[MicroOp]] = {
    # system
    Opcode.HALT: seq(MicroOp.HALT, MicroOp.END_INSTRUCTION),

    # stack
    Opcode.PUSHI: normal(MicroOp.PUSH_IR_OPERAND),
    Opcode.DROP: normal(MicroOp.DROP),
    Opcode.DUP: normal(MicroOp.DUP),
    Opcode.SWAP: normal(MicroOp.SWAP),

    # data memory
    Opcode.LOAD: normal(MicroOp.LOAD_DIRECT),
    Opcode.STORE: normal(MicroOp.STORE_DIRECT),
    Opcode.LOADI: normal(MicroOp.LOAD_INDIRECT),
    Opcode.STOREI: normal(MicroOp.STORE_INDIRECT),

    # arithmetic
    Opcode.ADD: bin_alu(MicroOp.ALU_ADD),
    Opcode.SUB: bin_alu(MicroOp.ALU_SUB),
    Opcode.MUL: bin_alu(MicroOp.ALU_MUL),
    Opcode.DIV: bin_alu(MicroOp.ALU_DIV),
    Opcode.MOD: bin_alu(MicroOp.ALU_MOD),

    # comparison
    Opcode.EQ: bin_alu(MicroOp.ALU_EQ),
    Opcode.NE: bin_alu(MicroOp.ALU_NE),
    Opcode.LT: bin_alu(MicroOp.ALU_LT),
    Opcode.GT: bin_alu(MicroOp.ALU_GT),
    Opcode.LE: bin_alu(MicroOp.ALU_LE),
    Opcode.GE: bin_alu(MicroOp.ALU_GE),

    # control flow
    Opcode.JMP: branch(MicroOp.JMP),
    Opcode.JZ: branch(MicroOp.JZ),
    Opcode.JNZ: branch(MicroOp.JNZ),

    # procedures
    Opcode.CALL: branch(MicroOp.CALL),
    Opcode.RET: branch(MicroOp.RET),

    # interrupts
    Opcode.INT: branch(MicroOp.INT),
    Opcode.IRET: branch(MicroOp.IRET),
    Opcode.EI: branch(MicroOp.EI),
    Opcode.DI: branch(MicroOp.DI),

    # port-mapped I/O
    Opcode.IN: normal(MicroOp.PORT_IN),
    Opcode.OUT: normal(MicroOp.PORT_OUT),
}


def get_microprogram(opcode: Opcode) -> list[MicroOp]:
    try:
        return MICROPROGRAM_MEMORY[opcode]
    except KeyError as exc:
        raise ValueError(f"No microprogram for opcode: {opcode.name}") from exc


def validate_microprogram_memory() -> None:
    missing = [opcode.name for opcode in Opcode if opcode not in MICROPROGRAM_MEMORY]
    if missing:
        raise ValueError(f"Missing microprograms for opcodes: {missing}")


def microprogram_to_text(opcode: Opcode) -> str:
    microprogram = get_microprogram(opcode)
    lines = [f"{opcode.name}:"]

    for address, micro_op in enumerate(microprogram):
        lines.append(f"  {address:02d}: {micro_op.value}")

    return "\n".join(lines)


def all_microprograms_to_text() -> str:
    return "\n\n".join(microprogram_to_text(opcode) for opcode in Opcode)