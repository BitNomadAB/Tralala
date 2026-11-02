from __future__ import annotations

import logging
from typing import Any

import pytest
from conftest import Api

from app.services import connections

AGENT_LOGGER = "tralala.agents"


def _fake_models(base_url: str, *, api_key: str | None, timeout: float) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "connected",
        "message": "Connected; 1 model(s) reported",
        "latency_ms": 7,
        "models": ["probe-model"],
    }


def test_a_configuration_can_be_tested_before_it_is_saved(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing is persisted: the form asks first, so a dead endpoint never becomes a row."""
    def completion(
        base_url: str, *, model: str, api_key: str | None, timeout: float
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "completed",
            "message": "Model probe-model answered: ok",
            "latency_ms": 22,
        }

    monkeypatch.setattr(connections, "probe_openai_compatible", _fake_models)
    monkeypatch.setattr(connections, "probe_completion", completion)

    with caplog.at_level(logging.INFO, logger=AGENT_LOGGER):
        result = api.data(
            api.post(
                "/api/v1/agents/test",
                json={
                    "connection_type": "openai_compatible",
                    "base_url": "http://127.0.0.1:8080/v1",
                    "model": "probe-model",
                },
            )
        )

    assert result["ok"] is True
    assert result["models"] == ["probe-model"]
    assert result["completion"]["status"] == "completed"
    assert api.data(api.get("/api/v1/agents")) == []

    events = [record.getMessage() for record in caplog.records if record.name == AGENT_LOGGER]
    assert any('"agent_probe_started"' in line for line in events)
    assert any('"agent_probe_finished"' in line for line in events)
    # The audit trail names the endpoint and the model, and never the key or its ciphertext.
    assert all('"api_key":' not in line and "sk-" not in line for line in events)


def test_a_failed_probe_is_logged_as_a_warning_with_the_reason(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def unauthorized(base_url: str, *, api_key: str | None, timeout: float) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "unauthorized",
            "message": "Endpoint rejected the credentials (HTTP 401)",
            "latency_ms": 5,
            "models": [],
        }

    monkeypatch.setattr(connections, "probe_openai_compatible", unauthorized)

    with caplog.at_level(logging.WARNING, logger=AGENT_LOGGER):
        result = api.data(
            api.post(
                "/api/v1/agents/test",
                json={
                    "connection_type": "openai_compatible",
                    "base_url": "http://127.0.0.1:8080/v1",
                    "model": "probe-model",
                },
            )
        )

    assert result["ok"] is False
    assert result["status"] == "unauthorized"
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert warnings, "a refused connection must be visible in the log"
    assert "agent_probe_failed" in warnings[0].getMessage()
    assert "401" in warnings[0].getMessage()


def test_probing_without_an_endpoint_is_explained(api: Api) -> None:
    response = api.post("/api/v1/agents/test", json={"model": "probe-model"})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert "endpoint" in body["error"]["message"].lower()


def test_probing_still_requires_a_signed_in_actor(client: Any) -> None:
    response = client.post(
        "/api/v1/agents/test",
        json={"connection_type": "openai_compatible", "base_url": "http://127.0.0.1:8080/v1"},
    )
    assert response.status_code == 401


def test_a_probe_can_say_no_key_explicitly_and_ignore_a_stored_one(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ticking "no key" must beat a key already stored on the agent."""
    agent = api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": "Keyed agent",
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8080/v1",
                "model": "probe-model",
                "role_template_id": next(
                    role["id"]
                    for role in api.data(api.get("/api/v1/role-templates"))
                    if role["builtin_key"] == "qa_engineer"
                ),
                "api_key": "sk-stored-key",
            },
        )
    )
    seen: list[str | None] = []

    def probe(base_url: str, *, api_key: str | None, timeout: float) -> dict[str, Any]:
        seen.append(api_key)
        return {
            "ok": True,
            "status": "connected",
            "message": "Connected; 1 model(s) reported",
            "latency_ms": 4,
            "models": ["probe-model"],
        }

    def completion(
        base_url: str, *, model: str, api_key: str | None, timeout: float
    ) -> dict[str, Any]:
        seen.append(api_key)
        return {"ok": True, "status": "completed", "message": "answered", "latency_ms": 9}

    monkeypatch.setattr(connections, "probe_openai_compatible", probe)
    monkeypatch.setattr(connections, "probe_completion", completion)

    api.data(api.post(f"/api/v1/agents/{agent['id']}/test", json={"no_api_key": True}))
    assert seen == [None, None], "a stored key must not be sent when the caller says there is none"

    seen.clear()
    api.data(api.post(f"/api/v1/agents/{agent['id']}/test", json={}))
    assert seen == ["sk-stored-key", "sk-stored-key"], "without the flag the stored key is used"
