from __future__ import annotations

import json
import queue
from typing import Any

from conftest import Api

from app.services import runtime


def _services(api: Api) -> Any:
    return api.client.app.state.services  # type: ignore[attr-defined]


def _agent(api: Api, name: str = "Event Bot") -> dict[str, Any]:
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


def _discussion(
    api: Api, board: dict[str, Any], agent: dict[str, Any]
) -> dict[str, Any]:
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={"list_id": lists[0]["id"], "title": "Event source"},
        )
    )
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions",
            json={
                "card_id": card["id"],
                "goal": "Publish the round?",
                "participant_ids": [agent["id"]],
            },
        )
    )


def _answers(name: str, verdict: str):
    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        return {
            "ok": True,
            "error": None,
            "text": f"{name} answers {verdict.upper()}",
            "verdict": verdict,
            "justification": "because",
            "model": "test-model",
            "usage": {"total_tokens": 12},
        }

    return call


def _drain(listener: queue.Queue) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        try:
            events.append(listener.get_nowait())
        except queue.Empty:
            return events


def _base(board: dict[str, Any], discussion: dict[str, Any]) -> str:
    return f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"


def test_round_publishes_events_that_are_already_stored(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api)
    discussion = _discussion(api, board, agent)
    monkeypatch.setattr(runtime, "call_agent", _answers("Event Bot", "agree"))
    events = _services(api).event
    listener = events.subscribe(board["id"], discussion["id"])
    try:
        api.data(api.post(f"{_base(board, discussion)}/start", json={}))
        published = _drain(listener)
    finally:
        events.unsubscribe(board["id"], discussion["id"], listener)

    types = [event["type"] for event in published]
    assert types == [
        "run_started",
        "agent_started",
        "message_created",
        "vote_recorded",
        "agent_completed",
        "round_completed",
        "discussion_status_changed",
        "consensus_proposed",
        "run_finished",
        "discussion_status_changed",
    ], types
    message = next(event for event in published if event["type"] == "message_created")
    assert message["payload"]["content"] == "Event Bot answers AGREE"
    assert message["payload"]["position"] == "agree"
    assert message["payload"]["author_name"] == "Event Bot"
    assert message["actor_id"] is None

    # Everything that was published is readable from the log: publishing never runs ahead of it.
    stored = api.data(api.get(f"{_base(board, discussion)}/events/history"))
    assert [item["seq"] for item in stored["items"]] == [event["seq"] for event in published]
    assert stored["items"][0]["payload"]["rounds_requested"] == 1


def test_agent_failures_are_published_and_stored(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Broken Event Bot")
    discussion = _discussion(api, board, agent)

    def failing(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        return {"ok": False, "error": "ConnectError", "text": ""}

    monkeypatch.setattr(runtime, "call_agent", failing)
    events = _services(api).event
    listener = events.subscribe(board["id"], discussion["id"])
    try:
        result = api.data(api.post(f"{_base(board, discussion)}/start", json={}))
        published = _drain(listener)
    finally:
        events.unsubscribe(board["id"], discussion["id"], listener)

    assert result["run_status"] == "failed"
    failed = next(event for event in published if event["type"] == "agent_failed")
    assert failed["payload"]["error"] == "ConnectError"
    assert [event["type"] for event in published].count("message_created") == 0


def test_history_replays_only_events_after_a_sequence(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Replay Bot")
    discussion = _discussion(api, board, agent)
    monkeypatch.setattr(runtime, "call_agent", _answers("Replay Bot", "disagree"))

    first = api.data(api.post(f"{_base(board, discussion)}/start", json={}))
    api.data(api.post(f"{_base(board, discussion)}/start", json={}))
    assert first["rounds_completed"] == 1

    everything = api.data(api.get(f"{_base(board, discussion)}/events/history"))
    assert everything["total"] > 10

    checkpoint = everything["items"][0]["seq"]
    remaining = api.data(
        api.get(f"{_base(board, discussion)}/events/history?after={checkpoint}")
    )
    assert all(item["seq"] > checkpoint for item in remaining["items"])
    assert remaining["total"] == everything["total"] - 1


def test_human_activity_is_published(api: Api, board: dict[str, Any]) -> None:
    agent = _agent(api, "Human Event Bot")
    discussion = _discussion(api, board, agent)
    events = _services(api).event
    listener = events.subscribe(board["id"], discussion["id"])
    try:
        api.data(
            api.post(
                f"{_base(board, discussion)}/messages",
                json={"content": "A human note"},
            )
        )
        published = _drain(listener)
    finally:
        events.unsubscribe(board["id"], discussion["id"], listener)

    message = next(event for event in published if event["type"] == "message_created")
    assert message["payload"]["content"] == "A human note"
    assert message["payload"]["author_type"] == "user"


def test_stream_replays_stored_events_as_server_sent_events(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Stream Bot")
    discussion = _discussion(api, board, agent)
    monkeypatch.setattr(runtime, "call_agent", _answers("Stream Bot", "agree"))
    api.data(api.post(f"{_base(board, discussion)}/start", json={}))

    url = f"{_base(board, discussion)}/events"
    with api.client.stream("GET", url) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines: list[str] = []
        for line in response.iter_lines():
            lines.append(line)
            if line.startswith("data: ") and '"type": "message_created"' in line:
                break
            if len([entry for entry in lines if entry.startswith("event: ")]) >= 12:
                break

    assert any(line.startswith("id: ") for line in lines)
    assert "event: message_created" in lines
    payload = next(
        line
        for line in lines
        if line.startswith("data: ") and '"type": "message_created"' in line
    )
    event = json.loads(payload[len("data: ") :])
    assert event["type"] == "message_created"
    assert event["seq"] >= 1
    assert event["payload"]["content"] == "Stream Bot answers AGREE"


def test_event_endpoints_validate_the_thread(api: Api, board: dict[str, Any]) -> None:
    base = f"/api/v1/boards/{board['id']}/discussions/does-not-exist"
    assert api.get(f"{base}/events/history").status_code == 404
    assert api.client.get(f"{base}/events").status_code == 404
