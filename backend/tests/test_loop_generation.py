"""Generation runs: bounded output, validated promotion, failure and recovery."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from conftest import Api

from app.services import runtime


def _base(board: dict[str, Any], loop: dict[str, Any]) -> str:
    return f"/api/v1/boards/{board['id']}/loops/{loop['id']}"


def _agent(api: Api) -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == "qa_engineer")
    return api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": "planner",
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "role_template_id": role["id"],
            },
        )
    )


def _wait_run(api: Api, url: str, run_id: str) -> dict[str, Any]:
    for _ in range(100):
        run = api.data(api.get(f"{url}/{run_id}"))
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("generation run did not finish")


def _analysis_json() -> str:
    return (
        '{"schema_version":1,"outcome":"Verify email","scope":["mail"],'
        '"findings":[{"id":"F-01","title":"Nothing exists","category":"change",'
        '"technical_detail":"detail","plain_language":"This must be built from scratch."}],'
        '"assumptions":[],"open_questions":["Which provider?"],"options":[],'
        '"recommendation":"Pick a provider","verification":["sign-in blocked"],'
        '"sources":[],"repository_revision":""}'
    )


def test_analysis_generation_is_validated_and_promoted(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent(api)
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    captured: dict[str, Any] = {}

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        captured["messages"] = kwargs.get("messages", [])
        return {
            "ok": True,
            "error": None,
            "text": "```json\n" + _analysis_json() + "\n```",
            "model": "test-model",
            "usage": {"total_tokens": 12},
        }

    monkeypatch.setattr(runtime, "call_completion", fake_call)
    started = api.data(
        api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    run = _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])
    assert run["status"] == "completed", run
    assert run["usage"]["total_tokens"] == 12
    assert "JSON schema" in captured["system_prompt"]
    documents = api.data(api.get(f"{_base(board, loop)}/documents"))["documents"]
    assert documents["analysis_ai"]["state"] == "ready_for_review"
    assert "This must be built from scratch." in documents["analysis"]["current_content"]
    loop_row = api.data(api.get(_base(board, loop)))
    assert loop_row["stage"] == "analysis_review"
    history = api.data(api.get(f"{_base(board, loop)}/generation-runs"))
    assert history[0]["status"] == "completed"


def test_invalid_output_never_creates_documents(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent(api)
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))

    def broken(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "error": None, "text": '{"not": "the schema"}', "usage": {}}

    monkeypatch.setattr(runtime, "call_completion", broken)
    started = api.data(
        api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    run = _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])
    assert run["status"] == "failed"
    assert run["error_code"] == "invalid_output"
    documents = api.data(api.get(f"{_base(board, loop)}/documents"))["documents"]
    assert documents["analysis_ai"]["state"] == "empty"


def test_provider_failure_is_reported_not_fabricated(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent(api)
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))

    def unavailable(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"ok": False, "error": "HTTP 503", "text": ""}

    monkeypatch.setattr(runtime, "call_completion", unavailable)
    started = api.data(
        api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    run = _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])
    assert run["status"] == "failed"
    assert run["error_code"] == "provider_error"


def test_generation_without_an_agent_is_explained(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    response = api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "generation_unavailable"


def test_interrupted_runs_are_marked_failed_at_startup(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    services = api.client.app.state.services
    _agent(api)
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))

    def slow(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        time.sleep(2)
        return {"ok": True, "error": None, "text": _analysis_json(), "usage": {}}

    monkeypatch.setattr(runtime, "call_completion", slow)
    started = api.data(
        api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    time.sleep(0.2)
    # The run is started in a worker thread; wait until it is actually running before pretending the
    # process died, otherwise there is nothing to recover and the assertion is a race.
    run_url = f"{_base(board, loop)}/generation-runs/{started['id']}"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if api.data(api.get(run_url))["status"] == "running":
            break
        time.sleep(0.05)
    recovered = services.loop_generation.recover(board["id"])
    assert recovered >= 1
    run = api.data(api.get(run_url))
    assert run["status"] == "failed"
    assert run["error_code"] == "interrupted"

def test_history_provenance_hashes_the_prompt_instead_of_copying_it() -> None:
    from app.services.loop_history import generation_provenance

    prompt = "You are the technical analysis agent for a software change initiative."
    provenance = generation_provenance(
        [
            {
                "id": "run-1",
                "purpose": "analysis",
                "status": "completed",
                "agent_id": "agent-1",
                "agent_name": "planner",
                "model": "test-model",
                "role_snapshot_json": json.dumps(
                    {"system_prompt": prompt, "agent_name": "planner", "purpose": "analysis"}
                ),
                "usage_json": json.dumps({"total_tokens": 12}),
                "created_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "error_code": None,
            }
        ]
    )
    assert set(provenance[0]) == {
        "run_id",
        "purpose",
        "status",
        "agent_id",
        "agent_name",
        "model",
        "system_prompt_sha256",
        "usage",
        "created_at",
        "finished_at",
        "error_code",
    }
    expected = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert provenance[0]["system_prompt_sha256"] == expected
    assert prompt not in json.dumps(provenance)

def test_a_run_that_loses_its_loop_names_the_reason(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent(api)
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    started = threading.Event()

    def slow_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        started.set()
        time.sleep(0.3)
        return {
            "ok": True,
            "error": None,
            "text": _analysis_json(),
            "model": "test-model",
            "usage": {},
        }

    monkeypatch.setattr(runtime, "call_completion", slow_call)
    run = api.data(
        api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    assert started.wait(5)
    loop_row = api.data(api.get(_base(board, loop)))
    api.data(
        api.post(
            f"{_base(board, loop)}/cancel",
            json={"version": loop_row["version"], "reason": "Stopping the Loop"},
        )
    )
    finished = _wait_run(api, f"{_base(board, loop)}/generation-runs", run["id"])
    assert finished["status"] == "failed"
    assert finished["error_code"] == "loop_closed"
    assert "not retryable" in (finished["error_message"] or "")

def _agent_named(
    api: Api,
    name: str,
    *,
    connection_type: str = "openai_compatible",
    enabled: bool = True,
    role_key: str = "qa_engineer",
) -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == role_key)
    return api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": name,
                "connection_type": connection_type,
                "base_url": "http://127.0.0.1:8099/v1",
                "model": f"{name}-model",
                "role_template_id": role["id"],
                "enabled": enabled,
            },
        )
    )


def test_generation_uses_the_agent_the_caller_picks(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent(api)
    chosen = _agent_named(api, "review agent", role_key="analytics_agent")
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    used: dict[str, Any] = {}

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        used["agent"] = agent_row
        used["system_prompt"] = kwargs.get("system_prompt", "")
        return {"ok": True, "error": None, "text": _analysis_json(), "model": "m", "usage": {}}

    monkeypatch.setattr(runtime, "call_completion", fake_call)
    started = api.data(
        api.post(
            f"{_base(board, loop)}/generation-runs",
            json={"purpose": "analysis", "agent_id": chosen["id"]},
        )
    )
    run = _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])
    assert run["status"] == "completed", run
    assert used["agent"]["id"] == chosen["id"]
    assert run["agent_name"] == "review agent"
    # The agent's role shapes the prompt, and the machine contract still comes last.
    assert "You are the Analytics agent" in used["system_prompt"]
    assert "JSON schema" in used["system_prompt"]
    prompt = used["system_prompt"]
    assert prompt.index("Analytics agent") < prompt.index("JSON schema")


def test_generation_refuses_an_agent_that_cannot_reach_a_model(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    disabled = _agent_named(api, "paused agent", enabled=False)
    a2a = _agent_named(api, "a2a agent", connection_type="a2a")
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    refused = api.post(
        f"{_base(board, loop)}/generation-runs",
        json={"purpose": "analysis", "agent_id": disabled["id"]},
    )
    assert refused.status_code in {422, 503}, refused.text
    assert "Agent is disabled" in refused.text, refused.text

    # An A2A agent speaks a transport the runtime can execute, so it must generate like any other
    # agent instead of being refused at selection.
    used: list[str] = []

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        used.append(str(agent_row["connection_type"]))
        return {
            "ok": True,
            "error": None,
            "text": "```json\n" + _analysis_json() + "\n```",
            "model": "test-model",
            "usage": {"total_tokens": 5},
        }

    monkeypatch.setattr(runtime, "call_completion", fake_call)
    started = api.data(
        api.post(
            f"{_base(board, loop)}/generation-runs",
            json={"purpose": "analysis", "agent_id": a2a["id"]},
        )
    )
    run = _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])
    assert run["status"] == "completed", run
    assert used == ["a2a"]
