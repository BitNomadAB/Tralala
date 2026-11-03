"""Agent calls: what is sent to a provider and how each answer becomes a result.

The runtime's real pinned client runs with a stand-in resolver, and the provider behind it is an
in-process ``httpx.MockTransport``: the request the runtime builds is captured and a fixed response
comes back, so no name is looked up, no socket is opened and the same input always gives the same
result.
"""

# The pure part of a request or database path is often a private helper; these tests call it
# on purpose (AGENTS.md, Verification contract), so private access is allowed in this file.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import socket
from collections.abc import Callable

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter

from app.core.config import Settings
from app.core.secrets import seal_secret
from app.services import connections, runtime, runtime_tools

Handler = Callable[[httpx.Request], httpx.Response]

# The stand-in resolver: a self-hosted model on the local network, and one name moved to the
# cloud metadata address after its endpoint was saved.
RESOLVES_TO = {
    "llm.example.com": ["192.168.1.20"],
    "a2a.example.com": ["192.168.1.21"],
    "moved.example.com": ["169.254.169.254"],
}


def _resolve(host: str) -> list[str]:
    if host not in RESOLVES_TO:
        raise socket.gaierror(socket.EAI_NONAME, "unknown host")
    return RESOLVES_TO[host]


def _named(request: httpx.Request) -> str:
    """The URL the runtime asked for: the pinned request keeps the name in its Host header."""
    return str(request.url.copy_with(netloc=request.headers["host"].encode("ascii")))


_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def member(value: JsonValue, *keys: str) -> JsonValue:
    """``value[key][key]...`` of a JSON object, failing the test where the shape differs."""
    for key in keys:
        assert isinstance(value, dict), value
        value = value[key]
    return value


