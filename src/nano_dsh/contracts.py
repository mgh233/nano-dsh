"""Shared contracts used by independently developed nano-dsh modules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeAlias


class RunFailure(RuntimeError):
    """An unrecoverable failure that ends an Agent Run."""


class ToolFailure(ValueError):
    """An expected Tool failure that the Agent can inspect."""


@dataclass(frozen=True)
class PluginSpec:
    """One declarative Plugin entry loaded from a Bundle."""

    id: str
    module: str
    inject: tuple[str, ...] = ()
    config: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    """One model request to invoke a Tool."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class UserEvent:
    """A user message appended to a Session."""

    content: str


@dataclass(frozen=True)
class AssistantEvent:
    """An assistant response appended before Tool execution."""

    content: str | None
    reasoning_content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ToolResultEvent:
    """The model-visible result of one Tool Execution."""

    tool_call_id: str
    name: str
    content: str


SessionEvent: TypeAlias = UserEvent | AssistantEvent | ToolResultEvent


@dataclass(frozen=True)
class AssistantOutput:
    """One normalized non-streaming Provider response."""

    content: str | None
    reasoning_content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


ToolHandler: TypeAlias = Callable[[object, Path], str]


@dataclass(frozen=True)
class ToolDefinition:
    """A model-facing Tool schema and its local handler."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler = field(repr=False, compare=False)


class LLMProvider(Protocol):
    """Provider contract consumed by AgentLoop."""

    def complete(
        self,
        events: Sequence[SessionEvent],
        tools: Sequence[ToolDefinition],
    ) -> AssistantOutput:
        """Produce the next assistant output."""


class Agent(Protocol):
    """Runtime contract used by a Driver."""

    def run(self, task: str) -> str:
        """Run one task until the final assistant response."""


class AgentFactory(Protocol):
    """Factory contract registered through the Agents Service."""

    def create(self, workspace: Path) -> Agent:
        """Create an Agent rooted at the selected Workspace."""


@dataclass(frozen=True)
class CommandLineArgs:
    """Validated values provided by the CLI before Plugin loading."""

    task: str
    workspace: Path
    api_key_file: Path


@dataclass(frozen=True)
class HeadlessStartup:
    """CLI-derived inputs that make a headless Agent Run ready."""

    task: str
    workspace: Path


Disposer: TypeAlias = Callable[[], None]
Trace: TypeAlias = Callable[[str, str], None]
