from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from nano_dsh.contracts import (
    AssistantEvent,
    CommandLineArgs,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolResultEvent,
    UserEvent,
)
from nano_dsh.plugins.deepseek import (
    SYSTEM_PROMPT,
    DeepSeekProvider,
    apply,
)


TEST_KEY = "test-secret-key"


def _tool() -> ToolDefinition:
    return ToolDefinition(
        "lookup",
        "Look up one value.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        lambda *_: ToolOutput(""),
    )


def _response(
    *,
    content: str | None = "done",
    reasoning: str | None = "private",
    tool_calls: list[object] | None = None,
    finish_reason: str = "stop",
) -> bytes:
    return json.dumps(
        {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "reasoning_content": reasoning,
                        "tool_calls": tool_calls,
                    },
                }
            ]
        }
    ).encode()


class RecordingTransport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request) -> bytes:
        self.calls.append(request)
        return self.response


class FakeContext:
    def __init__(self, args: CommandLineArgs) -> None:
        self.services: dict[str, object] = {"cmdline_args": args}
        self.traces: list[tuple[str, str]] = []
        self.disposers: list[object] = []

    def get(self, name: str) -> object:
        return self.services[name]

    def emit(self, category: str, message: str) -> None:
        self.traces.append((category, message))

    def provide(self, name: str, value: object) -> None:
        self.services[name] = value
        self.disposers.append(lambda: self.services.pop(name, None))

    def dispose(self) -> None:
        while self.disposers:
            disposer = self.disposers.pop()
            disposer()  # type: ignore[operator]


