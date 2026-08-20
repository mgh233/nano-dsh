from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nano_dsh.boot import boot
from nano_dsh.contracts import PluginSpec
from nano_dsh.cordis import Context, FiberState


class BootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.profile = Path(self.directory.name) / "profile.toml"
        self.profile.write_text('bundles = []')

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_provides_root_services_before_loading_plugins(self) -> None:
        context = Context()
        first = object()
        second = object()

        def load(_profile):
            self.assertIs(context.get("first"), first)
            self.assertIs(context.get("second"), second)
            return ()

        with patch("nano_dsh.boot.Loader.load", side_effect=load):
            result = boot(
                self.profile,
                {"first": first, "second": second},
                lambda *_: None,
                context_factory=lambda trace: context,
            )

        self.assertIs(result, context)

    def test_audit_reports_pending_fiber_and_missing_services(self) -> None:
        context = Context()
        fiber = context.add_fiber(
            PluginSpec("consumer", "test.consumer", ("agents",)),
            lambda _context: self.fail("pending Consumer activated"),
        )
        with patch("nano_dsh.boot.Loader.load", return_value=()):
            with self.assertRaisesRegex(
                AssertionError,
                r"consumer.*state=PENDING.*agents",
            ):
                boot(self.profile, {}, lambda *_: None, context_factory=lambda trace: context)

        self.assertIs(fiber.state, FiberState.PENDING)

    def test_loading_failure_propagates_without_disposal(self) -> None:
        context = Context()
        cleanup: list[str] = []

        def load(_profile):
            context.add_fiber(
                PluginSpec("plugin", "test.plugin"),
                lambda runtime: runtime.effect(
                    lambda: lambda: cleanup.append("plugin")
                ),
            )
            assert False, "load failed"

        with patch("nano_dsh.boot.Loader.load", side_effect=load):
            with self.assertRaisesRegex(AssertionError, "load failed"):
                boot(self.profile, {}, lambda *_: None, context_factory=lambda trace: context)

        self.assertEqual(cleanup, [])


if __name__ == "__main__":
    unittest.main()
