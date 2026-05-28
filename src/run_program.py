from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str]) -> None:
    print("$ " + " ".join(command))
    completed = subprocess.run(command, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile a .lisp program with translator.py and run it with machine.py."
    )
    parser.add_argument("source", help="Path to source .lisp file, for example examples/prob1.lisp")
    parser.add_argument("--input", default=None, help="Optional input stream file")
    parser.add_argument("--out-dir", default="build", help="Directory for generated files")
    parser.add_argument("--tick-limit", type=int, default=100_000_000, help="Machine tick limit")
    parser.add_argument("--data-memory-size", type=int, default=None, help="Optional data memory size in bytes")
    parser.add_argument("--translator", default="translator.py", help="Path to translator.py")
    parser.add_argument("--machine", default="machine.py", help="Path to machine.py")
    parser.add_argument(
        "--interrupt-ticks",
        default="",
        help="Comma-separated hardware interrupt schedule, for example: 40 or 40,120",
    )
    parser.add_argument(
        "--interrupt-symbol",
        default="!",
        help="One character placed into data_memory[0x04] when interrupt fires",
    )


    args = parser.parse_args()

    source = Path(args.source)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = source.stem
    bin_file = out_dir / f"{stem}.bin"
    data_file = out_dir / f"{stem}.data.json"
    disasm_file = out_dir / f"{stem}.disasm"
    vars_file = out_dir / f"{stem}.vars"
    out_file = out_dir / f"{stem}.out"
    log_file = out_dir / f"{stem}.log"
    data_out_file = out_dir / f"{stem}.data.out.json"

    python = sys.executable

    translate_cmd = [
        python,
        args.translator,
        str(source),
        str(bin_file),
        "--data",
        str(data_file),
        "--disasm",
        str(disasm_file),
        "--vars",
        str(vars_file),
    ]
    run_command(translate_cmd)

    machine_cmd = [
        python,
        args.machine,
        str(bin_file),
        "--data",
        str(data_file),
        "--output",
        str(out_file),
        "--log",
        str(log_file),
        "--tick-limit",
        str(args.tick_limit),
        "--data-output",
        str(data_out_file),
    ]

    if args.interrupt_ticks:
        machine_cmd.extend(["--interrupt-ticks", args.interrupt_ticks])

    if args.interrupt_symbol:
        machine_cmd.extend(["--interrupt-symbol", args.interrupt_symbol])

    if args.input is not None:
        machine_cmd.extend(["--input", args.input])

    if args.data_memory_size is not None:
        machine_cmd.extend(["--data-memory-size", str(args.data_memory_size)])

    run_command(machine_cmd)

    print("\nGenerated files:")
    for path in [
        bin_file,
        data_file,
        disasm_file,
        vars_file,
        out_file,
        log_file,
        data_out_file,
    ]:
        print(f"  {path}")

    if out_file.exists():
        print("\nProgram output:")
        print(out_file.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()