"""Per-Loop agent preference: a stored default per purpose, never a grant."""

from __future__ import annotations

import time
from typing import Any

from conftest import Api

from app.services import runtime


def _agent(
    api: Api, name: str, *, role_key: str = "analytics_agent", enabled: bool = True
) -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == role_key)
    return api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": name,
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "model": f"{name}-model",
                "role_template_id": role["id"],
                "enabled": enabled,
            },
        )
    )


def _base(board: dict[str, Any], loop: dict[str, Any]) -> str:
    return f"/api/v1/boards/{board['id']}/loops/{loop['id']}"


def _analysis_json() -> str:
    return (
        '{"schema_version":1,"outcome":"Verify email","scope":[],'
        '"findings":[{"id":"F-01","title":"Nothing exists","category":"change",'
        '"technical_detail":"detail","plain_language":"Build it."}],'
        '"assumptions":[],"open_questions":[],"options":[],"recommendation":"Go",'
        '"verification":["blocked"],"sources":[],"repository_revision":""}'
    )


def _wait_run(api: Api, url: str, run_id: str) -> dict[str, Any]:
    for _ in range(100):
        run = api.data(api.get(f"{url}/{run_id}"))
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("generation run did not finish")


def test_a_loop_remembers_one_agent_per_purpose(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    analyst = _agent(api, "analyst")
    planner = _agent(api, "planner", role_key="project_manager")
    api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}",
            json={"agent_ids": [analyst["id"], planner["id"]]},
        )
    )

    saved = api.data(
        api.put(
            f"{_base(board, loop)}/agents",
            json={"analysis_agent_id": analyst["id"], "roadmap_agent_id": planner["id"]},
        )
    )
    assert saved["analysis_agent_id"] == analyst["id"]
    assert saved["roadmap_agent_id"] == planner["id"]
    assert saved["qa_agent_id"] is None

    fetched = api.data(api.get(f"{_base(board, loop)}/agents"))
    assert fetched == saved

    cleared = api.data(
        api.put(f"{_base(board, loop)}/agents", json={"analysis_agent_id": None})
    )
    assert cleared["analysis_agent_id"] is None
    assert cleared["roadmap_agent_id"] == planner["id"]


def test_a_preference_stays_inside_the_board(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    listed = _agent(api, "listed agent")
    outsider = _agent(api, "outsider agent")
    api.data(api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": [listed["id"]]}))

    rejected = api.put(
        f"{_base(board, loop)}/agents", json={"analysis_agent_id": outsider["id"]}
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "agent_not_on_board"

    unknown = api.put(
        f"{_base(board, loop)}/agents",
        json={"analysis_agent_id": "0f0f0f0f-0000-0000-0000-000000000000"},
    )
    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["error"]["code"] == "agent_not_found"

    assert api.data(api.get(f"{_base(board, loop)}/agents"))["analysis_agent_id"] is None


def test_a_loop_of_another_board_is_not_found(api: Api, board: dict[str, Any]) -> None:
    other = api.data(api.post("/api/v1/boards", json={"name": "Other board"}))
    loop = api.data(api.post(f"/api/v1/boards/{other['id']}/loops", json={"name": "Elsewhere"}))
    response = api.get(f"/api/v1/boards/{board['id']}/loops/{loop['id']}/agents")
    assert response.status_code == 404, response.text


def test_the_stored_preference_is_the_default_agent(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent(api, "aaa first by name")
    preferred = _agent(api, "zzz preferred")
    api.data(
        api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": [preferred["id"]]})
    )
    api.data(
        api.put(f"{_base(board, loop)}/agents", json={"analysis_agent_id": preferred["id"]})
    )
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    used: dict[str, Any] = {}

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        used["agent"] = agent_row
        return {"ok": True, "error": None, "text": _analysis_json(), "model": "m", "usage": {}}

    monkeypatch.setattr(runtime, "call_completion", fake_call)
    started = api.data(
        api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    assert _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])["status"] == (
        "completed"
    )
    assert used["agent"]["id"] == preferred["id"]


def test_an_explicit_agent_still_wins_over_the_preference(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    preferred = _agent(api, "preferred agent")
    other = _agent(api, "other agent")
    api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}",
            json={"agent_ids": [preferred["id"], other["id"]]},
        )
    )
    api.data(
        api.put(f"{_base(board, loop)}/agents", json={"analysis_agent_id": preferred["id"]})
    )
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    used: dict[str, Any] = {}

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        used["agent"] = agent_row
        return {"ok": True, "error": None, "text": _analysis_json(), "model": "m", "usage": {}}

    monkeypatch.setattr(runtime, "call_completion", fake_call)
    started = api.data(
        api.post(
            f"{_base(board, loop)}/generation-runs",
            json={"purpose": "analysis", "agent_id": other["id"]},
        )
    )
    assert _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])["status"] == (
        "completed"
    )
    assert used["agent"]["id"] == other["id"]


def test_a_preference_for_a_deleted_agent_falls_back(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    doomed = _agent(api, "doomed agent")
    survivor = _agent(api, "survivor agent")
    api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}",
            json={"agent_ids": [doomed["id"], survivor["id"]]},
        )
    )
    api.data(api.put(f"{_base(board, loop)}/agents", json={"analysis_agent_id": doomed["id"]}))
    api.data(api.delete(f"/api/v1/agents/{doomed['id']}"))
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))
    used: dict[str, Any] = {}

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        used["agent"] = agent_row
        return {"ok": True, "error": None, "text": _analysis_json(), "model": "m", "usage": {}}

    monkeypatch.setattr(runtime, "call_completion", fake_call)
    started = api.data(
        api.post(f"{_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    run = _wait_run(api, f"{_base(board, loop)}/generation-runs", started["id"])
    assert run["status"] == "completed", run
    assert used["agent"]["id"] == survivor["id"]


def test_writing_a_preference_needs_board_write(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    agent = _agent(api, "agent")
    credential = api.data(
        api.post(
            "/api/v1/credentials",
            json={
                "name": "analyst agent",
                "scopes": ["boards:read", "loops:read", "loops:generate"],
            },
        )
    )
    headers = {"Authorization": f"Bearer {credential['token']}"}
    response = api.client.put(
        f"{_base(board, loop)}/agents",
        json={"analysis_agent_id": agent["id"]},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["details"]["required_scope"] == "boards:write"
