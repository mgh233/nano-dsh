# Workspace-confined text Editor Tool Plugin.

from pathlib import Path
from typing import Any

from nano_dsh.contracts import ToolDefinition, ToolOutput


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


def _failure(content: str) -> ToolOutput:
    return ToolOutput(f"Error: {content}", failed=True)


def _range(value: object, line_count: int) -> tuple[int, int] | None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(type(item) is int for item in value)
    ):
        return None
    start, end = value
    if start < 1 or end == 0 or end < -1 or (end != -1 and end < start):
        return None
    last = line_count if end == -1 else end
    if start > line_count or last > line_count:
        return None
    return start, last


def _view(target: Path, arguments: dict[str, object]) -> ToolOutput:
    if target.is_dir():
        if "view_range" in arguments:
            return _failure("view_range is valid only for files")
        names = [
            child.name + ("/" if child.is_dir() else "")
            for child in sorted(target.iterdir(), key=lambda child: child.name)
        ]
        return ToolOutput("\n".join(names)[:OUTPUT_LIMIT])
    text = target.read_text()
    lines = text.splitlines()
    if not lines:
        if "view_range" in arguments:
            return _failure("cannot select a range from an empty file")
        return ToolOutput("")
    start, end = 1, len(lines)
    if "view_range" in arguments:
        selected = _range(arguments["view_range"], len(lines))
        if selected is None:
            return _failure("invalid view_range")
        start, end = selected
    return ToolOutput("\n".join(
        f"{number}\t{lines[number - 1]}" for number in range(start, end + 1)
    )[:OUTPUT_LIMIT])


def _create(target: Path, arguments: dict[str, object]) -> ToolOutput:
    text = arguments.get("file_text")
    if not isinstance(text, str):
        return _failure("create requires string file_text")
    if target.exists():
        return _failure(f"path already exists: {target}")
    target.write_text(text)
    return ToolOutput(f"Created {target}"[:OUTPUT_LIMIT])


def _replace(target: Path, arguments: dict[str, object]) -> ToolOutput:
    old = arguments.get("old_str")
    new = arguments.get("new_str")
    if not isinstance(old, str) or not old:
        return _failure("str_replace requires non-empty string old_str")
    if not isinstance(new, str):
        return _failure("str_replace requires string new_str")
    text = target.read_text()
    matches = text.count(old)
    if matches != 1:
        return _failure(f"old_str must match exactly once; found {matches}")
    target.write_text(text.replace(old, new, 1))
    return ToolOutput(f"Replaced text in {target}"[:OUTPUT_LIMIT])


def _insert(target: Path, arguments: dict[str, object]) -> ToolOutput:
    line = arguments.get("insert_line")
    new = arguments.get("new_str")
    if type(line) is not int:
        return _failure("insert requires integer insert_line")
    if not isinstance(new, str) or not new:
        return _failure("insert requires non-empty string new_str")
    text = target.read_text()
    lines = text.splitlines(keepends=True)
    if line < 0 or line > len(lines):
        return _failure(f"insert_line must be between 0 and {len(lines)}")
    if line and not lines[line - 1].endswith(("\n", "\r")):
        lines[line - 1] += "\n"
    if line < len(lines) and not new.endswith(("\n", "\r")):
        new += "\n"
    lines.insert(line, new)
    target.write_text("".join(lines))
    return ToolOutput(f"Inserted text after line {line} in {target}"[:OUTPUT_LIMIT])


_HANDLERS = {
    "view": _view,
    "create": _create,
    "str_replace": _replace,
    "insert": _insert,
}


def _handle(value: object, workspace: Path) -> ToolOutput:
    if not isinstance(value, dict) or set(value) - FIELDS:
        return _failure("invalid editor arguments")
    command = value.get("command")
    path = value.get("path")
    if command not in COMMANDS or not isinstance(path, str) or "\0" in path:
        return _failure("invalid editor arguments")
    candidate = Path(path)
    if not candidate.is_absolute():
        return _failure("path must be absolute")
    target = candidate.resolve(strict=False)
    if not target.is_relative_to(workspace.resolve()):
        return _failure(f"path is outside the Workspace: {path}")
    return _HANDLERS[command](target, value)


def apply(ctx: Any, config: object) -> None:
    # Register the Editor Tool for the current Fiber.
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
