# Agents Service Plugin.

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nano_dsh.contracts import Agent, AgentFactory, Disposer, RunFailure


class AgentsService:
    # Own the single current AgentFactory.

    def __init__(self) -> None:
        self._factory: AgentFactory | None = None

    def set_factory(self, factory: AgentFactory) -> Disposer:
        # Register the current factory and return its disposer.
        if self._factory is not None:
            raise RunFailure("an AgentFactory is already registered")
        self._factory = factory

        def dispose() -> None:
            if self._factory is factory:
                self._factory = None

        return dispose

    def create(self, workspace: Path) -> Agent:
        # Create an Agent through the current factory.
        if self._factory is None:
            raise RunFailure("no AgentFactory is registered")
        return self._factory.create(workspace)


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    # Publish the Agents Service.
    ctx.provide("agents", AgentsService())
