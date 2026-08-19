"""Assemble a Context from root Services and a declarative Profile."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from .contracts import RunFailure, Trace
from .loader import Loader


def boot(
    profile_path: Path,
    root_services: Mapping[str, object],
    trace: Trace,
    context_factory: Callable[[Trace], object] | None = None,
) -> object:
    """Create, assemble, audit, and return an active Context."""
    if context_factory is None:
        from .cordis import Context

        context_factory = Context
    context = context_factory(trace)
    try:
        for name, service in root_services.items():
            context.provide_root(name, service)  # type: ignore[attr-defined]
        Loader(context).load(Path(profile_path))
        _require_active(context)
        return context
    except Exception:
        context.dispose()  # type: ignore[attr-defined]
        raise


def _require_active(context: object) -> None:
    for fiber in context.fibers:  # type: ignore[attr-defined]
        state = _state_name(fiber.state)
        if state == "ACTIVE":
            continue
        fiber_id = getattr(fiber, "id", None)
        if fiber_id is None:
            fiber_id = getattr(getattr(fiber, "spec", None), "id", "unknown")
        if state == "PENDING":
            missing = ", ".join(context.missing(fiber))  # type: ignore[attr-defined]
            raise RunFailure(f"Plugin Fiber {fiber_id} is PENDING; missing Services: {missing}")
        raise RunFailure(f"Plugin Fiber {fiber_id} is {state}; expected ACTIVE")


def _state_name(state: object) -> str:
    return getattr(state, "name", state)