class DeepSeekProviderTests(unittest.TestCase):
    def test_request_uses_fixed_endpoint_and_default_body(self) -> None:
        transport = RecordingTransport(_response())
        traces: list[tuple[str, str]] = []
        provider = DeepSeekProvider(
            TEST_KEY,
            transport=transport,
            trace=lambda *entry: traces.append(entry),
        )

        provider.complete([UserEvent("fix it")], [_tool()])

        request = transport.calls[0]
        headers = {name.lower(): value for name, value in request.header_items()}
        raw_body = request.data
        self.assertIsInstance(raw_body, bytes)
        body = json.loads(raw_body)
        self.assertEqual(
            request.full_url,
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(headers["authorization"], f"Bearer {TEST_KEY}")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(
            body["messages"],
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "fix it"},
            ],
        )
        self.assertEqual(provider.system_prompt, body["messages"][0]["content"])
        self.assertEqual(
            body["tools"],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Look up one value.",
                        "parameters": _tool().parameters,
                    },
                }
            ],
        )
        self.assertEqual(
            traces,
            [
                ("model", "request"),
                ("model", "response"),
                ("reasoning", "private"),
                ("assistant", "done"),
            ],
        )
        self.assertNotIn(TEST_KEY, repr(traces))
        self.assertIn("private", repr(traces))
        self.assertNotIn("fix it", repr(traces))

    def test_serializes_complete_event_sequence_and_reasoning(self) -> None:
        first = ToolCall("call-1", "lookup", '{"query":"a"}')
        events = [
            UserEvent("question"),
            AssistantEvent("checking", "reasoning verbatim", (first,)),
            ToolResultEvent("call-1", "lookup", "result"),
        ]
        transport = RecordingTransport(_response())
        provider = DeepSeekProvider(TEST_KEY, transport=transport)

        provider.complete(events, [_tool()])

        messages = json.loads(transport.calls[0].data)["messages"]
        self.assertEqual(
            messages[2],
            {
                "role": "assistant",
                "content": "checking",
                "reasoning_content": "reasoning verbatim",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "arguments": '{"query":"a"}',
                        },
                    }
                ],
            },
        )
        self.assertEqual(
            messages[3],
            {
                "role": "tool",
                "content": "result",
                "tool_call_id": "call-1",
            },
        )

    def test_preserves_multiple_tool_calls_in_model_order(self) -> None:
        calls = [
            {
                "id": "second-looking-id",
                "type": "function",
                "function": {"name": "first", "arguments": '{"x": 1}'},
            },
            {
                "id": "first-looking-id",
                "type": "function",
                "function": {"name": "second", "arguments": "not-json-yet"},
            },
        ]
        provider = DeepSeekProvider(
            TEST_KEY,
            transport=RecordingTransport(
                _response(
                    content=None,
                    reasoning="reason",
                    tool_calls=calls,
                    finish_reason="tool_calls",
                )
            ),
        )

        output = provider.complete([], [])

        self.assertEqual(output.content, None)
        self.assertEqual(output.reasoning_content, "reason")
        self.assertEqual(
            output.tool_calls,
            (
                ToolCall("second-looking-id", "first", '{"x": 1}'),
                ToolCall("first-looking-id", "second", "not-json-yet"),
            ),
        )

    def test_normalizes_plain_text_response(self) -> None:
        provider = DeepSeekProvider(
            TEST_KEY,
            transport=RecordingTransport(
                _response(content="final", reasoning="thought")
            ),
        )

        output = provider.complete([], [])

        self.assertEqual(output.content, "final")
        self.assertEqual(output.reasoning_content, "thought")
        self.assertEqual(output.tool_calls, ())

    def test_trace_omits_empty_assistant_sections(self) -> None:
        traces: list[tuple[str, str]] = []
        provider = DeepSeekProvider(
            TEST_KEY,
            transport=RecordingTransport(
                _response(content="", reasoning="")
            ),
            trace=lambda *entry: traces.append(entry),
        )

        provider.complete([], [])

        self.assertEqual(
            traces,
            [("model", "request"), ("model", "response")],
        )

    def test_rejects_falsey_non_list_tool_calls(self) -> None:
        for raw_calls in ("", {}, 0):
            with self.subTest(raw_calls=raw_calls):
                payload = json.loads(_response())
                payload["choices"][0]["message"]["tool_calls"] = raw_calls
                provider = DeepSeekProvider(
                    TEST_KEY,
                    transport=RecordingTransport(json.dumps(payload).encode()),
                )

                with self.assertRaises(AssertionError):
                    provider.complete([], [])

    def test_typed_constructor_configuration_reaches_the_request(self) -> None:
        transport = RecordingTransport(_response())
        provider = DeepSeekProvider(
            TEST_KEY,
            model="deepseek-v4-pro",
            thinking="disabled",
            reasoning_effort="max",
            transport=transport,
        )

        provider.complete([], [])

        body = json.loads(transport.calls[0].data)
        self.assertEqual(body["model"], "deepseek-v4-pro")
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["reasoning_effort"], "max")


class DeepSeekPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.key_file = self.root / "api-key"

    def _args(self, path: Path | None = None) -> CommandLineArgs:
        return CommandLineArgs("task", self.root, path or self.key_file)

    def test_plugin_config_is_trusted_after_loading(self) -> None:
        self.key_file.write_text(TEST_KEY)
        context = FakeContext(self._args())
        apply(context, {"model": "deepseek-v4-pro", "thinking": "disabled"})
        self.assertIsInstance(context.services["llm"], DeepSeekProvider)

    def test_plugin_config_is_optional(self) -> None:
        self.key_file.write_text(TEST_KEY)
        context = FakeContext(self._args())
        apply(context, {})
        self.assertIsInstance(context.services["llm"], DeepSeekProvider)

    def test_apply_provides_fiber_owned_service_and_disposes_it(self) -> None:
        self.key_file.write_text(TEST_KEY + "\n")
        context = FakeContext(self._args())

        apply(context, {})

        self.assertIsInstance(context.services["llm"], DeepSeekProvider)
        self.assertNotIn(TEST_KEY, repr(context.traces))
        context.dispose()
        self.assertNotIn("llm", context.services)


if __name__ == "__main__":
    unittest.main()
