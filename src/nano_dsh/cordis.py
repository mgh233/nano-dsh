"""A minimal Service-driven Plugin lifecycle runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from nano_dsh.contracts import Disposer, PluginSpec, RunFailure, Trace


class FiberState(Enum):
    """The lifecycle state of one Plugin Fiber."""

    PENDING = auto()
    LOADING = auto()
    ACTIVE = auto()
    UNLOADING = auto()
    FAILED = auto()
    DISPOSED = auto()


@dataclass
class Effect:
    """One disposer owned by a Fiber."""

    dispose: Disposer


PluginApply = Callable[["Context"], None]


@dataclass
class Fiber:
    """One Plugin instance and the Effects created by its activation."""

    id: str
    spec: PluginSpec
    apply: PluginApply = field(repr=False)
    state: FiberState = FiberState.PENDING
    effects: list[Effect] = field(default_factory=list, repr=False)


class Context:
    """Store Services and activate Fibers when their requirements are ready."""

    def __init__(self, trace: Trace | None = None) -> None:
        self.fibers: list[Fiber] = []
        self._trace = trace
        self._services: dict[str, object] = {}
        self._providers: dict[str, Fiber | None] = {}
        self._current: Fiber | None = None
        self._disposing = False

    def provide_root(self, name: str, value: object) -> None:
        """Publish a Service that is owned by the Context."""

        self._register_service(name, value, None)
        self._stabilize()

    def add_fiber(self, spec: PluginSpec, apply: PluginApply) -> Fiber:
        """Create a Fiber and activate every newly ready Fiber."""

        if any(fiber.id == spec.id for fiber in self.fibers):
            raise RunFailure(f"duplicate Fiber id: {spec.id}")
        fiber = Fiber(spec.id, spec, apply)
        self.fibers.append(fiber)
        self.emit("fiber", f"{fiber.id}: PENDING")
        self._stabilize()
        return fiber

    def get(self, name: str) -> object:
        """Return one currently available Service."""

        if not self._service_is_available(name):
            raise KeyError(f"Service is unavailable: {name}")
        return self._services[name]

    def provide(self, name: str, value: object) -> None:
        """Publish a Service owned by the loading Fiber."""

        owner = self._loading_fiber("provide a Service")
        self._register_service(name, value, owner)
        owner.effects.append(
            Effect(lambda: self._remove_service(name, owner))
        )

    def effect(self, setup: Callable[[], Disposer | None]) -> None:
        """Run setup and bind its optional disposer to the loading Fiber."""

        owner = self._loading_fiber("create an Effect")
        disposer = setup()
        if disposer is None:
            return
        if not callable(disposer):
            raise TypeError("Effect setup must return a disposer or None")
        owner.effects.append(Effect(disposer))

    def dispose_fiber(self, fiber: Fiber) -> None:
        """Permanently dispose one Fiber."""

        if not any(item is fiber for item in self.fibers):
            raise ValueError("Fiber does not belong to this Context")
        if fiber.state is FiberState.DISPOSED:
            return
        if fiber.state in (FiberState.LOADING, FiberState.UNLOADING):
            raise RunFailure(f"cannot dispose Fiber while {fiber.state.name}")
        if fiber.state is FiberState.ACTIVE:
            self._unload(fiber, FiberState.DISPOSED)
        else:
            self._cleanup(fiber)
            self._transition(fiber, FiberState.DISPOSED)
        if not self._disposing:
            self._stabilize()

    def dispose(self) -> None:
        """Dispose all Fibers in reverse creation order."""

        first_error: Exception | None = None
        self._disposing = True
        try:
            for fiber in reversed(self.fibers):
                try:
                    self.dispose_fiber(fiber)
                except Exception as error:
                    if first_error is None:
                        first_error = error
        finally:
            self._services.clear()
            self._providers.clear()
            self._disposing = False
        if first_error is not None:
            raise first_error

    def missing(self, fiber: Fiber) -> tuple[str, ...]:
        """Return the required Service names that are not available."""

        return tuple(
            name for name in fiber.spec.inject
            if not self._service_is_available(name)
        )

    def emit(self, category: str, message: str) -> None:
        """Send one concise teaching trace event."""

        if self._trace is not None:
            self._trace(category, message)

    def _stabilize(self) -> None:
        progressed = True
        while progressed:
            progressed = False
            for fiber in list(self.fibers):
                if fiber.state is FiberState.PENDING and not self.missing(fiber):
                    self._activate(fiber)
                    progressed = True

    def _activate(self, fiber: Fiber) -> None:
        self._transition(fiber, FiberState.LOADING)
        previous = self._current
        self._current = fiber
        try:
            fiber.apply(self)
        except Exception as error:
            try:
                self._cleanup(fiber)
            except Exception as cleanup_error:
                error.add_note(f"Effect cleanup failed: {cleanup_error}")
            self._transition(fiber, FiberState.FAILED)
            raise
        finally:
            self._current = previous
        self._transition(fiber, FiberState.ACTIVE)

    def _unload(self, fiber: Fiber, target: FiberState) -> None:
        errors: list[Exception] = []
        for name, owner in tuple(self._providers.items()):
            if owner is fiber:
                self._suspend_consumers(name, errors)
        self._transition(fiber, FiberState.UNLOADING)
        try:
            self._cleanup(fiber)
        except Exception as error:
            errors.append(error)
        finally:
            self._transition(fiber, target)
        if errors:
            raise errors[0]

    def _cleanup(self, fiber: Fiber) -> None:
        first_error: Exception | None = None
        while fiber.effects:
            try:
                fiber.effects.pop().dispose()
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def _register_service(
        self,
        name: str,
        value: object,
        owner: Fiber | None,
    ) -> None:
        if name in self._services:
            raise RunFailure(f"Service already has a Provider: {name}")
        self._services[name] = value
        self._providers[name] = owner
        provider = "root" if owner is None else owner.id
        self.emit("service", f"{name}: provided by {provider}")

    def _remove_service(self, name: str, owner: Fiber) -> None:
        if self._providers.get(name) is not owner:
            raise RunFailure(f"Service Provider ownership changed: {name}")
        del self._providers[name]
        del self._services[name]
        self.emit("service", f"{name}: removed")

    def _suspend_consumers(self, name: str, errors: list[Exception]) -> None:
        for fiber in reversed(self.fibers):
            if fiber.state is FiberState.ACTIVE and name in fiber.spec.inject:
                try:
                    self._unload(fiber, FiberState.PENDING)
                except Exception as error:
                    errors.append(error)

    def _service_is_available(self, name: str) -> bool:
        if name not in self._services:
            return False
        owner = self._providers[name]
        return owner is None or owner.state is FiberState.ACTIVE

    def _loading_fiber(self, action: str) -> Fiber:
        if self._current is None or self._current.state is not FiberState.LOADING:
            raise RunFailure(f"only a loading Fiber can {action}")
        return self._current

    def _transition(self, fiber: Fiber, state: FiberState) -> None:
        previous = fiber.state
        fiber.state = state
        self.emit("fiber", f"{fiber.id}: {previous.name} -> {state.name}")
