from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from nano_dsh.contracts import (
    AssistantEvent,
    CommandLineArgs,
    RunFailure,
    ToolCall,
    ToolDefinition,
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
        lambda *_: "",
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
    def __init__(self, response: bytes | Exception) -> None:
        self.response = response
        self.calls: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request) -> bytes:
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
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
            ],
        )
        self.assertNotIn(TEST_KEY, repr(traces))
        self.assertNotIn("private", repr(traces))
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

    def test_transport_failures_are_sanitized_without_retry(self) -> None:
        errors = [
            urllib.error.HTTPError(
                "https://example.test",
                401,
                TEST_KEY,
                {},
                None,
            ),
            urllib.error.URLError(TEST_KEY),
            RuntimeError(TEST_KEY),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                transport = RecordingTransport(error)
                provider = DeepSeekProvider(TEST_KEY, transport=transport)
                with self.assertRaises(RunFailure) as caught:
                    provider.complete([], [])
                self.assertEqual(str(caught.exception), "DeepSeek request failed")
                self.assertNotIn(TEST_KEY, str(caught.exception))
                self.assertEqual(len(transport.calls), 1)

    def test_json_and_response_shape_failures_are_sanitized(self) -> None:
        invalid_responses = [
            b"not-json",
            b"[]",
            b'{"error":{"message":"test-secret-key"}}',
            b'{"choices":[]}',
            b'{"choices":[{"message":[],"finish_reason":"stop"}]}',
            b'{"choices":[{"message":{"content":"x"},"finish_reason":"stop"}]}',
            b'{"choices":[{"message":{"content":7},"finish_reason":"stop"}]}',
            b'{"choices":[{"message":{"role":"assistant","tool_calls":{}}}]}',
            _response(
                content=None,
                tool_calls=[{"id": "bad"}],
                finish_reason="tool_calls",
            ),
        ]
        for response in invalid_responses:
            with self.subTest(response=response[:40]):
                provider = DeepSeekProvider(
                    TEST_KEY,
                    transport=RecordingTransport(response),
                )
                with self.assertRaises(RunFailure) as caught:
                    provider.complete([], [])
                self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_finish_reason_is_required_and_matches_tool_calls(self) -> None:
        missing = json.loads(_response(content=TEST_KEY))
        del missing["choices"][0]["finish_reason"]
        call = {
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": "{}"},
        }
        invalid_responses = [
            json.dumps(missing).encode(),
            _response(content=TEST_KEY, finish_reason="length"),
            _response(
                content=TEST_KEY,
                tool_calls=[call],
                finish_reason="stop",
            ),
            _response(content=TEST_KEY, finish_reason="tool_calls"),
        ]
        for response in invalid_responses:
            with self.subTest(response=response[:60]):
                provider = DeepSeekProvider(
                    TEST_KEY,
                    transport=RecordingTransport(response),
                )
                with self.assertRaises(RunFailure) as caught:
                    provider.complete([], [])
                self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_constructor_does_not_accept_base_url(self) -> None:
        with self.assertRaises(TypeError):
            DeepSeekProvider(
                TEST_KEY,
                base_url="https://attacker.example",  # type: ignore[call-arg]
            )

    def test_invalid_constructor_configuration_fails(self) -> None:
        cases = [
            {"model": ""},
            {"thinking": "sometimes"},
            {"reasoning_effort": "medium"},
            {"stream": True},
        ]
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(RunFailure):
                    DeepSeekProvider(TEST_KEY, **values)  # type: ignore[arg-type]


class DeepSeekPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.key_file = self.root / "api-key"

    def _args(self, path: Path | None = None) -> CommandLineArgs:
        return CommandLineArgs("task", self.root, path or self.key_file)

    def test_missing_and_empty_key_files_fail(self) -> None:
        for content in (None, "", " \n", "one\ntwo\n"):
            with self.subTest(content=content):
                key_file = self.root / f"key-{len(list(self.root.iterdir()))}"
                if content is not None:
                    key_file.write_text(content)
                with self.assertRaises(RunFailure) as caught:
                    apply(FakeContext(self._args(key_file)), {})
                self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_invalid_plugin_config_fails(self) -> None:
        self.key_file.write_text(TEST_KEY)
        invalid = [
            {"unknown": True},
            {"stream": "false"},
        ]
        for config in invalid:
            with self.subTest(config=config):
                with self.assertRaises(RunFailure) as caught:
                    apply(FakeContext(self._args()), config)
                self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_plugin_config_rejects_base_url(self) -> None:
        self.key_file.write_text(TEST_KEY)
        with self.assertRaises(RunFailure) as caught:
            apply(
                FakeContext(self._args()),
                {"base_url": "https://attacker.example"},
            )
        self.assertNotIn(TEST_KEY, str(caught.exception))

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
