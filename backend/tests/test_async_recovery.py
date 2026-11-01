from __future__ import annotations

import time
import uuid
from typing import Any

from conftest import Api, loop_id
from sqlalchemy import text

from app.services import runtime


def _board_id(value: Any) -> str:
    return value["id"] if isinstance(value, dict) else value


def _cards(api: Api, board: Any, suffix: str = "") -> str:
    identifier = _board_id(board)
    path = f"/api/v1/boards/{identifier}/loops/{loop_id(api, identifier)}/cards"
    return f"{path}{suffix}"


def _lists(api: Api, board: Any, suffix: str = "") -> str:
    identifier = _board_id(board)
    path = f"/api/v1/boards/{identifier}/loops/{loop_id(api, identifier)}/lists"
    return f"{path}{suffix}"


def _services(api: Api) -> Any:
    return api.client.app.state.services  # type: ignore[attr-defined]


def _agent(api: Api, name: str) -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == "qa_engineer")
    return api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": name,
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "role_template_id": role["id"],
            },
        )
    )


def _card(api: Api, board: dict[str, Any]) -> dict[str, Any]:
    lists = api.data(api.get(f"{_lists(api, board['id'])}"))
    return api.data(
        api.post(
            f"{_cards(api, board['id'])}",
            json={"list_id": lists[0]["id"], "title": "Recovery host"},
        )
    )


def _discussion(api: Api, board: dict[str, Any], agent: dict[str, Any]) -> dict[str, Any]:
    card = _card(api, board)
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions",
            json={
                "card_id": card["id"],
                "goal": "Will this survive a restart?",
                "participant_ids": [agent["id"]],
            },
        )
    )


def _answer(text: str = "Recovered and answering. AGREE"):
    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        return {
            "ok": True,
            "error": None,
            "text": text,
            "verdict": "agree",
            "justification": "because",
            "model": "test-model",
            "usage": {"total_tokens": 7},
        }

    return call


def _wait_job(api: Api, board: dict[str, Any], card_id: str, job_id: str) -> dict[str, Any]:
    url = f"{_cards(api, board['id'])}/{card_id}/mentions"
    deadline = time.monotonic() + 10
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        jobs = api.data(api.get(url))
        latest = next((job for job in jobs if job["id"] == job_id), {})
        if latest.get("status") in ("completed", "failed"):
            return latest
        time.sleep(0.05)
    raise AssertionError(f"Job never settled: {latest}")


def test_restart_recovery_frees_a_run_and_marks_it_explicitly(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Recovery Run Bot")
    discussion = _discussion(api, board, agent)
    services = _services(api)
    run_id = str(uuid.uuid4())
    base = f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"
    with services.boards.session(board["id"]) as conn:
        conn.execute(
            text(
                "INSERT INTO discussion_runs"
                " (id, discussion_id, status, autonomy, rounds_requested, rounds_completed,"
                "  tokens_used, elapsed_ms, started_by_actor_id, started_by_type, started_by_name,"
                "  created_at, started_at)"
                " VALUES (:id, :discussion, 'paused', 1, 3, 1, 0, 0, 'actor', 'user', 'admin',"
                "         :now, :now)"
            ),
            {"id": run_id, "discussion": discussion["id"], "now": discussion["created_at"]},
        )
        conn.execute(
            text("UPDATE discussion_threads SET run_state = 'paused' WHERE id = :id"),
            {"id": discussion["id"]},
        )

    assert api.post(f"{base}/runs", json={}).status_code == 409

    assert services.run.recover(board["id"]) == 1
    detail = api.data(api.get(base))
    assert detail["run_state"] == "idle"
    run = next(entry for entry in detail["runs"] if entry["id"] == run_id)
    assert run["status"] == "failed"
    assert run["stop_reason"] == "process_restart"
    assert run["error"] == "process_restart"

    monkeypatch.setattr(runtime, "call_agent", _answer())
    started = api.post(f"{base}/runs", json={})
    assert started.status_code == 202, started.text


def test_restart_recovery_resolves_mention_jobs(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Recovery Mention Bot")
    card = _card(api, board)
    services = _services(api)
    human = api.data(
        api.post(
            f"{_cards(api, board['id'])}/{card['id']}/comments",
            json={"content": "No mention here, just the source comment"},
        )
    )
    queued_source = api.data(
        api.post(
            f"{_cards(api, board['id'])}/{card['id']}/comments",
            json={"content": "Another source comment"},
        )
    )
    running_id = str(uuid.uuid4())
    queued_id = str(uuid.uuid4())
    now = "2026-10-30T12:00:00Z"
    insert = text(
        "INSERT INTO comment_mention_jobs"
        " (id, card_id, comment_id, agent_id, agent_name, status, attempts,"
        "  role_snapshot_json, tokens_used, requested_by_actor_id, requested_by_type,"
        "  requested_by_name, created_at, started_at)"
        " VALUES (:id, :card, :comment, :agent, :name, :status, :attempts, '{}', 0,"
        "         'actor', 'user', 'admin', :now, :started)"
    )
    with services.boards.session(board["id"]) as conn:
        conn.execute(
            insert,
            {
                "id": running_id,
                "card": card["id"],
                "comment": human["id"],
                "agent": agent["id"],
                "name": agent["name"],
                "status": "running",
                "attempts": 1,
                "now": now,
                "started": now,
            },
        )
        conn.execute(
            insert,
            {
                "id": queued_id,
                "card": card["id"],
                "comment": queued_source["id"],
                "agent": agent["id"],
                "name": agent["name"],
                "status": "queued",
                "attempts": 0,
                "now": now,
                "started": None,
            },
        )

    monkeypatch.setattr(runtime, "call_agent", _answer())
    assert services.mention.recover(board["id"]) == 2

    interrupted = api.data(api.get(f"{_cards(api, board['id'])}/{card['id']}/mentions"))
    failed = next(job for job in interrupted if job["id"] == running_id)
    assert failed["status"] == "failed"
    assert failed["error"] == "process_restart"
    assert failed["can_retry"] is True

    resumed = _wait_job(api, board, card["id"], queued_id)
    assert resumed["status"] == "completed"
    assert resumed["attempts"] == 1

    retried = api.data(
        api.post(f"{_cards(api, board['id'])}/{card['id']}/mentions/{running_id}/retry")
    )
    assert retried["status"] in ("queued", "running", "completed")
    completed = _wait_job(api, board, card["id"], running_id)
    assert completed["status"] == "completed"
    assert completed["attempts"] == 2

    comments = api.data(api.get(f"{_cards(api, board['id'])}/{card['id']}/comments"))
    assert [comment["id"] for comment in comments[:2]] == [human["id"], queued_source["id"]]
    assert len(comments) == 4
    assert all(comment["actor_type"] == "agent" for comment in comments[2:])
