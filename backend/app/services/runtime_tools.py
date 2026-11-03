"""Tool calling for OpenAI-compatible agents: the tools offered, the calls read back, the messages.

A model that may call tools answers either with text or with one or more tool calls. The caller runs
each call and sends the result back as a ``role: "tool"`` message after the assistant message that
made the call; the conversation goes on until an answer carries no call. This module holds only the
shapes and their translation to and from the chat completions API, so the runtime
(``runtime.call_completion``) and the connection test (``connections.probe_completion``) read a call
the same way. Nothing here performs a request or runs a tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal, NotRequired, TypedDict, TypeGuard

import httpx
from pydantic import JsonValue

# The start of a call's error when the provider refused the tools themselves: a caller that offered
# tools recognises it (``error.startswith(TOOLS_REFUSED)``) and can ask again without them.
TOOLS_REFUSED = "tools_refused"

# What a refusal of the tools names: OpenAI ("tool_choice is only allowed when tools are
# specified"), Ollama ("does not support tools"), vLLM ('"auto" tool choice requires
# --enable-auto-tool-choice'), llama.cpp ("tools param requires --jinja flag") and the older
# ``functions`` wording.
TOOLS_REFUSAL = re.compile(r"\b(?:tools?|tool_choice|functions?)\b|tool[ _-]?call", re.IGNORECASE)

type ToolChoice = Literal["auto", "none"]


class ToolDefinition(TypedDict):
    """A tool the model may call: its name, what it does and its arguments as a JSON schema.

    Sent as the chat completions API names one, ``{"type": "function", "function": {...}}``.
    """

    name: str
    description: str
    parameters: dict[str, JsonValue]


class ToolCall(TypedDict):
    """One tool call in an answer.

    ``arguments`` is the model's argument string parsed as JSON. When the string is not JSON,
    ``arguments`` is ``None`` and ``arguments_error`` says why, so the caller answers the model with
    the error instead of failing. ``arguments_text`` is the string as the model wrote it (``"{}"``
    for a call without arguments), which the assistant message that repeats the call sends back.
    """

    id: str
    name: str
    arguments: JsonValue
    arguments_error: str | None
    arguments_text: str


class UserMessage(TypedDict):
    role: Literal["user"]
    content: str


class AssistantMessage(TypedDict):
    """An earlier answer; ``tool_calls`` repeats its calls as ``Completion`` returned them."""

    role: Literal["assistant"]
    content: str
    tool_calls: NotRequired[list[ToolCall]]


class ToolMessage(TypedDict):
    """The result of one tool call, answered to the call that ``tool_call_id`` names."""

    role: Literal["tool"]
    tool_call_id: str
    content: str


# A message of the conversation after the system prompt. A plain ``{"role", "content"}`` mapping,
# as the discussions build them, is taken as well.
type ChatMessage = UserMessage | AssistantMessage | ToolMessage
type Message = ChatMessage | Mapping[str, str]


def tool_definitions(tools: Sequence[ToolDefinition]) -> list[JsonValue]:
    """``tools`` as the request's ``tools`` field."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in tools
    ]


def _repeats_calls(message: Message) -> TypeGuard[AssistantMessage]:
    calls = message.get("tool_calls")
    return message.get("role") == "assistant" and isinstance(calls, list) and calls != []


def wire_message(message: Message) -> dict[str, JsonValue]:
    """A message as the chat completions API takes it.

    An assistant message that made calls carries them as the provider wrote them (``id``, ``type``,
    ``function.name`` and the argument string), and no text is ``null``, as a provider answers it.
    """
    if not _repeats_calls(message):
        return {key: value for key, value in message.items() if isinstance(value, str)}
    calls: list[JsonValue] = [
        {
            "id": call["id"],
            "type": "function",
            "function": {"name": call["name"], "arguments": call["arguments_text"]},
        }
        for call in message.get("tool_calls", [])
    ]
    return {"role": "assistant", "content": message["content"] or None, "tool_calls": calls}


def tool_message(call: ToolCall, content: str) -> ToolMessage:
    """The answer to ``call``: what the tool returned (or why it could not)."""
    return {"role": "tool", "tool_call_id": call["id"], "content": content}


def assistant_message(text: str, calls: Sequence[ToolCall]) -> AssistantMessage:
    """The answer that made ``calls``, to repeat before their results."""
    message: AssistantMessage = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = list(calls)
    return message


def _arguments(raw: JsonValue) -> tuple[JsonValue, str | None, str]:
    """``(arguments, error, text)`` of a call's ``arguments``.

    The API sends a JSON string. No arguments, or an empty string, is a call without arguments; a
    provider that sends an object instead is taken at its word.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, None, "{}"
    if not isinstance(raw, str):
        return raw, None, json.dumps(raw, ensure_ascii=False)
    try:
        parsed: JsonValue = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"The arguments are not JSON: {exc.msg} (character {exc.pos})", raw
    except (ValueError, RecursionError):
        return None, "The arguments are not JSON", raw
    return parsed, None, raw


def read_tool_calls(message: JsonValue) -> list[ToolCall]:
    """The function calls in an answer's ``message``, in the order the model made them.

    An entry without a function name is not a call and is left out. A call without an ``id`` (some
    local servers send none) is named by its position, so its result can still answer it.
    """
    if not isinstance(message, dict):
        return []
    entries = message.get("tool_calls")
    if not isinstance(entries, list):
        return []
    calls: list[ToolCall] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        call_id = entry.get("id")
        arguments, error, text = _arguments(function.get("arguments"))
        calls.append(
            {
                "id": call_id if isinstance(call_id, str) and call_id else f"call_{index}",
                "name": name,
                "arguments": arguments,
                "arguments_error": error,
                "arguments_text": text,
            }
        )
    return calls


def answer_message(body: JsonValue) -> JsonValue:
    """``body["choices"][0]["message"]``, or ``None`` when the body has no such message."""
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    return choices[0].get("message")


def refuses_tools(response: httpx.Response) -> bool:
    """A 400 or 422 whose error names the tools: the provider or the model does not take them.

    An answer that is too long for the model's context counts the tools in its sentence too
    ("500 in the functions"), so a refusal that speaks of the context is not this one.
    """
    if response.status_code not in (400, 422):
        return False
    text = response.text or ""
    return bool(TOOLS_REFUSAL.search(text)) and "context" not in text.lower()


__all__ = [
    "TOOLS_REFUSED",
    "AssistantMessage",
    "ChatMessage",
    "Message",
    "ToolCall",
    "ToolChoice",
    "ToolDefinition",
    "ToolMessage",
    "UserMessage",
    "answer_message",
    "assistant_message",
    "read_tool_calls",
    "refuses_tools",
    "tool_definitions",
    "tool_message",
    "wire_message",
]
