"""Board agent membership: a board lists its agents, and generation stays inside that list."""

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
        '{"schema_version":1,"outcome":"Verify email","scope":["mail"],'
        '"findings":[{"id":"F-01","title":"Nothing exists","category":"change",'
        '"technical_detail":"detail","plain_language":"This must be built from scratch."}],'
        '"assumptions":[],"open_questions":[],"options":[],'
        '"recommendation":"Pick a provider","verification":["sign-in blocked"],'
        '"sources":[],"repository_revision":""}'
    )


def _wait_run(api: Api, url: str, run_id: str) -> dict[str, Any]:
    for _ in range(100):
        run = api.data(api.get(f"{url}/{run_id}"))
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("generation run did not finish")


def test_a_board_selects_the_agents_that_work_on_it(api: Api) -> None:
    first = _agent(api, "alpha agent")
    second = _agent(api, "beta agent")
    board = api.data(
        api.post(
            "/api/v1/boards",
            json={"name": "Staffed board", "agent_ids": [first["id"], second["id"]]},
        )
    )
    assert set(board["agent_ids"]) == {first["id"], second["id"]}

    listed = api.data(api.get("/api/v1/boards"))
    entry = next(item for item in listed if item["id"] == board["id"])
    assert set(entry["agent_ids"]) == {first["id"], second["id"]}


def test_editing_a_board_replaces_its_agent_selection(api: Api, board: dict[str, Any]) -> None:
    first = _agent(api, "alpha agent")
    second = _agent(api, "beta agent")
    api.data(api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": [first["id"]]}))

    kept = api.data(api.patch(f"/api/v1/boards/{board['id']}", json={"description": "Only text"}))
    assert kept["agent_ids"] == [first["id"]]

    replaced = api.data(
        api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": [second["id"]]})
    )
    assert replaced["agent_ids"] == [second["id"]]

    cleared = api.data(api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": []}))
    assert cleared["agent_ids"] == []


def test_one_agent_may_work_on_two_boards(api: Api) -> None:
    shared = _agent(api, "shared agent")
    for name in ("First board", "Second board"):
        board = api.data(
            api.post("/api/v1/boards", json={"name": name, "agent_ids": [shared["id"]]})
        )
        assert board["agent_ids"] == [shared["id"]]


def test_an_unknown_agent_cannot_be_selected(api: Api) -> None:
    missing = "0f0f0f0f-0000-0000-0000-000000000000"
    response = api.post("/api/v1/boards", json={"name": "Broken", "agent_ids": [missing]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "agent_not_found"
    assert api.data(api.get("/api/v1/boards")) == []

    board = api.data(api.post("/api/v1/boards", json={"name": "Kept"}))
    rejected = api.patch(
        f"/api/v1/boards/{board['id']}",
        json={"name": "Renamed", "agent_ids": [missing]},
    )
    assert rejected.status_code == 404
    unchanged = api.data(api.get(f"/api/v1/boards/{board['id']}"))
    assert unchanged["name"] == "Kept"
    assert unchanged["agent_ids"] == []


def test_deleting_an_agent_detaches_it_from_boards(api: Api) -> None:
    agent = _agent(api, "temporary agent")
    board = api.data(
        api.post("/api/v1/boards", json={"name": "Detach board", "agent_ids": [agent["id"]]})
    )
    api.data(api.delete(f"/api/v1/agents/{agent['id']}"))
    refreshed = api.data(api.get(f"/api/v1/boards/{board['id']}"))
    assert refreshed["agent_ids"] == []


def test_generation_refuses_an_agent_the_board_does_not_list(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    listed = _agent(api, "listed agent")
    outsider = _agent(api, "outsider agent")
    api.data(api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": [listed["id"]]}))
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))

    response = api.post(
        f"{_base(board, loop)}/generation-runs",
        json={"purpose": "analysis", "agent_id": outsider["id"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "agent_not_on_board"


def test_the_default_agent_is_one_the_board_lists(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent(api, "aaa first by name")
    chosen = _agent(api, "zzz still on the board")
    api.data(api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": [chosen["id"]]}))
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
    assert used["agent"]["id"] == chosen["id"]


def test_a_board_without_agents_keeps_any_enabled_generator(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    only = _agent(api, "only agent")
    assert board["agent_ids"] == []
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
    assert used["agent"]["id"] == only["id"]


def test_a_disabled_board_agent_is_still_reported_as_disabled(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    agent = _agent(api, "paused agent")
    api.data(api.patch(f"/api/v1/boards/{board['id']}", json={"agent_ids": [agent["id"]]}))
    api.data(api.patch(f"/api/v1/agents/{agent['id']}", json={"enabled": False}))
    api.data(api.put(f"{_base(board, loop)}/documents/info", json={"content": "Intent"}))

    response = api.post(
        f"{_base(board, loop)}/generation-runs",
        json={"purpose": "analysis", "agent_id": agent["id"]},
    )
    assert response.status_code == 422, response.text
    assert "disabled" in response.text.lower()
