"""AgentLoop AgentFactory Plugin."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nano_dsh.contracts import (
    Agent,
    AssistantEvent,
    Disposer,
    LLMProvider,
    RunFailure,
    ToolResultEvent,
    Trace,
    UserEvent,
)
from nano_dsh.plugins.agents import AgentsService
from nano_dsh.plugins.sessions import Session, SessionsService
from nano_dsh.plugins.tools import ToolsService


class AgentLoopFactory:
    """Create Agents backed by the active core Services."""

    def __init__(self, ctx: Any) -> None:
        self._agents: AgentsService = ctx.get("agents")
        self._sessions: SessionsService = ctx.get("sessions")
        self._llm: LLMProvider = ctx.get("llm")
        self._tools: ToolsService = ctx.get("tools")
        self._trace: Trace = ctx.emit

    def register(self) -> Disposer:
        """Register this factory through the Agents Service."""
        return self._agents.set_factory(self)

    def create(self, workspace: Path) -> Agent:
        """Create one Agent with one new Session."""
        return _Agent(
            self._sessions.create(),
            self._llm,
            self._tools,
            workspace,
            self._trace,
        )


class _Agent:
    def __init__(
        self,
        session: Session,
        llm: LLMProvider,
        tools: ToolsService,
        workspace: Path,
        trace: Trace,
    ) -> None:
        self._session = session
        self._llm = llm
        self._tools = tools
        self._workspace = workspace
        self._trace = trace

    def run(self, task: str) -> str:
        """Run Model Steps until the Provider returns final content."""
        self._session.append(UserEvent(task))
        self._trace("agent", "run started")
        model_step = 0
        while True:
            model_step += 1
            self._trace("model", f"step {model_step} started")
            output = self._llm.complete(
                self._session.events,
                self._tools.definitions(),
            )
            self._trace("model", f"step {model_step} completed")
            self._session.append(
                AssistantEvent(
                    content=output.content,
                    reasoning_content=output.reasoning_content,
                    tool_calls=output.tool_calls,
                )
            )
            if output.tool_calls:
                for call in output.tool_calls:
                    result = self._tools.execute(call, self._workspace)
                    self._session.append(
                        ToolResultEvent(
                            tool_call_id=call.id,
                            name=call.name,
                            content=result,
                        )
                    )
                continue
            if output.content is None or not output.content.strip():
                raise RunFailure(
                    "final assistant response must contain non-empty content"
                )
            self._trace("agent", "run completed")
            return output.content


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    """Register the AgentLoop factory as a Fiber-owned Effect."""
    factory = AgentLoopFactory(ctx)
    ctx.effect(factory.register)
