from __future__ import annotations

import unittest
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from nano_dsh.contracts import (
    AssistantEvent,
    AssistantOutput,
    CommandLineArgs,
    PluginSpec,
    SessionEvent,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolResultEvent,
    UserEvent,
)
from nano_dsh.cordis import Context, FiberState
from nano_dsh.plugins import (
    agent_loop,
    agents,
    headless_runner,
    headless_startup,
    sessions,
    tools,
)
from nano_dsh.plugins.agents import AgentsService
from nano_dsh.plugins.sessions import Session, SessionsService
from nano_dsh.plugins.tools import ToolsService


class FakeContext:
    def __init__(self, llm: object | None = None) -> None:
        self.services: dict[str, object] = {}
        if llm is not None:
            self.services["llm"] = llm
        self.disposers: list[Callable[[], None]] = []
        self.traces: list[tuple[str, str]] = []

    def provide(self, name: str, service: object) -> None:
        assert name not in self.services, f"duplicate Service: {name}"
        self.services[name] = service

    def get(self, name: str) -> object:
        return self.services[name]

    def effect(self, action: Callable[[], Callable[[], None]]) -> None:
        self.disposers.append(action())

    def emit(self, category: str, message: str) -> None:
        self.traces.append((category, message))

    def dispose_effects(self) -> None:
        while self.disposers:
            self.disposers.pop()()


class ScriptedProvider:
    system_prompt = "test system prompt"

    def __init__(
        self,
        responses: Sequence[AssistantOutput],
    ) -> None:
        self._responses = list(responses)
        self.events: list[tuple[SessionEvent, ...]] = []
        self.tools: list[tuple[ToolDefinition, ...]] = []

    def complete(
        self,
        events: Sequence[SessionEvent],
        definitions: Sequence[ToolDefinition],
    ) -> AssistantOutput:
        self.events.append(tuple(events))
        self.tools.append(tuple(definitions))
        assert self._responses, "Scripted Provider exhausted"
        return self._responses.pop(0)


class CountingSessions(SessionsService):
    def __init__(self) -> None:
        self.created: list[Session] = []

    def create(self) -> Session:
        session = super().create()
        self.created.append(session)
        return session


def definition(
    name: str,
    handler: Callable[[object, Path], ToolOutput],
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} description",
        parameters={"type": "object"},
        handler=handler,
    )


class SessionTests(unittest.TestCase):
    def test_events_are_append_only_immutable_snapshots(self) -> None:
        session = Session()
        original = session.events
        user = UserEvent("task")

        session.append(user)

        self.assertEqual(original, ())
        self.assertEqual(session.events, (user,))
        self.assertIsInstance(session.events, tuple)

    def test_apply_publishes_sessions_service(self) -> None:
        ctx = FakeContext()

        sessions.apply(ctx, {})

        service = ctx.get("sessions")
        self.assertIsInstance(service, SessionsService)
        self.assertIsInstance(service.create(), Session)


class AgentsServiceTests(unittest.TestCase):
    def test_factory_registration_creation_and_disposal(self) -> None:
        service = AgentsService()
        created = object()

        class Factory:
            def create(self, workspace: Path) -> Any:
                self.workspace = workspace
                return created

        factory = Factory()
        disposer = service.set_factory(factory)

        self.assertIs(service.create(Path("/workspace")), created)
        self.assertEqual(factory.workspace, Path("/workspace"))
        with self.assertRaisesRegex(AssertionError, "already registered"):
            service.set_factory(Factory())

        disposer()
        disposer()
        replacement = Factory()
        service.set_factory(replacement)
        self.assertIs(service.create(Path("/replacement")), created)
        self.assertEqual(replacement.workspace, Path("/replacement"))

    def test_apply_publishes_agents_service(self) -> None:
        ctx = FakeContext()

        agents.apply(ctx, {})

        self.assertIsInstance(ctx.get("agents"), AgentsService)


class ToolsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.traces: list[tuple[str, str]] = []
        self.service = ToolsService(
            lambda category, message: self.traces.append((category, message))
        )

    def test_registration_rejects_duplicate_and_disposer_removes_tool(self) -> None:
        first = definition(
            "inspect",
            lambda arguments, workspace: ToolOutput("first"),
        )
        second = definition(
            "inspect",
            lambda arguments, workspace: ToolOutput("second"),
        )

        disposer = self.service.register(first)

        self.assertEqual(self.service.definitions(), (first,))
        with self.assertRaises(AssertionError):
            self.service.register(second)

        disposer()
        disposer()
        self.assertEqual(self.service.definitions(), ())
        self.service.register(second)
        self.assertEqual(self.service.definitions(), (second,))

    def test_execute_returns_content_and_records_tool_status(self) -> None:
        received: list[tuple[object, Path]] = []

        def inspect(arguments: object, workspace: Path) -> ToolOutput:
            received.append((arguments, workspace))
            return ToolOutput("ok")

        def reject(arguments: object, workspace: Path) -> ToolOutput:
            return ToolOutput("Error: bad input", failed=True)

        self.service.register(definition("inspect", inspect))
        self.service.register(definition("reject", reject))
        workspace = Path("/workspace")

        result = self.service.execute(
            ToolCall("1", "inspect", '{"path": "a.py", "line": 3}'),
            workspace,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(
            received,
            [({"path": "a.py", "line": 3}, workspace)],
        )
        self.assertEqual(
            self.service.execute(
                ToolCall("2", "missing", "{}"),
                workspace,
            ),
            "Error: unknown Tool: missing",
        )
        self.assertEqual(
            self.service.execute(
                ToolCall("3", "reject", "{}"),
                workspace,
            ),
            "Error: bad input",
        )
        self.assertEqual(
            self.traces,
            [
                ("tool", "execute inspect"),
                ("tool", "complete inspect"),
                ("tool", "execute <unknown>"),
                ("tool", "failed <unknown>"),
                ("tool", "execute reject"),
                ("tool", "failed reject"),
            ],
        )

    def test_invalid_json_propagates(self) -> None:
        self.service.register(
            definition(
                "inspect",
                lambda arguments, workspace: ToolOutput("unused"),
            )
        )

        with self.assertRaises(json.JSONDecodeError):
            self.service.execute(
                ToolCall("1", "inspect", "{broken"),
                Path("/workspace"),
            )

    def test_unknown_tool_name_cannot_inject_trace_lines(self) -> None:
        name = "missing\nmodel: forged trace"

        result = self.service.execute(
            ToolCall("1", name, "{}"),
            Path("/workspace"),
        )

        self.assertEqual(result, f"Error: unknown Tool: {name}")
        self.assertEqual(
            self.traces,
            [
                ("tool", "execute <unknown>"),
                ("tool", "failed <unknown>"),
            ],
        )
        self.assertTrue(all("\n" not in message for _, message in self.traces))

    def test_unexpected_tool_exception_propagates(self) -> None:
        def crash(arguments: object, workspace: Path) -> ToolOutput:
            assert False, "boom"

        self.service.register(definition("crash", crash))

        with self.assertRaisesRegex(AssertionError, "boom"):
            self.service.execute(
                ToolCall("1", "crash", "{}"),
                Path("/workspace"),
            )

    def test_apply_publishes_tools_service(self) -> None:
        ctx = FakeContext()

        tools.apply(ctx, {})

        self.assertIsInstance(ctx.get("tools"), ToolsService)


class AgentLoopIntegrationTests(unittest.TestCase):
    def make_context(self, provider: object) -> FakeContext:
        ctx = FakeContext(provider)
        agents.apply(ctx, {})
        tools.apply(ctx, {})
        ctx.services["sessions"] = CountingSessions()
        agent_loop.apply(ctx, {})
        return ctx

    def test_factory_registration_delays_agent_creation(self) -> None:
        provider = ScriptedProvider((AssistantOutput("Done."),))

        ctx = self.make_context(provider)
        sessions_service = ctx.get("sessions")
        agents_service = ctx.get("agents")

        self.assertIsInstance(sessions_service, CountingSessions)
        self.assertIsInstance(agents_service, AgentsService)
        self.assertEqual(sessions_service.created, [])
        self.assertEqual(provider.events, [])
        agent = agents_service.create(Path("/workspace"))
        self.assertEqual(len(sessions_service.created), 1)
        self.assertEqual(provider.events, [])
        self.assertEqual(agent.run("task"), "Done.")

    def test_two_tool_calls_run_in_order_before_final_response(self) -> None:
        calls = (
            ToolCall("call-1", "record", '{"value": "first"}'),
            ToolCall("call-2", "record", '{"value": "second"}'),
        )
        provider = ScriptedProvider(
            (
                AssistantOutput(
                    content="Working.",
                    reasoning_content="private reasoning",
                    tool_calls=calls,
                ),
                AssistantOutput(
                    content="Done.",
                    reasoning_content="final reasoning",
                ),
            )
        )
        ctx = self.make_context(provider)
        sessions_service = ctx.get("sessions")
        agents_service = ctx.get("agents")
        tools_service = ctx.get("tools")
        self.assertIsInstance(sessions_service, CountingSessions)
        self.assertIsInstance(agents_service, AgentsService)
        self.assertIsInstance(tools_service, ToolsService)
        order: list[str] = []
        events_during_tools: list[tuple[SessionEvent, ...]] = []

        def record(arguments: object, workspace: Path) -> ToolOutput:
            self.assertIsInstance(arguments, Mapping)
            value = arguments["value"]  # type: ignore[index]
            order.append(value)
            events_during_tools.append(sessions_service.created[0].events)
            return ToolOutput(f"result:{value}")

        tools_service.register(definition("record", record))

        result = agents_service.create(Path("/workspace")).run("Fix the bug")

        self.assertEqual(result, "Done.")
        self.assertEqual(order, ["first", "second"])
        self.assertEqual(len(sessions_service.created), 1)
        session_events = sessions_service.created[0].events
        self.assertEqual(
            session_events,
            (
                UserEvent("Fix the bug"),
                AssistantEvent(
                    content="Working.",
                    reasoning_content="private reasoning",
                    tool_calls=calls,
                ),
                ToolResultEvent("call-1", "record", "result:first"),
                ToolResultEvent("call-2", "record", "result:second"),
                AssistantEvent(
                    content="Done.",
                    reasoning_content="final reasoning",
                ),
            ),
        )
        self.assertEqual(len(provider.events), 2)
        self.assertEqual(provider.events[1], session_events[:-1])
        self.assertTrue(
            all(
                isinstance(events[1], AssistantEvent)
                for events in events_during_tools
            )
        )
        self.assertEqual(
            {category for category, message in ctx.traces},
            {"agent", "model", "tool", "tool_result"},
        )
        self.assertIn(
            (
                "tool_result",
                "id: call-1\nname: record\ncontent:\nresult:first",
            ),
            ctx.traces,
        )
        self.assertNotIn("private reasoning", repr(ctx.traces))

        ctx.dispose_effects()

        class ReplacementFactory:
            def create(self, workspace: Path) -> Any:
                return "replacement"

        agents_service.set_factory(ReplacementFactory())
        self.assertEqual(agents_service.create(Path("/workspace")), "replacement")

    def test_tool_failure_outputs_become_results_and_continue(self) -> None:
        calls = (
            ToolCall("unknown", "missing", "{}"),
            ToolCall("failure", "reject", "{}"),
        )
        provider = ScriptedProvider(
            (
                AssistantOutput(content=None, tool_calls=calls),
                AssistantOutput(content="Recovered."),
            )
        )
        ctx = self.make_context(provider)
        tools_service = ctx.get("tools")
        agents_service = ctx.get("agents")
        self.assertIsInstance(tools_service, ToolsService)
        self.assertIsInstance(agents_service, AgentsService)
        def reject(arguments: object, workspace: Path) -> ToolOutput:
            return ToolOutput("Error: bad input", failed=True)

        tools_service.register(definition("reject", reject))

        result = agents_service.create(Path("/workspace")).run("task")

        self.assertEqual(result, "Recovered.")
        results = provider.events[1][-2:]
        self.assertTrue(
            all(isinstance(event, ToolResultEvent) for event in results)
        )
        self.assertTrue(
            all(event.content.startswith("Error:") for event in results)
        )
        self.assertIn("unknown Tool", results[0].content)
        self.assertIn("bad input", results[1].content)

    def test_unexpected_tool_exception_ends_agent_run(self) -> None:
        provider = ScriptedProvider(
            (
                AssistantOutput(
                    content=None,
                    tool_calls=(ToolCall("1", "crash", "{}"),),
                ),
            )
        )
        ctx = self.make_context(provider)
        tools_service = ctx.get("tools")
        agents_service = ctx.get("agents")
        self.assertIsInstance(tools_service, ToolsService)
        self.assertIsInstance(agents_service, AgentsService)

        def crash(arguments: object, workspace: Path) -> ToolOutput:
            assert False, "boom"

        tools_service.register(definition("crash", crash))

        with self.assertRaisesRegex(AssertionError, "boom"):
            agents_service.create(Path("/workspace")).run("task")

    def test_provider_exception_ends_agent_run(self) -> None:
        class FailingProvider:
            def complete(self, events, definitions):
                assert False, "provider unavailable"

        provider = FailingProvider()
        ctx = self.make_context(provider)
        agents_service = ctx.get("agents")
        self.assertIsInstance(agents_service, AgentsService)

        with self.assertRaisesRegex(AssertionError, "provider unavailable"):
            agents_service.create(Path("/workspace")).run("task")

    def test_empty_final_response_fails_visibly(self) -> None:
        for content in (None, "", "   "):
            with self.subTest(content=content):
                provider = ScriptedProvider((AssistantOutput(content),))
                ctx = self.make_context(provider)
                agents_service = ctx.get("agents")
                self.assertIsInstance(agents_service, AgentsService)

                with self.assertRaisesRegex(AssertionError, "non-empty content"):
                    agents_service.create(Path("/workspace")).run("task")

    def test_agent_has_no_model_step_cap(self) -> None:
        tool_steps = 1_001
        responses = [
            AssistantOutput(
                content=None,
                tool_calls=(ToolCall(str(index), "tick", "{}"),),
            )
            for index in range(tool_steps)
        ]
        responses.append(AssistantOutput(content="Done."))
        provider = ScriptedProvider(responses)
        ctx = self.make_context(provider)
        tools_service = ctx.get("tools")
        agents_service = ctx.get("agents")
        self.assertIsInstance(tools_service, ToolsService)
        self.assertIsInstance(agents_service, AgentsService)
        tools_service.register(
            definition(
                "tick",
                lambda arguments, workspace: ToolOutput("ok"),
            )
        )

        result = agents_service.create(Path("/workspace")).run("task")

        self.assertEqual(result, "Done.")
        self.assertEqual(len(provider.events), tool_steps + 1)


class RealContextIntegrationTests(unittest.TestCase):
    def test_pending_agent_loop_activates_and_runs_with_real_context(self) -> None:
        call = ToolCall("call-1", "echo", '{"value": "observed"}')
        provider = ScriptedProvider(
            (
                AssistantOutput(
                    content="Checking.",
                    reasoning_content="private reasoning",
                    tool_calls=(call,),
                ),
                AssistantOutput(content="Done."),
            )
        )
        traces: list[tuple[str, str]] = []
        ctx = Context(
            lambda category, message: traces.append((category, message))
        )
        loop_fiber = ctx.add_fiber(
            PluginSpec(
                id="agent-loop",
                module="nano_dsh.plugins.agent_loop",
                inject=("agents", "sessions", "llm", "tools"),
            ),
            lambda context: agent_loop.apply(context, {}),
        )

        self.assertIs(loop_fiber.state, FiberState.PENDING)
        self.assertEqual(
            ctx.missing(loop_fiber),
            ("agents", "sessions", "llm", "tools"),
        )

        ctx.add_fiber(
            PluginSpec("agents", "nano_dsh.plugins.agents"),
            lambda context: agents.apply(context, {}),
        )
        ctx.add_fiber(
            PluginSpec("sessions", "nano_dsh.plugins.sessions"),
            lambda context: sessions.apply(context, {}),
        )
        ctx.add_fiber(
            PluginSpec("tools", "nano_dsh.plugins.tools"),
            lambda context: tools.apply(context, {}),
        )

        self.assertIs(loop_fiber.state, FiberState.PENDING)
        self.assertEqual(ctx.missing(loop_fiber), ("llm",))
        ctx.provide_root("llm", provider)
        self.assertIs(loop_fiber.state, FiberState.ACTIVE)

        tools_service = ctx.get("tools")
        agents_service = ctx.get("agents")
        self.assertIsInstance(tools_service, ToolsService)
        self.assertIsInstance(agents_service, AgentsService)

        def echo(arguments: object, workspace: Path) -> ToolOutput:
            self.assertIsInstance(arguments, Mapping)
            self.assertEqual(workspace, Path("/workspace"))
            return ToolOutput(arguments["value"])  # type: ignore[index]

        tools_service.register(definition("echo", echo))

        result = agents_service.create(Path("/workspace")).run("Inspect")

        self.assertEqual(result, "Done.")
        self.assertEqual(
            provider.events[1],
            (
                UserEvent("Inspect"),
                AssistantEvent(
                    content="Checking.",
                    reasoning_content="private reasoning",
                    tool_calls=(call,),
                ),
                ToolResultEvent("call-1", "echo", "observed"),
            ),
        )
        self.assertIn(("tool", "execute echo"), traces)
        self.assertNotIn("private reasoning", repr(traces))


class HeadlessFlowTests(unittest.TestCase):
    def test_startup_and_runner_drive_the_registered_factory(self) -> None:
        provider = ScriptedProvider((AssistantOutput("Done."),))
        ctx = FakeContext(provider)
        ctx.services["cmdline_args"] = CommandLineArgs(
            "inspect the workspace",
            Path("/workspace"),
            Path("/api-key"),
        )
        agents.apply(ctx, {})
        sessions.apply(ctx, {})
        tools.apply(ctx, {})
        agent_loop.apply(ctx, {})

        headless_startup.apply(ctx, {"unused": True})
        output = StringIO()
        with redirect_stdout(output):
            headless_runner.apply(ctx, {"unused": True})

        self.assertEqual(output.getvalue(), "Done.\n")
        self.assertEqual(
            provider.events,
            [(UserEvent("inspect the workspace"),)],
        )
        self.assertEqual(
            [
                message
                for category, message in ctx.traces
                if category == "headless"
            ],
            ["run started", "run completed"],
        )
        self.assertEqual(
            ctx.traces[:3],
            [
                ("system", provider.system_prompt),
                ("user", "inspect the workspace"),
                ("headless", "run started"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
