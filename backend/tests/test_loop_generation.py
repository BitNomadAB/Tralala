"""Generation runs: bounded output, validated promotion, failure and recovery."""

from __future__ import annotations

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
    recovered = services.loop_generation.recover(board["id"])
    assert recovered >= 1
    run = api.data(api.get(f"{_base(board, loop)}/generation-runs/{started['id']}"))
    assert run["status"] == "failed"
    assert run["error_code"] == "interrupted"
