# A minimal Service-driven Plugin lifecycle runtime.

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from nano_dsh.contracts import Disposer, PluginSpec, Trace


class FiberState(Enum):
    # The lifecycle state of one Plugin Fiber.
    PENDING = auto()
    LOADING = auto()
    ACTIVE = auto()

PluginApply = Callable[["Context"], None]


@dataclass
class Fiber:
    # One Plugin instance and the Effects created by its activation.
    id: str
    spec: PluginSpec
    apply: PluginApply = field(repr=False)
    state: FiberState = FiberState.PENDING
    effects: list[Disposer] = field(default_factory=list, repr=False)


class Context:
    # Store Services and activate Fibers when their requirements are ready.

    def __init__(self, trace: Trace | None = None) -> None:
        self.fibers: list[Fiber] = []
        self._trace = trace
        self._services: dict[str, tuple[object, Fiber | None]] = {}
        self._current: Fiber | None = None

    def provide_root(self, name: str, value: object) -> None:
        # Publish a Service that is owned by the Context.
        self._register_service(name, value, None)
        self._stabilize()

    def add_fiber(self, spec: PluginSpec, apply: PluginApply) -> Fiber:
        # Create a Fiber and activate every newly ready Fiber.
        fiber = Fiber(spec.id, spec, apply)
        self.fibers.append(fiber)
        self.emit("fiber", f"{fiber.id}: PENDING")
        self._stabilize()
        return fiber

    def get(self, name: str) -> object:
        # Return one currently available Service.
        return self._services[name][0]

    def provide(self, name: str, value: object) -> None:
        # Publish a Service owned by the loading Fiber.
        owner = self._current
        assert owner is not None and owner.state is FiberState.LOADING, (
            "Context.provide() requires an active Plugin"
        )
        self._register_service(name, value, owner)
        owner.effects.append(lambda: self._remove_service(name, owner))

    def effect(self, setup: Callable[[], Disposer | None]) -> None:
        # Run setup and bind its optional disposer to the loading Fiber.
        owner = self._current
        assert owner is not None and owner.state is FiberState.LOADING, (
            "Context.effect() requires an active Plugin"
        )
        disposer = setup()
        if disposer is None:
            return
        owner.effects.append(disposer)

    def dispose_fiber(self, fiber: Fiber) -> None:
        # Permanently dispose one Fiber.
        if fiber.state is FiberState.ACTIVE:
            self._unload(fiber)
        self.fibers.remove(fiber)
        self._stabilize()

    def dispose(self) -> None:
        # Dispose all Fibers in reverse creation order.
        for fiber in reversed(self.fibers):
            self.dispose_fiber(fiber)
        self._services.clear()

    def missing(self, fiber: Fiber) -> tuple[str, ...]:
        # Return required Service names that are not available.
        return tuple(
            name for name in fiber.spec.inject
            if not self._service_is_available(name)
        )

    def emit(self, category: str, message: str) -> None:
        # Send one concise teaching trace event.
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
        self._current = fiber
        fiber.apply(self)
        self._current = None
        self._transition(fiber, FiberState.ACTIVE)

    def _unload(self, fiber: Fiber) -> None:
        for name, (_, owner) in tuple(self._services.items()):
            if owner is fiber:
                self._suspend_consumers(name)
        self._cleanup(fiber)
        self._transition(fiber, FiberState.PENDING)

    def _cleanup(self, fiber: Fiber) -> None:
        while fiber.effects:
            fiber.effects.pop()()

    def _register_service(self, name: str, value: object, owner: Fiber | None) -> None:
        assert name not in self._services, f"Service already has a Provider: {name}"
        self._services[name] = (value, owner)
        provider = "root" if owner is None else owner.id
        self.emit("service", f"{name}: provided by {provider}")

    def _remove_service(self, name: str, owner: Fiber) -> None:
        assert self._services[name][1] is owner
        del self._services[name]
        self.emit("service", f"{name}: removed")

    def _suspend_consumers(self, name: str) -> None:
        for fiber in reversed(self.fibers):
            if fiber.state is FiberState.ACTIVE and name in fiber.spec.inject:
                self._unload(fiber)

    def _service_is_available(self, name: str) -> bool:
        service = self._services.get(name)
        return service is not None and (
            service[1] is None or service[1].state is FiberState.ACTIVE
        )

    def _transition(self, fiber: Fiber, state: FiberState) -> None:
        previous = fiber.state
        fiber.state = state
        self.emit("fiber", f"{fiber.id}: {previous.name} -> {state.name}")
