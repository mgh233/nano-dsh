# One-shot Bash Tool Plugin.

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nano_dsh.contracts import RunFailure, ToolDefinition, ToolFailure


TIMEOUT_SECONDS = 300
OUTPUT_LIMIT = 16_000


def _handle(arguments: object, workspace: Path) -> str:
    if not isinstance(arguments, dict):
        raise ToolFailure("bash arguments must be an object")
    if set(arguments) != {"command"}:
        raise ToolFailure("bash requires only the command argument")
    command = arguments["command"]
    if not isinstance(command, str):
        raise ToolFailure("command must be a string")
    if not workspace.is_dir():
        raise ToolFailure(f"Workspace is not a directory: {workspace}")

    environment = os.environ.copy()
    environment.pop("DEEPSEEK_API_KEY", None)
    try:
        completed = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=workspace,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ToolFailure(f"Bash command timed out after {TIMEOUT_SECONDS} seconds") from None
    except OSError as error:
        raise ToolFailure(f"Bash execution failed: {error}") from error

    output = completed.stdout
    if completed.returncode == 0:
        return output[:OUTPUT_LIMIT]
    marker = f"[exit code: {completed.returncode}]"
    suffix = ("" if not output or output.endswith("\n") else "\n") + marker
    return output[: OUTPUT_LIMIT - len(suffix)] + suffix


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    # Register the Bash Tool for the current Fiber.
    if not isinstance(config, Mapping) or config:
        raise RunFailure("bash Plugin config must be empty")
    tools = ctx.get("tools")
    definition = ToolDefinition(
        name="bash",
        description="Run one command in a fresh Bash process in the Workspace.",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "additionalProperties": False,
        },
        handler=_handle,
    )
    ctx.effect(lambda: tools.register(definition))
