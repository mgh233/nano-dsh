# Assemble a Context from root Services and a declarative Profile.

from collections.abc import Callable, Mapping
from pathlib import Path

from .contracts import Trace
from .cordis import Context, FiberState
from .loader import Loader


def boot(
    profile_path: Path,
    root_services: Mapping[str, object],
    trace: Trace,
    context_factory: Callable[[Trace], Context] | None = None,
) -> Context:
    # Create, assemble, audit, and return an active Context.
    if context_factory is None:
        context_factory = Context
    context = context_factory(trace)
    for name, service in root_services.items():
        context.provide_root(name, service)
    Loader(context).load(Path(profile_path))
    _require_active(context)
    return context


def _require_active(context: Context) -> None:
    for fiber in context.fibers:
        missing = ", ".join(context.missing(fiber))
        assert fiber.state is FiberState.ACTIVE, (
            f"Plugin Fiber {fiber.id} did not activate; "
            f"state={fiber.state.name}; missing Services: {missing}"
        )
