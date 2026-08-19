"""In-memory Session Service Plugin."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nano_dsh.contracts import SessionEvent


class Session:
    """One append-only record of an Agent Run."""

    def __init__(self) -> None:
        self._events: list[SessionEvent] = []

    @property
    def events(self) -> tuple[SessionEvent, ...]:
        """Return an immutable snapshot of the current events."""
        return tuple(self._events)

    def append(self, event: SessionEvent) -> None:
        """Append one Session Event."""
        self._events.append(event)


class SessionsService:
    """Create independent in-memory Sessions."""

    def create(self) -> Session:
        """Create one empty Session."""
        return Session()


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    """Publish the Sessions Service."""
    ctx.provide("sessions", SessionsService())
