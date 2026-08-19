from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nano_dsh.boot import boot
from nano_dsh.contracts import RunFailure


class Fiber:
    def __init__(self, fiber_id: str, state: str) -> None:
        self.id = fiber_id
        self.state = state


class FakeContext:
    def __init__(self, trace, fibers: list[Fiber]) -> None:
        self.trace = trace
        self.fibers = fibers
        self.events: list[tuple[str, object]] = []
        self.disposed = False

    def provide_root(self, name: str, service: object) -> None:
        self.events.append(("root", name))

    def add_fiber(self, spec, apply) -> None:
        self.events.append(("fiber", spec.id))

    def missing(self, fiber: Fiber) -> tuple[str, ...]:
        return ("agents",) if fiber.id == "consumer" else ()

    def dispose(self) -> None:
        self.disposed = True

    def emit(self, category: str, detail: str) -> None:
        self.events.append((category, detail))


class BootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.profile = Path(self.directory.name) / "profile.toml"
        self.profile.write_text('bundles = []')

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_provides_root_services_before_loading_plugins(self) -> None:
        context = FakeContext(lambda *_: None, [Fiber("ready", "ACTIVE")])
        def load(_profile):
            context.events.append(("load", "plugins"))
            return ()

        with patch("nano_dsh.boot.Loader.load", side_effect=load):
            result = boot(
                self.profile,
                {"first": object(), "second": object()},
                lambda *_: None,
                context_factory=lambda trace: context,
            )

        self.assertIs(result, context)
        self.assertEqual(
            context.events,
            [("root", "first"), ("root", "second"), ("load", "plugins")],
        )

    def test_audit_reports_pending_fiber_and_missing_services(self) -> None:
        context = FakeContext(lambda *_: None, [Fiber("consumer", "PENDING")])
        with patch("nano_dsh.boot.Loader.load", return_value=()):
            with self.assertRaisesRegex(RunFailure, r"consumer.*agents"):
                boot(self.profile, {}, lambda *_: None, context_factory=lambda trace: context)

        self.assertTrue(context.disposed)

    def test_disposes_context_when_loading_fails(self) -> None:
        context = FakeContext(lambda *_: None, [])
        with patch("nano_dsh.boot.Loader.load", side_effect=RunFailure("bad profile")):
            with self.assertRaisesRegex(RunFailure, "bad profile"):
                boot(self.profile, {}, lambda *_: None, context_factory=lambda trace: context)

        self.assertTrue(context.disposed)


if __name__ == "__main__":
    unittest.main()
