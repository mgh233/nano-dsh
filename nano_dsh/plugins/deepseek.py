# Synchronous DeepSeek Chat Completions Provider Plugin.

import json
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from nano_dsh import contracts as c


SYSTEM_PROMPT = "You are a coding agent. Use the provided tools to inspect and modify the Workspace. Continue until the task is complete. Then give a concise final response."
_ENDPOINT = "https://api.deepseek.com/chat/completions"
Transport = Callable[[urllib.request.Request], bytes]


def _send(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


class DeepSeekProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "deepseek-v4-flash",
        thinking: str = "enabled",
        reasoning_effort: str = "high",
        stream: bool = False,
        transport: Transport | None = None,
        trace: c.Trace | None = None,
    ) -> None:
        assert isinstance(api_key, str) and api_key.strip()
        assert isinstance(model, str) and model.strip()
        assert thinking in ("enabled", "disabled")
        assert reasoning_effort in ("high", "max")
        assert stream is False
        self._api_key = api_key
        self._model = model
        self._thinking = thinking
        self._reasoning_effort = reasoning_effort
        self._transport = transport or _send
        self._trace = trace

    def complete(
        self,
        events: Sequence[c.SessionEvent],
        tools: Sequence[c.ToolDefinition],
    ) -> c.AssistantOutput:
        payload = {
            "model": self._model,
            "messages": _messages(events),
            "tools": [_tool_definition(tool) for tool in tools],
            "tool_choice": "auto",
            "thinking": {"type": self._thinking},
            "reasoning_effort": self._reasoning_effort,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        self._emit("request")
        request = urllib.request.Request(_ENDPOINT, body, headers, method="POST")
        raw = self._transport(request)
        self._emit("response")
        payload = json.loads(raw.decode("utf-8"))
        return _assistant_output(payload)

    def _emit(self, phase: str) -> None:
        if self._trace is not None:
            self._trace("model", phase)


def _messages(events: Sequence[c.SessionEvent]) -> list[dict[str, Any]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for event in events:
        if isinstance(event, c.UserEvent):
            messages.append({"role": "user", "content": event.content})
        elif isinstance(event, c.AssistantEvent):
            message: dict[str, Any] = {"role": "assistant", "content": event.content}
            if event.reasoning_content is not None:
                message["reasoning_content"] = event.reasoning_content
            if event.tool_calls:
                message["tool_calls"] = [_tool_call(call) for call in event.tool_calls]
            messages.append(message)
        elif isinstance(event, c.ToolResultEvent):
            messages.append({
                "role": "tool", "content": event.content,
                "tool_call_id": event.tool_call_id,
            })
        else:
            assert False
    return messages


def _tool_call(call: c.ToolCall) -> dict[str, Any]:
    function = {"name": call.name, "arguments": call.arguments}
    return {"id": call.id, "type": "function", "function": function}


def _tool_definition(tool: c.ToolDefinition) -> dict[str, Any]:
    function = {"name": tool.name, "description": tool.description,
                "parameters": tool.parameters}
    return {"type": "function", "function": function}


def _assistant_output(payload: object) -> c.AssistantOutput:
    assert isinstance(payload, dict)
    assert "error" not in payload
    choices = payload["choices"]
    assert isinstance(choices, list) and len(choices) == 1
    choice = choices[0]
    assert isinstance(choice, dict)
    message = choice["message"]
    assert isinstance(message, dict) and message.get("role") == "assistant"
    content = message.get("content")
    reasoning = message.get("reasoning_content")
    assert content is None or isinstance(content, str)
    assert reasoning is None or isinstance(reasoning, str)
    raw_calls = message.get("tool_calls")
    assert raw_calls is None or isinstance(raw_calls, list)
    calls = tuple(_parse_tool_call(call) for call in raw_calls or ())
    assert choice["finish_reason"] == ("tool_calls" if calls else "stop")
    return c.AssistantOutput(content, reasoning, calls)


def _parse_tool_call(value: object) -> c.ToolCall:
    assert isinstance(value, dict) and value.get("type") == "function"
    function = value.get("function")
    assert isinstance(function, dict)
    call_id = value.get("id")
    name = function.get("name")
    arguments = function.get("arguments")
    assert isinstance(call_id, str) and call_id
    assert isinstance(name, str) and name
    assert isinstance(arguments, str)
    return c.ToolCall(call_id, name, arguments)


def _read_api_key(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].strip()
    return lines[0]


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    args: c.CommandLineArgs = ctx.get("cmdline_args")
    provider = DeepSeekProvider(
        _read_api_key(args.api_key_file),
        model=config.get("model", "deepseek-v4-flash"),
        thinking=config.get("thinking", "enabled"),
        reasoning_effort=config.get("reasoning_effort", "high"),
        stream=config.get("stream", False),
        trace=ctx.emit,
    )
    ctx.provide("llm", provider)
