"""Tests for the minimal Cordis runtime."""

from __future__ import annotations

import unittest

from nano_dsh.contracts import PluginSpec
from nano_dsh.cordis import Context, FiberState


def spec(id: str, *inject: str) -> PluginSpec:
    return PluginSpec(id=id, module=f"plugins.{id}", inject=inject)


class ContextTests(unittest.TestCase):
    def test_consumer_before_provider_activates_after_provider_finishes(self) -> None:
        ctx = Context()
        events: list[str] = []

        consumer = ctx.add_fiber(
            spec("consumer", "model"),
            lambda context: events.append(f"consumer:{context.get('model')}"),
        )

        def provide_model(context: Context) -> None:
            events.append("provider:start")
            context.provide("model", "ready")
            events.append("provider:end")

        provider = ctx.add_fiber(spec("provider"), provide_model)

        self.assertEqual(provider.state, FiberState.ACTIVE)
        self.assertEqual(consumer.state, FiberState.ACTIVE)
        self.assertEqual(
            events,
            ["provider:start", "provider:end", "consumer:ready"],
        )

    def test_missing_dependency_remains_pending(self) -> None:
        ctx = Context()
        fiber = ctx.add_fiber(
            spec("consumer", "model", "tools"),
            lambda context: self.fail("pending Consumer activated"),
        )

        ctx.provide_root("model", object())

        self.assertEqual(fiber.state, FiberState.PENDING)
        self.assertEqual(ctx.missing(fiber), ("tools",))

    def test_duplicate_provider_keeps_the_current_service_owned(self) -> None:
        ctx = Context()
        ctx.add_fiber(
            spec("first"),
            lambda context: context.provide("model", "first"),
        )

        with self.assertRaisesRegex(
            AssertionError,
            "Service already has a Provider: model",
        ):
            ctx.add_fiber(
                spec("second"),
                lambda context: context.provide("model", "second"),
            )

        self.assertEqual(ctx.get("model"), "first")

    def test_context_methods_require_an_active_plugin(self) -> None:
        ctx = Context()

        with self.assertRaisesRegex(
            AssertionError,
            r"Context\.provide\(\) requires an active Plugin",
        ):
            ctx.provide("model", object())

        with self.assertRaisesRegex(
            AssertionError,
            r"Context\.effect\(\) requires an active Plugin",
        ):
            ctx.effect(lambda: None)

    def test_plugin_failure_propagates_without_cleanup(self) -> None:
        ctx = Context()
        cleanup: list[str] = []

        def apply(context: Context) -> None:
            context.effect(lambda: lambda: cleanup.append("plugin"))
            assert False, "plugin failed"

        with self.assertRaisesRegex(AssertionError, "plugin failed"):
            ctx.add_fiber(spec("plugin"), apply)

        self.assertEqual(cleanup, [])

    def test_effect_cleanup_uses_reverse_registration_order(self) -> None:
        ctx = Context()
        cleanup: list[str] = []

        def apply(context: Context) -> None:
            context.effect(lambda: lambda: cleanup.append("first"))
            context.effect(lambda: lambda: cleanup.append("second"))
            context.effect(lambda: lambda: cleanup.append("third"))

        fiber = ctx.add_fiber(spec("plugin"), apply)
        ctx.dispose_fiber(fiber)

        self.assertEqual(cleanup, ["third", "second", "first"])
        self.assertNotIn(fiber, ctx.fibers)

    def test_provider_disposal_unloads_consumer(self) -> None:
        ctx = Context()
        cleanup: list[str] = []

        def consume_model(context: Context) -> None:
            context.effect(
                lambda: lambda: cleanup.append(context.get("model"))
            )

        consumer = ctx.add_fiber(
            spec("consumer", "model"),
            consume_model,
        )
        provider = ctx.add_fiber(
            spec("provider"),
            lambda context: context.provide("model", "ready"),
        )

        ctx.dispose_fiber(provider)

        self.assertNotIn(provider, ctx.fibers)
        self.assertEqual(consumer.state, FiberState.PENDING)
        self.assertEqual(cleanup, ["ready"])

    def test_disposer_failure_propagates(self) -> None:
        ctx = Context()
        cleanup: list[str] = []

        def failing_consumer(context: Context) -> None:
            def dispose() -> None:
                cleanup.append("failing")
                assert False, "consumer cleanup failed"

            context.effect(lambda: dispose)

        failing = ctx.add_fiber(spec("failing", "model"), failing_consumer)
        provider = ctx.add_fiber(
            spec("provider"),
            lambda context: context.provide("model", "old"),
        )

        with self.assertRaisesRegex(AssertionError, "consumer cleanup failed"):
            ctx.dispose_fiber(provider)

        self.assertEqual(cleanup, ["failing"])
        self.assertEqual(failing.state, FiberState.ACTIVE)

    def test_replacement_provider_reactivates_consumer(self) -> None:
        ctx = Context()
        seen: list[str] = []
        consumer = ctx.add_fiber(
            spec("consumer", "model"),
            lambda context: seen.append(context.get("model")),
        )
        first = ctx.add_fiber(
            spec("first-provider"),
            lambda context: context.provide("model", "first"),
        )

        ctx.dispose_fiber(first)
        ctx.add_fiber(
            spec("second-provider"),
            lambda context: context.provide("model", "second"),
        )

        self.assertEqual(consumer.state, FiberState.ACTIVE)
        self.assertEqual(seen, ["first", "second"])

    def test_trace_omits_service_values(self) -> None:
        trace: list[tuple[str, str]] = []
        ctx = Context(lambda category, message: trace.append((category, message)))

        ctx.add_fiber(
            spec("provider"),
            lambda context: context.provide("model", "secret-value"),
        )

        self.assertTrue(trace)
        self.assertNotIn("secret-value", repr(trace))

    def test_context_disposal_uses_reverse_creation_order(self) -> None:
        ctx = Context()
        cleanup: list[str] = []

        for name in ("first", "second", "third"):
            ctx.add_fiber(
                spec(name),
                lambda context, name=name: context.effect(
                    lambda: lambda: cleanup.append(name)
                ),
            )

        ctx.dispose()

        self.assertEqual(cleanup, ["third", "second", "first"])
        self.assertEqual(ctx.fibers, [])


if __name__ == "__main__":
    unittest.main()
