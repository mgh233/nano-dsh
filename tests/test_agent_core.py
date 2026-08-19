from __future__ import annotations

import unittest
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from nano_dsh.contracts import (
    AssistantEvent,
    AssistantOutput,
    RunFailure,
    SessionEvent,
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResultEvent,
    UserEvent,
)
from nano_dsh.plugins import agent_loop, agents, sessions, tools
from nano_dsh.plugins.agents import AgentsService
from nano_dsh.plugins.sessions import Session, SessionsService
from nano_dsh.plugins.tools import ToolsService


class FakeContext:
    def __init__(self, llm: object | None = None) -> None:
        self.llm = llm
        self.services: dict[str, object] = {}
        self.disposers: list[Callable[[], None]] = []
        self.traces: list[tuple[str, str]] = []

    def provide(self, name: str, service: object) -> None:
        if name in self.services:
            raise RuntimeError(f"duplicate Service: {name}")
        self.services[name] = service
        setattr(self, name, service)

    def effect(self, action: Callable[[], Callable[[], None]]) -> None:
        self.disposers.append(action())

    def trace(self, category: str, message: str) -> None:
        self.traces.append((category, message))

    def dispose_effects(self) -> None:
        while self.disposers:
            self.disposers.pop()()


class ScriptedProvider:
    def __init__(self, responses: Sequence[AssistantOutput]) -> None:
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
        if not self._responses:
            raise AssertionError("Scripted Provider exhausted")
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
    handler: Callable[[object, Path], str],
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

        self.assertIsInstance(ctx.sessions, SessionsService)
        self.assertIsInstance(ctx.sessions.create(), Session)


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
        with self.assertRaisesRegex(RunFailure, "already registered"):
            service.set_factory(Factory())

        disposer()
        disposer()
        with self.assertRaisesRegex(RunFailure, "no AgentFactory"):
            service.create(Path("/workspace"))

    def test_apply_publishes_agents_service(self) -> None:
        ctx = FakeContext()

        agents.apply(ctx, {})

        self.assertIsInstance(ctx.agents, AgentsService)


class ToolsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.traces: list[tuple[str, str]] = []
        self.service = ToolsService(
            lambda category, message: self.traces.append((category, message))
        )

    def test_registration_rejects_duplicate_and_disposer_removes_tool(self) -> None:
        first = definition("inspect", lambda arguments, workspace: "first")
        second = definition("inspect", lambda arguments, workspace: "second")

        disposer = self.service.register(first)

        self.assertEqual(self.service.definitions(), (first,))
        with self.assertRaisesRegex(RunFailure, "already registered"):
            self.service.register(second)

        disposer()
        disposer()
        self.assertEqual(self.service.definitions(), ())
        self.service.register(second)
        self.assertEqual(self.service.definitions(), (second,))

    def test_execute_parses_json_and_returns_tool_failures(self) -> None:
        received: list[tuple[object, Path]] = []

        def inspect(arguments: object, workspace: Path) -> str:
            received.append((arguments, workspace))
            return "ok"

        def reject(arguments: object, workspace: Path) -> str:
            raise ToolFailure("bad input")

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
        self.assertTrue(
            self.service.execute(
                ToolCall("2", "inspect", "{broken"),
                workspace,
            ).startswith("Error:")
        )
        self.assertTrue(
            self.service.execute(
                ToolCall("3", "missing", "{}"),
                workspace,
            ).startswith("Error:")
        )
        self.assertEqual(
            self.service.execute(
                ToolCall("4", "reject", "{}"),
                workspace,
            ),
            "Error: bad input",
        )

    def test_unexpected_tool_exception_propagates(self) -> None:
        class UnexpectedError(Exception):
            pass

        def crash(arguments: object, workspace: Path) -> str:
            raise UnexpectedError("boom")

        self.service.register(definition("crash", crash))

        with self.assertRaisesRegex(UnexpectedError, "boom"):
            self.service.execute(
                ToolCall("1", "crash", "{}"),
                Path("/workspace"),
            )

    def test_apply_publishes_tools_service(self) -> None:
        ctx = FakeContext()

        tools.apply(ctx, {})

        self.assertIsInstance(ctx.tools, ToolsService)


class AgentLoopIntegrationTests(unittest.TestCase):
    def make_context(self, provider: ScriptedProvider) -> FakeContext:
        ctx = FakeContext(provider)
        agents.apply(ctx, {})
        tools.apply(ctx, {})
        ctx.sessions = CountingSessions()
        ctx.services["sessions"] = ctx.sessions
        agent_loop.apply(ctx, {})
        return ctx

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
        order: list[str] = []
        events_during_tools: list[tuple[SessionEvent, ...]] = []

        def record(arguments: object, workspace: Path) -> str:
            self.assertIsInstance(arguments, Mapping)
            value = arguments["value"]  # type: ignore[index]
            order.append(value)
            events_during_tools.append(ctx.sessions.created[0].events)
            return f"result:{value}"

        ctx.tools.register(definition("record", record))

        result = ctx.agents.create(Path("/workspace")).run("Fix the bug")

        self.assertEqual(result, "Done.")
        self.assertEqual(order, ["first", "second"])
        self.assertEqual(len(ctx.sessions.created), 1)
        session_events = ctx.sessions.created[0].events
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
            {"agent", "tool"},
        )

        ctx.dispose_effects()
        with self.assertRaisesRegex(RunFailure, "no AgentFactory"):
            ctx.agents.create(Path("/workspace"))

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

        class UnexpectedError(Exception):
            pass

        def crash(arguments: object, workspace: Path) -> str:
            raise UnexpectedError("boom")

        ctx.tools.register(definition("crash", crash))

        with self.assertRaisesRegex(UnexpectedError, "boom"):
            ctx.agents.create(Path("/workspace")).run("task")

    def test_empty_final_response_fails_visibly(self) -> None:
        for content in (None, "", "   "):
            with self.subTest(content=content):
                provider = ScriptedProvider((AssistantOutput(content),))
                ctx = self.make_context(provider)

                with self.assertRaisesRegex(RunFailure, "non-empty content"):
                    ctx.agents.create(Path("/workspace")).run("task")


if __name__ == "__main__":
    unittest.main()
