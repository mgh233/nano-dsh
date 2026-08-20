# Headless nano-dsh command-line application.

import argparse
import sys
from pathlib import Path

from nano_dsh.boot import boot
from nano_dsh.contracts import CommandLineArgs, Trace


TRANSCRIPT_CATEGORIES = {
    "system",
    "user",
    "reasoning",
    "assistant",
    "tool_call",
    "tool_result",
}


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


def _make_trace() -> Trace:
    started = False

    def trace(category: str, message: str) -> None:
        nonlocal started
        if not started:
            started = category == "system"
            if not started:
                return
        if category in TRANSCRIPT_CATEGORIES:
            if category != "system":
                print(file=sys.stderr)
            print(
                f"=== {category.upper().replace('_', ' ')} ===",
                file=sys.stderr,
            )
            print(message, file=sys.stderr)
            return
        print(f"{category}: {message}", file=sys.stderr)

    return trace


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    profile = Path(__file__).resolve().parents[1] / "profiles/headless.toml"
    context = boot(profile, {"cmdline_args": args}, _make_trace())
    context.dispose()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
