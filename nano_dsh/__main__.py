# Headless nano-dsh command-line application.

import argparse
import sys
from pathlib import Path

from nano_dsh.boot import boot
from nano_dsh.contracts import CommandLineArgs


def _parse_args(argv: list[str] | None = None) -> CommandLineArgs:
    parser = argparse.ArgumentParser(prog="nano-dsh")
    parser.add_argument("task")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--api-key-file", default=".key")
    values = parser.parse_args(argv)
    workspace = Path(values.workspace).resolve()
    if not workspace.is_dir():
        parser.error(f"workspace is not a directory: {workspace}")
    return CommandLineArgs(
        values.task,
        workspace,
        Path(values.api_key_file).resolve(),
    )


def _trace(category: str, message: str) -> None:
    print(f"{category}: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    profile = Path(__file__).resolve().parents[1] / "profiles/headless.toml"
    context = boot(profile, {"cmdline_args": args}, _trace)
    context.dispose()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
