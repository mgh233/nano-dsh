# Tool Registry Service Plugin.

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nano_dsh.contracts import (
    Disposer,
    RunFailure,
    ToolCall,
    ToolDefinition,
    ToolFailure,
    Trace,
)


class ToolsService:
    # Register and execute uniquely named Tools.

    def __init__(self, trace: Trace) -> None:
        self._trace = trace
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> Disposer:
        # Register one Tool and return its disposer.
        if definition.name in self._definitions:
            raise RunFailure(f"Tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

        def dispose() -> None:
            if self._definitions.get(definition.name) is definition:
                del self._definitions[definition.name]

        return dispose

    def definitions(self) -> tuple[ToolDefinition, ...]:
        # Return Tool definitions in registration order.
        return tuple(self._definitions.values())

    def execute(self, call: ToolCall, workspace: Path) -> str:
        # Parse and execute one Tool Call.
        definition = self._definitions.get(call.name)
        label = definition.name if definition is not None else "<unknown>"
        self._trace("tool", f"execute {label}")
        if definition is None:
            self._trace("tool", f"failed {label}")
            return f"Error: unknown Tool: {call.name}"
        try:
            arguments = json.loads(call.arguments)
        except json.JSONDecodeError as error:
            self._trace("tool", f"failed {label}")
            return f"Error: invalid JSON arguments: {error.msg}"
        try:
            result = definition.handler(arguments, workspace)
        except ToolFailure as error:
            self._trace("tool", f"failed {label}")
            return f"Error: {error}"
        self._trace("tool", f"complete {label}")
        return result


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    # Publish the Tool Registry Service.
    ctx.provide("tools", ToolsService(ctx.emit))
