# Agents Service Plugin.

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from nano_dsh.contracts import Agent, AgentFactory, Disposer


class AgentsService:
    # Own the single current AgentFactory.

    def __init__(self) -> None:
        self._factory: AgentFactory | None = None

    def set_factory(self, factory: AgentFactory) -> Disposer:
        # Register the current factory and return its disposer.
        assert self._factory is None, "an AgentFactory is already registered"
        self._factory = factory

        def dispose() -> None:
            if self._factory is factory:
                self._factory = None

        return dispose

    def create(self, workspace: Path) -> Agent:
        # Create an Agent through the current factory.
        return cast(AgentFactory, self._factory).create(workspace)


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    # Publish the Agents Service.
    ctx.provide("agents", AgentsService())
