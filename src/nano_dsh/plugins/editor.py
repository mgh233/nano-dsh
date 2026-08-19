"""Workspace-confined text Editor Tool Plugin."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nano_dsh.contracts import RunFailure, ToolDefinition, ToolFailure


OUTPUT_LIMIT = 16_000
COMMANDS = ("view", "create", "str_replace", "insert")
FIELDS = {
    "command",
    "path",
    "file_text",
    "insert_line",
    "new_str",
    "old_str",
    "view_range",
}


def _arguments(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ToolFailure("editor arguments must be an object")
    extra = set(value) - FIELDS
    if extra:
        raise ToolFailure(f"unknown editor argument: {sorted(extra)[0]}")
    command = value.get("command")
    path = value.get("path")
    if command not in COMMANDS:
        raise ToolFailure(f"invalid editor command: {command}")
    if not isinstance(path, str):
        raise ToolFailure("path must be a string")
    return value


def _resolve(path: str, workspace: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ToolFailure("path must be absolute")
    try:
        root = workspace.resolve(strict=True)
        target = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        raise ToolFailure("cannot resolve path") from None
    if not root.is_dir():
        raise ToolFailure(f"Workspace is not a directory: {workspace}")
    try:
        target.relative_to(root)
    except ValueError:
        raise ToolFailure(f"path is outside the Workspace: {path}") from None
    if candidate.is_symlink():
        raise ToolFailure(f"path must not be a symbolic link: {path}")
    return target


def _read(target: Path) -> str:
    if not target.exists():
        raise ToolFailure(f"path does not exist: {target}")
    if not target.is_file():
        raise ToolFailure(f"path is not a file: {target}")
    try:
        return target.read_text()
    except (OSError, UnicodeError) as error:
        raise ToolFailure(f"cannot read file: {error}") from error


def _write(target: Path, text: str) -> None:
    try:
        target.write_text(text)
    except (OSError, UnicodeError) as error:
        raise ToolFailure(f"cannot write file: {error}") from error


def _range(value: object, line_count: int) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(item) is not int for item in value)
    ):
        raise ToolFailure("view_range must contain two integers")
    start, end = value
    if start < 1 or end == 0 or end < -1 or (end != -1 and end < start):
        raise ToolFailure(f"invalid view_range: {value}")
    last = line_count if end == -1 else end
    if start > line_count or last > line_count:
        raise ToolFailure(f"view_range exceeds {line_count} lines")
    return start, last


def _view(target: Path, arguments: dict[str, object]) -> str:
    if target.is_dir():
        if "view_range" in arguments:
            raise ToolFailure("view_range is valid only for files")
        try:
            names = [
                child.name + ("/" if child.is_dir() else "")
                for child in sorted(target.iterdir(), key=lambda item: item.name)
            ]
        except OSError as error:
            raise ToolFailure(f"cannot list directory: {error}") from error
        return "\n".join(names)[:OUTPUT_LIMIT]
    text = _read(target)
    lines = text.splitlines()
    if not lines:
        if "view_range" in arguments:
            raise ToolFailure("cannot select a range from an empty file")
        return ""
    start, end = (1, len(lines))
    if "view_range" in arguments:
        start, end = _range(arguments["view_range"], len(lines))
    result = "\n".join(
        f"{number}\t{lines[number - 1]}"
        for number in range(start, end + 1)
    )
    return result[:OUTPUT_LIMIT]


def _create(target: Path, arguments: dict[str, object]) -> str:
    text = arguments.get("file_text")
    if not isinstance(text, str):
        raise ToolFailure("create requires string file_text")
    if target.exists() or target.is_symlink():
        raise ToolFailure(f"path already exists: {target}")
    if not target.parent.is_dir():
        raise ToolFailure(f"parent directory does not exist: {target.parent}")
    _write(target, text)
    return f"Created {target}"[:OUTPUT_LIMIT]


def _replace(target: Path, arguments: dict[str, object]) -> str:
    old = arguments.get("old_str")
    new = arguments.get("new_str")
    if not isinstance(old, str) or not old:
        raise ToolFailure("str_replace requires non-empty string old_str")
    if not isinstance(new, str):
        raise ToolFailure("str_replace requires string new_str")
    text = _read(target)
    matches = text.count(old)
    if matches != 1:
        raise ToolFailure(f"old_str must match exactly once; found {matches}")
    _write(target, text.replace(old, new, 1))
    return f"Replaced text in {target}"[:OUTPUT_LIMIT]


def _insert(target: Path, arguments: dict[str, object]) -> str:
    line = arguments.get("insert_line")
    new = arguments.get("new_str")
    if type(line) is not int:
        raise ToolFailure("insert requires integer insert_line")
    if not isinstance(new, str) or not new:
        raise ToolFailure("insert requires non-empty string new_str")
    text = _read(target)
    lines = text.splitlines(keepends=True)
    if line < 0 or line > len(lines):
        raise ToolFailure(f"insert_line must be between 0 and {len(lines)}")
    before = "".join(lines[:line])
    after = "".join(lines[line:])
    if before and not before.endswith(("\n", "\r")):
        before += "\n"
    if after and not new.endswith(("\n", "\r")):
        new += "\n"
    _write(target, before + new + after)
    return f"Inserted text after line {line} in {target}"[:OUTPUT_LIMIT]


def _handle(value: object, workspace: Path) -> str:
    arguments = _arguments(value)
    target = _resolve(arguments["path"], workspace)
    command = arguments["command"]
    if command == "view":
        return _view(target, arguments)
    if command == "create":
        return _create(target, arguments)
    if command == "str_replace":
        return _replace(target, arguments)
    return _insert(target, arguments)


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    """Register the Editor Tool for the current Fiber."""
    if not isinstance(config, Mapping) or config:
        raise RunFailure("str_replace_editor Plugin config must be empty")
    tools = ctx.get("tools")
    definition = ToolDefinition(
        name="str_replace_editor",
        description="View, create, replace, or insert text in the Workspace.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "enum": list(COMMANDS)},
                "path": {"type": "string"},
                "file_text": {"type": "string"},
                "insert_line": {"type": "integer"},
                "new_str": {"type": "string"},
                "old_str": {"type": "string"},
                "view_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["command", "path"],
            "additionalProperties": False,
        },
        handler=_handle,
    )
    ctx.effect(lambda: tools.register(definition))
