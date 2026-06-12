import json
import sys
from pathlib import Path

import pytest
import yaml

# Чтобы тесты из папки tests/ видели machine.py, translator.py, isa.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from srу.machine import simulation
from srу.translator import translate_source
from srу.isa import DATA_WORD_SIZE_BYTES, INSTRUCTION_SIZE_BYTES


GOLDEN_DIR = PROJECT_ROOT / "golden"
RUN_TICK_LIMIT = 100_000_000
MAX_LOG_TICK = 400
MAX_DISASM_ADDRESS = 400


def code_hex_text(instructions, max_address: int = MAX_DISASM_ADDRESS):
    lines: list[str] = []

    for index, instruction in enumerate(instructions):
        address = index * INSTRUCTION_SIZE_BYTES

        if address > max_address:
            break

        lines.append(instruction.disasm(address))

    return "\n".join(lines)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def data_words_text(data: list[int]) -> str:
    lines: list[str] = []

    word_count = (len(data) + DATA_WORD_SIZE_BYTES - 1) // DATA_WORD_SIZE_BYTES
    index_width = max(2, len(str(word_count)))

    for word_index, offset in enumerate(
        range(0, len(data), DATA_WORD_SIZE_BYTES),
        start=1,
    ):
        chunk = data[offset:offset + DATA_WORD_SIZE_BYTES]

        bytes_text = ", ".join(
            f"{int(byte):>3d}"
            for byte in chunk
        )

        lines.append(f"{word_index:0{index_width}d} - {bytes_text}")

    return "\n".join(lines)


def filter_disasm_by_max_address(text: str, max_address: int = MAX_DISASM_ADDRESS) -> str:
    lines: list[str] = []

    for line in str(text).splitlines():
        stripped = line.rstrip()

        if not stripped:
            continue

        address_text = stripped.split("-", 1)[0].strip()

        try:
            address = int(address_text)
        except ValueError:
            # Если вдруг строка не похожа на строку дизассемблера,
            # оставляем её как есть, чтобы тест честно показал расхождение.
            lines.append(stripped)
            continue

        if address <= max_address:
            lines.append(stripped)

    return "\n".join(lines)


def filter_log_by_max_tick(text: str, max_tick: int = MAX_LOG_TICK) -> str:
    lines: list[str] = []

    for line in str(text).splitlines():
        stripped = line.rstrip()

        if stripped.startswith("TICK="):
            tick_text = stripped.split("|", 1)[0].replace("TICK=", "").strip()

            try:
                tick = int(tick_text)
            except ValueError:
                lines.append(stripped)
                continue

            if tick > max_tick:
                break

        lines.append(stripped)

    return "\n".join(lines)


def assert_limited_text_equal(actual: str, expected: str) -> None:
    assert actual.rstrip() == str(expected).rstrip()

def stdout_text(result):
    text = (
        f"Ticks: {result.ticks}\n"
        f"Halt reason: {result.halt_reason}\n"
        f"{'=' * 106}\n"
        f"{result.output}"
    )

    if not text.endswith("\n"):
        text += "\n"

    return text


def load_golden_files():
    return sorted(GOLDEN_DIR.glob("*.yml"))

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
        tick_limit=RUN_TICK_LIMIT
    )

    actual_code_hex = code_hex_text(
        translation.instructions,
        max_address=MAX_DISASM_ADDRESS,
    )
    expected_code_hex = filter_disasm_by_max_address(
        golden["out_code_hex"],
        max_address=MAX_DISASM_ADDRESS,
    )

    assert_limited_text_equal(actual_code_hex, expected_code_hex)

    data_len = len(translation.data_memory)
    final_data_prefix = result.data_memory[:data_len]

    actual_data_dec = data_words_text(final_data_prefix)
    expected_data_dec = str(golden["out_data_dec"]).rstrip()

    assert actual_data_dec == expected_data_dec

    # stdout машины
    assert stdout_text(result) == golden["out_stdout"]

    actual_log = filter_log_by_max_tick(
        "\n".join(result.log),
        max_tick=MAX_LOG_TICK,
    )
    expected_log = filter_log_by_max_tick(
        golden["out_log"],
        max_tick=MAX_LOG_TICK,
    )

    assert_limited_text_equal(actual_log, expected_log)
