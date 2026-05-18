import json
import sys
from pathlib import Path

import pytest
import yaml

# Чтобы тесты из папки tests/ видели machine.py, translator.py, isa.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.machine import simulation
from src.translator import translate_source
from src.isa import instructions_to_bytes


GOLDEN_DIR = PROJECT_ROOT / "golden"
MAX_COMPARE_LINES = 101


def code_hex_text(instructions):
    return "\n".join(
        instruction.disasm(address)
        for address, instruction in enumerate(instructions)
    )


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def first_lines(text: str, limit: int = MAX_COMPARE_LINES, strip_right: bool = False) -> str:
    lines = text.splitlines()

    if strip_right:
        lines = [line.rstrip() for line in lines]

    return "\n".join(lines[:limit])


def stdout_text(result):
    text = (
        f"Ticks: {result.ticks}\n"
        f"Halt reason: {result.halt_reason}\n"
        f"Interrupts handled: {result.interrupts_handled}\n"
        f"{'=' * 106}\n"
        f"{result.output}"
    )

    if not text.endswith("\n"):
        text += "\n"

    return text


def load_golden_files():
    return sorted(GOLDEN_DIR.glob("*.yml"))

def parse_interrupt_ticks(value):
    if value is None:
        return []

    value = str(value).strip()

    if value == "":
        return []

    return [
        int(item.strip())
        for item in value.split(",")
        if item.strip()
    ]


def parse_interrupt_symbol(value):
    value = str(value)

    if len(value) != 1:
        raise AssertionError("in_interrupt_symbol must contain exactly one character")

    return ord(value)

@pytest.mark.parametrize("golden_path", load_golden_files())
def test_translator_and_machine(golden_path):
    golden = yaml.safe_load(golden_path.read_text(encoding="utf-8"))

    source = golden["in_source"]
    stdin = golden.get("in_stdin", "")

    translation = translate_source(source)

    result = simulation(
        instructions=translation.instructions,
        input_text=stdin,
        initial_data_memory=translation.data_memory,
        tick_limit=100000000,
        interrupt_ticks=parse_interrupt_ticks(golden.get("in_interrupt_ticks", "")),
        interrupt_device_symbol=parse_interrupt_symbol(golden.get("in_interrupt_symbol", "!")),
    )

    # Память команд в человекочитаемом виде.
    # Проверяем только первые 101 строку.
    actual_code_hex = code_hex_text(translation.instructions)
    expected_code_hex = golden["out_code_hex"]

    assert first_lines(actual_code_hex) == first_lines(expected_code_hex)

    # Память команд в бинарном виде, если есть поле out_code.
    # ВАЖНО: это всё ещё проверяет весь бинарник целиком.
    if "out_code" in golden:
        assert instructions_to_bytes(translation.instructions) == golden["out_code"]

    # Финальная память данных.
    # Проверяем только первые n ячеек, где n = размер .data.json,
    # то есть размер translation.data_memory.
    data_len = len(translation.data_memory)
    final_data_prefix = result.data_memory[:data_len]

    assert json_text(final_data_prefix) == golden["out_data_dec"]

    # stdout машины
    assert stdout_text(result) == golden["out_stdout"]

    # log машины.
    # Проверяем только первые 100 строк.
    # strip_right=True нужен, чтобы не падать из-за невидимых пробелов в конце строк.
    actual_log = "\n".join(result.log)
    expected_log = golden["out_log"]

    assert first_lines(actual_log, strip_right=True) == first_lines(expected_log, strip_right=True)