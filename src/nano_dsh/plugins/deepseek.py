"""Synchronous DeepSeek Chat Completions Provider Plugin."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from nano_dsh import contracts as c


SYSTEM_PROMPT = "You are a coding agent. Use the provided tools to inspect and modify the Workspace. Continue until the task is complete. Then give a concise final response."
Transport = Callable[[str, Mapping[str, str], bytes], bytes]


def _post(url: str, headers: Mapping[str, str], body: bytes) -> bytes:
    request = urllib.request.Request(url, body, dict(headers), method="POST")
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


class DeepSeekProvider:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        thinking: str = "enabled",
        reasoning_effort: str = "high",
        stream: bool = False,
        transport: Transport | None = None,
        trace: c.Trace | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise c.RunFailure("DeepSeek API key must be non-empty")
        self._base_url = _base_url(base_url)
        if not isinstance(model, str) or not model.strip():
            raise c.RunFailure("DeepSeek model must be a non-empty string")
        if thinking not in ("enabled", "disabled"):
            raise c.RunFailure("DeepSeek thinking must be enabled or disabled")
        if reasoning_effort not in ("high", "max"):
            raise c.RunFailure("DeepSeek reasoning_effort must be high or max")
        if stream is not False:
            raise c.RunFailure("DeepSeek stream must be false")
        self._api_key = api_key
        self._model = model
        self._thinking = thinking
        self._reasoning_effort = reasoning_effort
        self._transport = transport or _post
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
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            raise c.RunFailure("DeepSeek request serialization failed") from None
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        self._emit("request")
        try:
            url = f"{self._base_url}/chat/completions"
            raw = self._transport(url, headers, body)
        except Exception:
            raise c.RunFailure("DeepSeek request failed") from None
        self._emit("response")
        try:
            if not isinstance(raw, bytes):
                raise TypeError
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise c.RunFailure("DeepSeek response is not valid JSON") from None
        return _assistant_output(payload)

    def _emit(self, phase: str) -> None:
        if self._trace is not None:
            self._trace("model", phase)


def _base_url(value: object) -> str:
    if not isinstance(value, str):
        raise c.RunFailure("DeepSeek base_url must be an HTTPS origin")
    parsed = urlsplit(value)
    invalid = (
        parsed.scheme != "https", not parsed.netloc, parsed.username is not None,
        parsed.password is not None, parsed.path not in ("", "/"),
        bool(parsed.query), bool(parsed.fragment),
    )
    if any(invalid):
        raise c.RunFailure("DeepSeek base_url must be an HTTPS origin")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


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
            raise c.RunFailure("Unsupported Session Event")
    return messages


def _tool_call(call: c.ToolCall) -> dict[str, Any]:
    function = {"name": call.name, "arguments": call.arguments}
    return {"id": call.id, "type": "function", "function": function}


def _tool_definition(tool: c.ToolDefinition) -> dict[str, Any]:
    function = {"name": tool.name, "description": tool.description,
                "parameters": tool.parameters}
    return {"type": "function", "function": function}


def _assistant_output(payload: object) -> c.AssistantOutput:
    if not isinstance(payload, dict):
        raise c.RunFailure("DeepSeek response has an invalid shape")
    if "error" in payload:
        raise c.RunFailure("DeepSeek API returned an error")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise c.RunFailure("DeepSeek response has an invalid shape")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise c.RunFailure("DeepSeek response has an invalid shape")
    message = choice["message"]
    if message.get("role") != "assistant":
        raise c.RunFailure("DeepSeek response has an invalid shape")
    content = _optional_text(message, "content")
    reasoning = _optional_text(message, "reasoning_content")
    raw_calls = message.get("tool_calls")
    if raw_calls is None:
        raw_calls = []
    elif not isinstance(raw_calls, list):
        raise c.RunFailure("DeepSeek response has an invalid shape")
    calls = tuple(_parse_tool_call(call) for call in raw_calls)
    finish = choice.get("finish_reason")
    if finish is not None:
        expected = "tool_calls" if calls else "stop"
        if finish != expected:
            raise c.RunFailure("DeepSeek response did not finish normally")
    return c.AssistantOutput(content, reasoning, calls)


def _optional_text(message: Mapping[str, object], name: str) -> str | None:
    value = message.get(name)
    if value is not None and not isinstance(value, str):
        raise c.RunFailure("DeepSeek response has an invalid shape")
    return value


def _parse_tool_call(value: object) -> c.ToolCall:
    if not isinstance(value, dict) or value.get("type") != "function":
        raise c.RunFailure("DeepSeek response has an invalid Tool Call")
    function = value.get("function")
    if not isinstance(function, dict):
        raise c.RunFailure("DeepSeek response has an invalid Tool Call")
    call_id = value.get("id")
    name = function.get("name")
    arguments = function.get("arguments")
    invalid = (
        not isinstance(call_id, str), not call_id,
        not isinstance(name, str), not name,
        not isinstance(arguments, str),
    )
    if any(invalid):
        raise c.RunFailure("DeepSeek response has an invalid Tool Call")
    return c.ToolCall(call_id, name, arguments)


def _read_api_key(path: Path) -> str:
    if not isinstance(path, Path):
        raise c.RunFailure("DeepSeek API key file path must be a Path")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise c.RunFailure("DeepSeek API key file cannot be read") from None
    if len(lines) != 1 or not lines[0].strip():
        raise c.RunFailure("DeepSeek API key file must contain one non-empty line")
    return lines[0]


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    if not isinstance(config, Mapping):
        raise c.RunFailure("DeepSeek Plugin config must be a mapping")
    allowed = {"base_url", "model", "thinking", "reasoning_effort", "stream"}
    if not set(config).issubset(allowed):
        raise c.RunFailure("DeepSeek Plugin config has unknown fields")
    args = ctx.get("cmdline_args")
    if not isinstance(args, c.CommandLineArgs):
        raise c.RunFailure("cmdline_args must be CommandLineArgs")
    provider = DeepSeekProvider(
        _read_api_key(args.api_key_file),
        base_url=config.get("base_url", "https://api.deepseek.com"),
        model=config.get("model", "deepseek-v4-flash"),
        thinking=config.get("thinking", "enabled"),
        reasoning_effort=config.get("reasoning_effort", "high"),
        stream=config.get("stream", False),
        trace=ctx.emit,
    )
    ctx.provide("llm", provider)
