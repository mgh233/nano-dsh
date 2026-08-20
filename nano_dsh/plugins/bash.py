# One-shot Bash Tool Plugin.

import os
import subprocess
from pathlib import Path
from typing import Any

from nano_dsh.contracts import ToolDefinition, ToolOutput


TIMEOUT_SECONDS = 300
OUTPUT_LIMIT = 16_000


def _handle(arguments: object, workspace: Path) -> ToolOutput:
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"command"}
        or not isinstance(arguments.get("command"), str)
    ):
        return ToolOutput("Error: bash requires a string command", failed=True)
    command = arguments["command"]

    environment = os.environ.copy()
    environment.pop("DEEPSEEK_API_KEY", None)
    completed = subprocess.run(
        ["/bin/bash", "-lc", command],
        cwd=workspace,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )

    output = completed.stdout
    if completed.returncode == 0:
        return ToolOutput(output[:OUTPUT_LIMIT])
    marker = f"[exit code: {completed.returncode}]"
    suffix = ("" if not output or output.endswith("\n") else "\n") + marker
    return ToolOutput(
        output[: OUTPUT_LIMIT - len(suffix)] + suffix,
        failed=True,
    )


def apply(ctx: Any, config: object) -> None:
    # Register the Bash Tool for the current Fiber.
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
