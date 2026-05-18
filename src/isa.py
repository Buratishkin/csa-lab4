from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


INSTRUCTION_SIZE_BYTES = 4

OPCODE_BITS = 8
OPERAND_BITS = 24

OPCODE_MASK = 0xFF
OPERAND_MASK = 0xFFFFFF

MAX_U24 = (1 << 24) - 1
MIN_I24 = -(1 << 23)
MAX_I24 = (1 << 23) - 1


class Opcode(IntEnum):
    # system
    HALT = 0x00

    # stack
    PUSHI = 0x01
    DROP = 0x02
    DUP = 0x03
    SWAP = 0x04

    # data memory
    LOAD = 0x10
    STORE = 0x11
    LOADI = 0x12
    STOREI = 0x13

    # arithmetic
    ADD = 0x20
    SUB = 0x21
    MUL = 0x22
    DIV = 0x23
    MOD = 0x24

    # comparison
    EQ = 0x30
    NE = 0x31
    LT = 0x32
    GT = 0x33
    LE = 0x34
    GE = 0x35

    # control flow
    JMP = 0x40
    JZ = 0x41
    JNZ = 0x42

    # procedures
    CALL = 0x50
    RET = 0x51

    # port-mapped I/O
    IN = 0x60
    OUT = 0x61

    # interrupts
    # INT operand is an interrupt number for software interrupt.
    # Hardware interrupts use the interrupt vector stored in data memory.
    INT = 0x70
    IRET = 0x71
    EI = 0x72
    DI = 0x73


NO_OPERAND_OPCODES: set[Opcode] = {
    Opcode.HALT,
    Opcode.DROP,
    Opcode.DUP,
    Opcode.SWAP,
    Opcode.LOADI,
    Opcode.STOREI,
    Opcode.ADD,
    Opcode.SUB,
    Opcode.MUL,
    Opcode.DIV,
    Opcode.MOD,
    Opcode.EQ,
    Opcode.NE,
    Opcode.LT,
    Opcode.GT,
    Opcode.LE,
    Opcode.GE,
    Opcode.RET,
    Opcode.IRET,
    Opcode.EI,
    Opcode.DI,
}


SIGNED_OPERAND_OPCODES: set[Opcode] = {
    Opcode.PUSHI,
}


UNSIGNED_OPERAND_OPCODES: set[Opcode] = {
    Opcode.LOAD,
    Opcode.STORE,
    Opcode.JMP,
    Opcode.JZ,
    Opcode.JNZ,
    Opcode.CALL,
    Opcode.IN,
    Opcode.OUT,
    Opcode.INT,
}


def sign_extend_24(value: int) -> int:
    value &= OPERAND_MASK

    if value & (1 << 23):
        return value - (1 << 24)

    return value


def encode_signed_24(value: int) -> int:
    if not MIN_I24 <= value <= MAX_I24:
        raise ValueError(
            f"Signed operand does not fit into 24 bits: {value}. "
            f"Allowed range: {MIN_I24}..{MAX_I24}"
        )

    return value & OPERAND_MASK


def encode_unsigned_24(value: int) -> int:
    if not 0 <= value <= MAX_U24:
        raise ValueError(
            f"Unsigned operand does not fit into 24 bits: {value}. "
            f"Allowed range: 0..{MAX_U24}"
        )

    return value


@dataclass(frozen=True)
class Instruction:
    opcode: Opcode
    operand: int = 0

    def __post_init__(self) -> None:
        validate_operand(self.opcode, self.operand)

    @property
    def raw_operand(self) -> int:
        if self.opcode in SIGNED_OPERAND_OPCODES:
            return encode_signed_24(self.operand)

        return encode_unsigned_24(self.operand)

    @property
    def word(self) -> int:
        return encode_instruction(self.opcode, self.operand)

    def to_bytes(self) -> bytes:
        return self.word.to_bytes(
            INSTRUCTION_SIZE_BYTES,
            byteorder="big",
            signed=False,
        )

    def disasm(self, address: int | None = None) -> str:
        prefix = "" if address is None else f"{address:04d} - "

        if self.opcode in NO_OPERAND_OPCODES:
            return f"{prefix}{self.word:08X} - {self.opcode.name}"

        return f"{prefix}{self.word:08X} - {self.opcode.name} {self.operand}"


def validate_operand(opcode: Opcode, operand: int) -> None:
    if opcode in NO_OPERAND_OPCODES:
        if operand != 0:
            raise ValueError(f"{opcode.name} must not have operand: {operand}")
        return

    if opcode in SIGNED_OPERAND_OPCODES:
        encode_signed_24(operand)
        return

    if opcode in UNSIGNED_OPERAND_OPCODES:
        encode_unsigned_24(operand)
        return

    raise ValueError(f"Unknown operand type for opcode: {opcode}")


def encode_instruction(opcode: Opcode, operand: int = 0) -> int:
    validate_operand(opcode, operand)

    if opcode in SIGNED_OPERAND_OPCODES:
        encoded_operand = encode_signed_24(operand)
    else:
        encoded_operand = encode_unsigned_24(operand)

    return (int(opcode) << OPERAND_BITS) | encoded_operand


def decode_instruction(word: int) -> Instruction:
    if not 0 <= word <= 0xFFFFFFFF:
        raise ValueError(f"Instruction word must be uint32: {word}")

    opcode_raw = (word >> OPERAND_BITS) & OPCODE_MASK
    operand_raw = word & OPERAND_MASK

    try:
        opcode = Opcode(opcode_raw)
    except ValueError as exc:
        raise ValueError(f"Unknown opcode: 0x{opcode_raw:02X}") from exc

    if opcode in SIGNED_OPERAND_OPCODES:
        operand = sign_extend_24(operand_raw)
    else:
        operand = operand_raw

    return Instruction(opcode=opcode, operand=operand)


def instruction_from_bytes(data: bytes) -> Instruction:
    if len(data) != INSTRUCTION_SIZE_BYTES:
        raise ValueError(
            f"Instruction must be exactly {INSTRUCTION_SIZE_BYTES} bytes, "
            f"got {len(data)}"
        )

    word = int.from_bytes(data, byteorder="big", signed=False)
    return decode_instruction(word)


def instructions_to_bytes(instructions: list[Instruction]) -> bytes:
    return b"".join(instruction.to_bytes() for instruction in instructions)


def instructions_from_bytes(data: bytes) -> list[Instruction]:
    if len(data) % INSTRUCTION_SIZE_BYTES != 0:
        raise ValueError(
            f"Binary size must be divisible by {INSTRUCTION_SIZE_BYTES}, "
            f"got {len(data)}"
        )

    instructions: list[Instruction] = []

    for offset in range(0, len(data), INSTRUCTION_SIZE_BYTES):
        chunk = data[offset : offset + INSTRUCTION_SIZE_BYTES]
        instructions.append(instruction_from_bytes(chunk))

    return instructions


def write_code(filename: str | Path, instructions: list[Instruction]) -> None:
    Path(filename).write_bytes(instructions_to_bytes(instructions))


def read_code(filename: str | Path) -> list[Instruction]:
    return instructions_from_bytes(Path(filename).read_bytes())


def write_disasm(filename: str | Path, instructions: list[Instruction]) -> None:
    lines = [
        instruction.disasm(address)
        for address, instruction in enumerate(instructions)
    ]

    Path(filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def instructions_to_words(instructions: list[Instruction]) -> list[int]:
    return [instruction.word for instruction in instructions]


def words_to_instructions(words: list[int]) -> list[Instruction]:
    return [decode_instruction(word) for word in words]