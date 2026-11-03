"""Agent calls: what is sent to a provider and how each answer becomes a result.

The provider is an in-process ``httpx.MockTransport``: the request the runtime builds is captured
and a fixed response comes back, so no socket is opened and the same input always gives the same
result.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.secrets import seal_secret
from app.services import runtime

Handler = Callable[[httpx.Request], httpx.Response]


class Provider:
    """Records every request the runtime sends and answers with the installed handler."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []
        self.client_options: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)


@pytest.fixture()
def provider(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], Provider]:
    real_client = httpx.Client

    def install(handler: Handler) -> Provider:
        recorder = Provider(handler)

        def client(**options: Any) -> httpx.Client:
            recorder.client_options.append(options)
            return real_client(transport=httpx.MockTransport(recorder), **options)

        monkeypatch.setattr(runtime.httpx, "Client", client)
        return recorder

    return install


def _agent(connection_type: str = "openai_compatible", **overrides: Any) -> dict[str, Any]:
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
        "model": "served-model",
        "usage": {"total_tokens": 9},
    }
    request = recorder.requests[0]
    assert str(request.url) == "http://llm.example.com/v1/chat/completions"
    assert "authorization" not in request.headers
    assert recorder.body() == {
        "model": "default",
        "messages": [
            {"role": "system", "content": "You are the architect."},
            {"role": "user", "content": "Is the plan sound?"},
        ],
        "temperature": 0.3,
    }
    assert recorder.client_options[0]["follow_redirects"] is False


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
    assert result == {"ok": False, "error": "HTTP 400: Model Not Exist", "text": ""}


def test_an_answer_that_is_not_a_completion_is_malformed(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    provider(lambda _request: httpx.Response(200, json={"choices": []}))
    result = runtime.call_completion(settings, _agent(), system_prompt="s", messages=[])
    assert result == {"ok": False, "error": "malformed_response", "text": ""}


def test_an_unreachable_provider_is_named_by_its_failure(
    settings: Settings, provider: Callable[[Handler], Provider]
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider(refuse)
    result = runtime.call_completion(settings, _agent(), system_prompt="s", messages=[])
    assert result == {"ok": False, "error": "ConnectError", "text": ""}


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


def _a2a(rpc: Callable[[dict[str, Any]], dict[str, Any]], card_url: str | None) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if card_url is None:
                return httpx.Response(404, json={"error": "missing"})
            return httpx.Response(200, json={"name": "Stub agent", "url": card_url})
        return httpx.Response(200, json=rpc(json.loads(request.content)))

    return handle


def _task(*texts: str) -> dict[str, Any]:
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
    assert result == {"ok": True, "error": None, "text": "AGREE\nEcho", "model": "a2a", "usage": {}}
    card, rpc = recorder.requests
    assert str(card.url) == "http://llm.example.com/v1/.well-known/agent.json"
    assert str(rpc.url) == "http://a2a.example.com/rpc"
    sent = recorder.body()
    assert sent["method"] == "message/send"
    assert sent["params"]["configuration"] == {"blocking": True}
    assert sent["params"]["message"]["parts"] == [
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
    assert str(recorder.requests[-1].url) == "http://llm.example.com/v1"


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
    answer: dict[str, Any],
    error: str,
) -> None:
    provider(_a2a(lambda _message: answer, None))
    result = runtime.call_a2a(settings, _agent("a2a"), system_prompt="", messages=[])
    assert result == {"ok": False, "error": error, "text": ""}


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
    answer = {
        "parts": [{"kind": "text", "text": "message part"}, {"kind": "data", "data": {}}],
        "artifacts": [{"parts": [{"text": "artifact part"}]}],
        "status": {"message": {"parts": [{"text": "status part"}]}},
    }
    assert runtime._text_parts(answer) == ["message part", "artifact part", "status part"]
    assert runtime._text_parts(None) == []
    assert runtime._text_parts(["not", "a", "dict"]) == []