class Provider:
    """Records every request the runtime sends and answers with the installed handler."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []
        self.client_options: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def body(self, index: int = -1) -> dict[str, JsonValue]:
        return _JSON_OBJECT.validate_json(self.requests[index].content)


@pytest.fixture()
def provider(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], Provider]:
    real_client = connections.endpoint_client

    def install(handler: Handler) -> Provider:
        recorder = Provider(handler)

        def client(*, timeout: float, allow_private: bool) -> httpx.Client:
            recorder.client_options.append({"timeout": timeout, "allow_private": allow_private})
            return real_client(
                timeout=timeout,
                allow_private=allow_private,
                resolve=_resolve,
                connect=lambda: httpx.MockTransport(recorder),
            )

        monkeypatch.setattr(connections, "endpoint_client", client)
        return recorder

    return install


def _agent(connection_type: str = "openai_compatible", **overrides: object) -> dict[str, object]:
    return {
        "id": "agent-1",
        "name": "Planner",
        "connection_type": connection_type,
        "base_url": "http://llm.example.com/v1/",
        "model": None,
        "temperature": None,
        "max_output_tokens": None,
        "timeout_seconds": 10,
        "api_key_ciphertext": None,
        **overrides,
    }


def _completion(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "served-model",
            "choices": [{"message": {"content": f"  {text}  "}}],
            "usage": {"total_tokens": 9},
        },
    )


# --- OpenAI-compatible chat completions ---------------------------------------------------------


def test_a_completion_sends_the_system_prompt_first(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(lambda _request: _completion("AGREE"))
    result = runtime.call_completion(
        settings,
        _agent(),
        system_prompt="You are the architect.",
        messages=[{"role": "user", "content": "Is the plan sound?"}],
    )
    assert result == {
        "ok": True,
        "error": None,
        "text": "AGREE",
        "tool_calls": [],
        "model": "served-model",
        "usage": {"total_tokens": 9},
    }
    request = recorder.requests[0]
    assert _named(request) == "http://llm.example.com/v1/chat/completions"
    assert request.url.host == "192.168.1.20"
    assert "authorization" not in request.headers
    assert recorder.body() == {
        "model": "default",
        "messages": [
            {"role": "system", "content": "You are the architect."},
            {"role": "user", "content": "Is the plan sound?"},
        ],
    }
    assert recorder.client_options == [{"timeout": 10.0, "allow_private": True}]


def test_a_provider_that_refuses_a_temperature_answers_when_nobody_chose_one(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    def refuse_temperature(request: httpx.Request) -> httpx.Response:
        sent: JsonValue = json.loads(request.content)
        if isinstance(sent, dict) and "temperature" in sent:
            return httpx.Response(400, json={"error": {"message": "temperature is not supported"}})
        return _completion("ok")

    recorder = provider(refuse_temperature)
    result = runtime.call_completion(settings, _agent(), system_prompt="s", messages=[])
    assert (result["ok"], result["text"]) == (True, "ok")
    assert "temperature" not in recorder.body()
    # A caller's choice is still sent, and the provider's refusal still carries its sentence.
    refused = runtime.call_completion(
        settings, _agent(), system_prompt="s", messages=[], temperature=0.2
    )
    assert (refused["ok"], refused["error"]) == (False, "HTTP 400: temperature is not supported")
    assert recorder.body()["temperature"] == 0.2


@pytest.mark.parametrize("connection_type", ["openai_compatible", "a2a"])
def test_a_call_that_runs_out_of_time_names_the_agents_timeout(
    settings: Settings, provider: Callable[[Handler], Provider], connection_type: str
) -> None:
    def too_slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider(too_slow)
    agent = _agent(connection_type, timeout_seconds=180)
    result = runtime.call_completion(settings, agent, system_prompt="s", messages=[])
    assert result == {
        "ok": False,
        "error": "No answer within 180 s (the agent's timeout setting)",
        "text": "",
        "tool_calls": [],
    }


def test_the_agent_settings_and_its_sealed_key_reach_the_request(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(lambda _request: _completion("ok"))
    agent = _agent(
        model="example-model",
        temperature=0.0,
        max_output_tokens=512,
        api_key_ciphertext=seal_secret(settings, "sk-provider-key"),
    )
    runtime.call_completion(settings, agent, system_prompt="s", messages=[])
    assert recorder.requests[0].headers["authorization"] == "Bearer sk-provider-key"
    body = recorder.body()
    assert (body["model"], body["temperature"], body["max_tokens"]) == ("example-model", 0.0, 512)


def test_a_refused_completion_carries_the_provider_sentence(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    provider(lambda _request: httpx.Response(400, json={"error": {"message": "Model Not Exist"}}))
    result = runtime.call_completion(settings, _agent(), system_prompt="s", messages=[])
    assert result == {
        "ok": False,
        "error": "HTTP 400: Model Not Exist",
        "text": "",
        "tool_calls": [],
    }


def test_an_answer_that_is_not_a_completion_is_malformed(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    provider(lambda _request: httpx.Response(200, json={"choices": []}))
    result = runtime.call_completion(settings, _agent(), system_prompt="s", messages=[])
    assert result == {"ok": False, "error": "malformed_response", "text": "", "tool_calls": []}


def test_an_unreachable_provider_is_named_by_its_failure(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider(refuse)
    result = runtime.call_completion(settings, _agent(), system_prompt="s", messages=[])
    assert result == {"ok": False, "error": "ConnectError", "text": "", "tool_calls": []}


def test_a_name_moved_to_a_refused_address_is_never_called(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(lambda _request: _completion("ok"))
    moved = _agent(base_url="http://moved.example.com/v1")
    result = runtime.call_completion(settings, moved, system_prompt="s", messages=[])
    assert result == {"ok": False, "error": "ForbiddenAddressError", "text": "", "tool_calls": []}
    assert recorder.requests == []


def test_a_private_model_is_not_called_when_private_endpoints_are_disabled(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(lambda _request: _completion("ok"))
    public_only = settings.model_copy(update={"agents_allow_private_endpoints": False})
    result = runtime.call_completion(public_only, _agent(), system_prompt="s", messages=[])
    assert result == {"ok": False, "error": "ForbiddenAddressError", "text": "", "tool_calls": []}
    assert recorder.client_options == [{"timeout": 10.0, "allow_private": False}]
    assert recorder.requests == []


# --- the answer's format: a JSON schema where the provider takes one ----------------------------

SCHEMA: runtime.ResponseSchema = {
    "name": "analysis",
    "schema": {"type": "object", "properties": {"outcome": {"type": "string"}}},
}
RESPONSE_FORMAT = {"type": "json_schema", "json_schema": SCHEMA}
REFUSED = {
    "error": {
        "message": "Invalid parameter: 'response_format' of type 'json_schema' is not supported",
        "param": "response_format",
    }
}


def _requires_the_schema(request: httpx.Request) -> httpx.Response:
    """A provider that answers only a request that asks for the JSON schema."""
    if json.loads(request.content).get("response_format") != RESPONSE_FORMAT:
        return httpx.Response(400, json={"error": {"message": "this model needs a schema"}})
    return _completion('{"outcome": "ok"}')


def _refuses_the_schema(request: httpx.Request) -> httpx.Response:
    """A provider that refuses ``response_format`` and answers everything else."""
    if "response_format" in json.loads(request.content):
        return httpx.Response(400, json=REFUSED)
    return _completion('{"outcome": "ok"}')


def test_an_agent_whose_provider_takes_a_schema_is_sent_it(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(_requires_the_schema)
    agent = _agent(supports_json_schema=1)
    result = runtime.call_completion(
        settings, agent, system_prompt="s", messages=[], response_schema=SCHEMA
    )
    assert (result["ok"], result["text"]) == (True, '{"outcome": "ok"}')
    assert len(recorder.requests) == 1
    assert recorder.body()["response_format"] == RESPONSE_FORMAT


def test_a_provider_that_refuses_the_schema_is_asked_again_without_it(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(_refuses_the_schema)
    agent = _agent(supports_json_schema=1)
    result = runtime.call_completion(
        settings, agent, system_prompt="s", messages=[], response_schema=SCHEMA
    )
    assert (result["ok"], result["error"], result["text"]) == (True, None, '{"outcome": "ok"}')
    first, second = recorder.body(0), recorder.body(1)
    assert first["response_format"] == RESPONSE_FORMAT
    assert second == {key: value for key, value in first.items() if key != "response_format"}


@pytest.mark.parametrize(
    ("supports", "schema"), [(0, SCHEMA), (1, None)], ids=["provider without", "no schema"]
)
def test_the_schema_is_sent_only_with_a_provider_that_takes_one(
    settings: Settings,
    provider: Callable[[Handler], Provider],
    supports: int,
    schema: runtime.ResponseSchema | None,
) -> None:
    recorder = provider(_refuses_the_schema)
    agent = _agent(supports_json_schema=supports)
    result = runtime.call_completion(
        settings, agent, system_prompt="s", messages=[], response_schema=schema
    )
    assert result["ok"] is True
    assert len(recorder.requests) == 1
    assert "response_format" not in recorder.body()


def test_a_refusal_that_does_not_name_the_format_is_reported_not_retried(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(
        lambda _request: httpx.Response(400, json={"error": {"message": "context too long"}})
    )
    agent = _agent(supports_json_schema=1)
    result = runtime.call_completion(
        settings, agent, system_prompt="s", messages=[], response_schema=SCHEMA
    )
    assert result == {
        "ok": False,
        "error": "HTTP 400: context too long",
        "text": "",
        "tool_calls": [],
    }
    assert len(recorder.requests) == 1


def test_a_refusal_names_the_format_only_in_a_400() -> None:
    assert runtime.refuses_response_format(httpx.Response(400, json=REFUSED))
    assert not runtime.refuses_response_format(httpx.Response(422, json=REFUSED))
    assert not runtime.refuses_response_format(httpx.Response(400, json={"error": "bad model"}))


def test_an_a2a_agent_never_gets_the_schema(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(_a2a(lambda _message: _task("ok"), None))
    agent = _agent("a2a", supports_json_schema=1)
    result = runtime.call_completion(
        settings, agent, system_prompt="s", messages=[], response_schema=SCHEMA
    )
    assert result["ok"] is True
    assert "response_format" not in recorder.body()


def test_a_discussion_call_adds_the_position(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    provider(lambda _request: _completion("The plan holds.\nVerdict: AGREE"))
    result = runtime.call_agent(settings, _agent(), system_prompt="s", messages=[])
    assert (result["verdict"], result["justification"]) == ("agree", "The plan holds.")

    provider(lambda _request: httpx.Response(503, text="busy"))
    failed = runtime.call_agent(settings, _agent(), system_prompt="s", messages=[])
    assert (failed["ok"], failed["verdict"]) == (False, "abstain")
    assert failed["error"] == "HTTP 503: busy"


# --- A2A ----------------------------------------------------------------------------------------


def _a2a(rpc: Callable[[object], object], card_url: str | None) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if card_url is None:
                return httpx.Response(404, json={"error": "missing"})
            return httpx.Response(200, json={"name": "Stub agent", "url": card_url})
        return httpx.Response(200, json=rpc(json.loads(request.content)))

    return handle


def _task(*texts: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "kind": "task",
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": text} for text in texts]}],
        },
    }


def test_an_a2a_agent_is_called_over_message_send(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(_a2a(lambda _message: _task("AGREE", "Echo"), "http://a2a.example.com/rpc"))
    result = runtime.call_completion(
        settings,
        _agent("a2a"),
        system_prompt="You are the architect.",
        messages=[{"role": "user", "content": "Is the plan sound?"}],
    )
    assert result == {
        "ok": True,
        "error": None,
        "text": "AGREE\nEcho",
        "tool_calls": [],
        "model": "a2a",
        "usage": {},
    }
    card, rpc = recorder.requests
    assert _named(card) == "http://llm.example.com/v1/.well-known/agent.json"
    assert _named(rpc) == "http://a2a.example.com/rpc"
    assert (card.url.host, rpc.url.host) == ("192.168.1.20", "192.168.1.21")
    sent = recorder.body()
    assert sent["method"] == "message/send"
    assert member(sent, "params", "configuration") == {"blocking": True}
    assert member(sent, "params", "message", "parts") == [
        {
            "kind": "text",
            "text": "[instructions]\nYou are the architect.\n\n[user]\nIs the plan sound?",
        }
    ]


def test_without_a_card_the_base_url_is_the_endpoint(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(_a2a(lambda _message: _task("ok"), None))
    runtime.call_a2a(settings, _agent("a2a"), system_prompt="", messages=[])
    assert _named(recorder.requests[-1]) == "http://llm.example.com/v1"


@pytest.mark.parametrize(
    "card_url", ["http://169.254.169.254/latest/meta-data", "http://moved.example.com/rpc"]
)
def test_a_card_that_names_a_refused_endpoint_is_not_followed(
    settings: Settings, provider: Callable[[Handler], Provider], card_url: str
) -> None:
    recorder = provider(_a2a(lambda _message: _task("ok"), card_url))
    result = runtime.call_a2a(settings, _agent("a2a"), system_prompt="", messages=[])
    assert result == {"ok": False, "error": "ForbiddenAddressError", "text": "", "tool_calls": []}
    assert [request.method for request in recorder.requests] == ["GET"]


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ({"jsonrpc": "2.0", "id": "1", "error": {"code": -32000}}, "a2a:-32000"),
        ({"jsonrpc": "2.0", "id": "1", "result": {"kind": "task"}}, "a2a_empty_response"),
        (_task("   "), "a2a_empty_response"),
    ],
)
def test_an_a2a_failure_is_reported_not_invented(
    settings: Settings,
    provider: Callable[[Handler], Provider],
    answer: dict[str, object],
    error: str,
) -> None:
    provider(_a2a(lambda _message: answer, None))
    result = runtime.call_a2a(settings, _agent("a2a"), system_prompt="", messages=[])
    assert result == {"ok": False, "error": error, "text": "", "tool_calls": []}


def test_the_transcript_carries_every_role_in_order() -> None:
    messages = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Second"},
        {"content": "Third"},
    ]
    assert runtime._transcript("Rules", messages) == (
        "[instructions]\nRules\n\n[user]\nFirst\n\n[assistant]\nSecond\n\n[user]\nThird"
    )
    assert runtime._transcript("", [{"role": "user", "content": "Only"}]) == "[user]\nOnly"


def test_text_is_collected_from_every_shape_a_server_answers_with() -> None:
    answer: dict[str, object] = {
        "parts": [{"kind": "text", "text": "message part"}, {"kind": "data", "data": {}}],
        "artifacts": [{"parts": [{"text": "artifact part"}]}],
        "status": {"message": {"parts": [{"text": "status part"}]}},
    }
    assert runtime._text_parts(answer) == ["message part", "artifact part", "status part"]
    assert runtime._text_parts(None) == []
    assert runtime._text_parts(["not", "a", "dict"]) == []


# --- tools: offered where the model calls them, the calls read back -----------------------------

READ_FILE: runtime_tools.ToolDefinition = {
    "name": "read_file",
    "description": "Read a file of the repository.",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}
WIRE_TOOLS: list[JsonValue] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file of the repository.",
            "parameters": READ_FILE["parameters"],
        },
    }
]


def _calls(message: dict[str, JsonValue]) -> httpx.Response:
    """A chat completion whose answer is ``message``."""
    return httpx.Response(
        200, json={"model": "served-model", "choices": [{"message": message}], "usage": {}}
    )


def _call(call_id: str, name: str, arguments: JsonValue) -> dict[str, JsonValue]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def test_an_answer_that_calls_tools_returns_the_calls_and_no_text(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    answer: dict[str, JsonValue] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            _call("call_a", "read_file", '{"path": "README.md"}'),
            _call("call_b", "read_file", '{"path": "docs/'),
        ],
    }
    provider(lambda _request: _calls(answer))
    result = runtime.call_completion(
        settings, _agent(supports_tools=1), system_prompt="s", messages=[], tools=[READ_FILE]
    )
    assert (result["ok"], result["error"], result["text"]) == (True, None, "")
    good, bad = result["tool_calls"]
    assert good == {
        "id": "call_a",
        "name": "read_file",
        "arguments": {"path": "README.md"},
        "arguments_error": None,
        "arguments_text": '{"path": "README.md"}',
    }
    # Arguments that are not JSON are named, not a failed call: the model is told and tries again.
    assert (bad["id"], bad["arguments"]) == ("call_b", None)
    assert bad["arguments_text"] == '{"path": "docs/'
    assert str(bad["arguments_error"]).startswith("The arguments are not JSON: ")


def test_an_answer_that_only_calls_tools_may_carry_no_content_key(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    provider(lambda _request: _calls({"tool_calls": [_call("c", "read_file", "{}")]}))
    result = runtime.call_completion(
        settings, _agent(supports_tools=1), system_prompt="s", messages=[], tools=[READ_FILE]
    )
    assert (result["ok"], result["text"], len(result["tool_calls"])) == (True, "", 1)
    # Without a call, a message without content is still not a completion.
    provider(lambda _request: _calls({"role": "assistant"}))
    malformed = runtime.call_completion(settings, _agent(), system_prompt="s", messages=[])
    assert malformed == {"ok": False, "error": "malformed_response", "text": "", "tool_calls": []}


def test_a_text_answer_has_no_tool_calls(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    provider(lambda _request: _completion("Done."))
    result = runtime.call_completion(
        settings, _agent(supports_tools=1), system_prompt="s", messages=[], tools=[READ_FILE]
    )
    assert (result["text"], result["tool_calls"]) == ("Done.", [])


def test_an_agent_whose_model_calls_tools_is_offered_them(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(lambda _request: _completion("ok"))
    agent = _agent(supports_tools=1)
    runtime.call_completion(settings, agent, system_prompt="s", messages=[], tools=[READ_FILE])
    assert (recorder.body()["tools"], recorder.body()["tool_choice"]) == (WIRE_TOOLS, "auto")
    runtime.call_completion(
        settings, agent, system_prompt="s", messages=[], tools=[READ_FILE], tool_choice="none"
    )
    assert recorder.body()["tool_choice"] == "none"


@pytest.mark.parametrize(
    ("supports", "tools"),
    [(0, [READ_FILE]), (1, None), (1, [])],
    ids=["model without", "no tools", "an empty list"],
)
def test_tools_are_sent_only_when_given_to_a_model_that_calls_them(
    settings: Settings,
    provider: Callable[[Handler], Provider],
    supports: int,
    tools: list[runtime_tools.ToolDefinition] | None,
) -> None:
    recorder = provider(lambda _request: _completion("ok"))
    agent = _agent(supports_tools=supports)
    result = runtime.call_completion(settings, agent, system_prompt="s", messages=[], tools=tools)
    assert result["ok"] is True
    assert ("tools" in recorder.body(), "tool_choice" in recorder.body()) == (False, False)


def test_an_a2a_agent_never_gets_tools(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(_a2a(lambda _message: _task("ok"), None))
    agent = _agent("a2a", supports_tools=1)
    result = runtime.call_completion(
        settings, agent, system_prompt="s", messages=[], tools=[READ_FILE]
    )
    assert (result["ok"], result["tool_calls"]) == (True, [])
    assert "tools" not in json.dumps(recorder.body())


@pytest.mark.parametrize(
    "sentence",
    [
        "registry.ollama.ai/library/gemma:2b does not support tools",
        '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set',
        "tools param requires --jinja flag",
        "Unrecognized request argument supplied: functions",
    ],
)
def test_a_provider_that_refuses_the_tools_is_named_and_not_asked_again(
    settings: Settings, provider: Callable[[Handler], Provider], sentence: str
) -> None:
    recorder = provider(lambda _request: httpx.Response(400, json={"error": {"message": sentence}}))
    result = runtime.call_completion(
        settings, _agent(supports_tools=1), system_prompt="s", messages=[], tools=[READ_FILE]
    )
    assert result == {
        "ok": False,
        "error": f"{runtime_tools.TOOLS_REFUSED}: HTTP 400: {sentence}",
        "text": "",
        "tool_calls": [],
    }
    assert len(recorder.requests) == 1


def test_a_refusal_is_only_about_the_tools_when_tools_were_sent(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    refusal = {"error": {"message": "this model does not support tools"}}
    provider(lambda _request: httpx.Response(400, json=refusal))
    agent = _agent(supports_tools=1)
    result = runtime.call_completion(settings, agent, system_prompt="s", messages=[])
    assert result["error"] == "HTTP 400: this model does not support tools"


def test_a_refusal_of_the_tools_is_a_400_or_422_that_names_them() -> None:
    def refusal(status: int, sentence: str) -> bool:
        return runtime_tools.refuses_tools(
            httpx.Response(status, json={"error": {"message": sentence}})
        )

    assert refusal(400, "tool_choice is only allowed when tools are specified")
    assert refusal(422, "Tool calling is not supported by this model")
    assert not refusal(500, "tools param requires --jinja flag")
    assert not refusal(400, "Model Not Exist")
    # A context overflow counts the tools in its sentence; it is not a refusal of them.
    assert not refusal(
        400, "maximum context length is 8192 tokens; you requested 9000 (500 in the functions)"
    )


def test_a_conversation_with_tool_calls_is_sent_as_the_api_names_it(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    recorder = provider(lambda _request: _completion("The README says so."))
    call: runtime_tools.ToolCall = {
        "id": "call_a",
        "name": "read_file",
        "arguments": {"path": "README.md"},
        "arguments_error": None,
        "arguments_text": '{"path": "README.md"}',
    }
    messages: list[runtime_tools.Message] = [
        {"role": "user", "content": "Is there a README?"},
        runtime_tools.assistant_message("", [call]),
        runtime_tools.tool_message(call, "1: # Tralala"),
        runtime_tools.assistant_message("Noted.", []),
        {"role": "user", "content": "Answer now."},
    ]
    runtime.call_completion(
        settings, _agent(supports_tools=1), system_prompt="s", messages=messages, tools=[READ_FILE]
    )
    assert recorder.body()["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "Is there a README?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "README.md"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "1: # Tralala"},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "Answer now."},
    ]


def test_every_call_shape_a_server_answers_with_is_read() -> None:
    message: JsonValue = {
        "tool_calls": [
            {"function": {"name": "list_files", "arguments": ""}},
            {"id": "call_b", "function": {"name": "search", "arguments": {"pattern": "TODO"}}},
            {"id": "call_c", "function": {"name": "read_file"}},
            {"id": "no-name", "function": {"arguments": "{}"}},
            {"id": "no-function"},
            "not a call",
        ]
    }
    calls = runtime_tools.read_tool_calls(message)
    assert [(call["id"], call["name"], call["arguments"]) for call in calls] == [
        ("call_0", "list_files", {}),
        ("call_b", "search", {"pattern": "TODO"}),
        ("call_c", "read_file", {}),
    ]
    assert [call["arguments_text"] for call in calls] == ["{}", '{"pattern": "TODO"}', "{}"]
    assert runtime_tools.read_tool_calls({"tool_calls": "none"}) == []
    assert runtime_tools.read_tool_calls(None) == []
    assert runtime_tools.answer_message({"choices": [{"message": message}]}) == message
    assert runtime_tools.answer_message({"choices": []}) is None
