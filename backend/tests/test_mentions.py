from __future__ import annotations

import json
import queue
import time
from typing import Any

from conftest import Api, loop_id

from app.services import runtime
from app.services.mentions import extract_mentions

MENTION_AGENTS = [
    {"id": "a1", "name": "Review Bot"},
    {"id": "a2", "name": "Review"},
    {"id": "a3", "name": "Oddy Qwen Coder"},
]


def test_mention_parser_resolves_names_without_swallowing_words() -> None:
    found = extract_mentions(
        "@[Oddy Qwen Coder] and @Review, not reviewer@Review.example or @Reviewer",
        MENTION_AGENTS,
    )
    assert [agent["name"] for agent in found] == ["Oddy Qwen Coder", "Review"]
    assert extract_mentions("@Review and @[Review]", MENTION_AGENTS) == MENTION_AGENTS[1:2]


def _services(api: Api) -> Any:
    return api.client.app.state.services  # type: ignore[attr-defined]


def _agent(api: Api, name: str, *, enabled: bool = True) -> dict[str, Any]:
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
                "enabled": enabled,
            },
        )
    )


def _card(api: Api, board: dict[str, Any], title: str = "Mention host") -> dict[str, Any]:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={
                "list_id": lists[0]["id"],
                "title": title,
                "description": "The checkout retries forever under load.",
                "priority": "high",
            },
        )
    )


def _urls(api: Api, board: dict[str, Any], card: dict[str, Any]) -> str:
    return f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/{card['id']}"


def _jobs(api: Api, board: dict[str, Any], card: dict[str, Any]) -> list[dict[str, Any]]:
    return api.data(api.get(f"{_urls(api, board, card)}/mentions"))


def _wait_job(
    api: Api,
    board: dict[str, Any],
    card: dict[str, Any],
    *,
    count: int = 1,
    statuses: tuple[str, ...] = ("completed", "failed"),
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    latest: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        latest = _jobs(api, board, card)
        if len(latest) >= count and all(job["status"] in statuses for job in latest):
            return latest
        time.sleep(0.05)
    raise AssertionError(f"Mention jobs never settled: {latest}")


def _answer(text: str = "Raise the retry budget and cap backoff. AGREE"):
    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        return {
            "ok": True,
            "error": None,
            "text": text,
            "verdict": "agree",
            "justification": "because",
            "model": "test-model",
            "usage": {"total_tokens": 41},
        }

    return call


def test_mentioned_agent_answers_in_the_ticket_thread(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Thread Bot")
    card = _card(api, board)
    monkeypatch.setattr(runtime, "call_agent", _answer())

    response = api.post(
        f"{_urls(api, board, card)}/comments",
        json={"content": f"@{agent['name']} can you look at the retry storm?"},
    )
    human = api.data(response)
    assert human["actor_type"] == "user"

    jobs = _wait_job(api, board, card)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["status"] == "completed"
    assert job["agent_id"] == agent["id"]
    assert job["agent_name"] == agent["name"]
    assert job["response_comment_id"]
    assert job["tokens_used"] == 41
    assert job["comment_id"] == human["id"]
    assert job["can_retry"] is False

    comments = api.data(api.get(f"{_urls(api, board, card)}/comments"))
    assert [comment["id"] for comment in comments] == [human["id"], job["response_comment_id"]]
    reply = comments[-1]
    assert reply["actor_id"] == agent["id"]
    assert reply["actor_name"] == agent["name"]
    assert reply["actor_type"] == "agent"


def test_context_contains_ticket_labels_checklists_and_recent_comments(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Context Bot")
    card = _card(api, board, "Checkout retry storm")
    label = api.data(api.post(f"/api/v1/boards/{board['id']}/labels", json={"name": "reliability"}))
    api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/{card['id']}",
            json={"version": card["version"], "labels": [label["id"]]},
        )
    )
    checklist = api.data(
        api.post(f"{_urls(api, board, card)}/checklists", json={"title": "Acceptance"})
    )
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/checklists/{checklist['id']}/items",
            json={"text": "Backoff is capped"},
        )
    )
    api.data(
        api.post(f"{_urls(api, board, card)}/comments", json={"content": "Earlier human note"})
    )
    api.post(
        f"/api/v1/boards/{board['id']}/attachments",
        params={"card_id": card["id"], "filename": "trace.txt"},
        content=b"stack trace",
        headers={"Content-Type": "text/plain"},
    )

    captured: dict[str, Any] = {}

    def capture(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        captured["system_prompt"] = system_prompt
        captured["messages"] = messages
        return _answer("Use exponential backoff. AGREE")(
            settings, agent_row, system_prompt=system_prompt, messages=messages
        )

    monkeypatch.setattr(runtime, "call_agent", capture)
    api.data(
        api.post(
            f"{_urls(api, board, card)}/comments",
            json={"content": f"@{agent['name']} what should we do?"},
        )
    )
    _wait_job(api, board, card)

    prompt = captured["messages"][0]["content"]
    assert "Ticket: Checkout retry storm" in prompt
    assert "Loop: " in prompt
    assert f"Ticket id: {card['id']}" in prompt
    assert "The checkout retries forever under load." in prompt
    assert "Priority: high" in prompt
    assert "Labels: reliability" in prompt
    assert "- Acceptance: [ ] Backoff is capped" in prompt
    assert "Earlier human note" in prompt
    assert "trace.txt (text/plain" in prompt
    assert f"@{agent['name']} what should we do?" in prompt
    assert "QA Engineer" in captured["system_prompt"]


def test_a_failed_mention_is_retried_without_duplicating_the_comment(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Retry Bot")
    card = _card(api, board)
    calls = {"n": 0}

    def flaky(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "error": "ConnectError", "text": ""}
        return _answer("Second attempt works. AGREE")(
            settings, agent_row, system_prompt=system_prompt, messages=messages
        )

    monkeypatch.setattr(runtime, "call_agent", flaky)
    human = api.data(
        api.post(
            f"{_urls(api, board, card)}/comments",
            json={"content": f"@{agent['name']} ping"},
        )
    )
    failed = _wait_job(api, board, card)[0]
    assert failed["status"] == "failed"
    assert failed["error"] == "ConnectError"
    assert failed["can_retry"] is True
    assert failed["response_comment_id"] is None
    assert len(api.data(api.get(f"{_urls(api, board, card)}/comments"))) == 1

    retried = api.data(api.post(f"{_urls(api, board, card)}/mentions/{failed['id']}/retry"))
    assert retried["status"] in ("queued", "running", "completed")
    completed = _wait_job(api, board, card)[0]
    assert completed["status"] == "completed"
    assert completed["attempts"] == 2
    assert completed["id"] == failed["id"]

    comments = api.data(api.get(f"{_urls(api, board, card)}/comments"))
    assert [comment["id"] for comment in comments] == [
        human["id"],
        completed["response_comment_id"],
    ]

    again = api.post(f"{_urls(api, board, card)}/mentions/{failed['id']}/retry")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"
    assert len(api.data(api.get(f"{_urls(api, board, card)}/comments"))) == 2


def test_disabled_agents_and_unknown_names_are_ignored(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Sleeping Bot", enabled=False)
    card = _card(api, board)
    monkeypatch.setattr(runtime, "call_agent", _answer())
    api.data(
        api.post(
            f"{_urls(api, board, card)}/comments",
            json={"content": f"@{agent['name']} and @Nobody are not here"},
        )
    )
    time.sleep(0.2)
    assert _jobs(api, board, card) == []
    assert len(api.data(api.get(f"{_urls(api, board, card)}/comments"))) == 1


def test_mention_events_are_published_stored_and_streamed(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Event Mention Bot")
    card = _card(api, board)
    monkeypatch.setattr(runtime, "call_agent", _answer("Events are fine. AGREE"))
    events = _services(api).event
    listener = events.subscribe_card(board["id"], card["id"])
    try:
        api.data(
            api.post(
                f"{_urls(api, board, card)}/comments",
                json={"content": f"@{agent['name']} say hi"},
            )
        )
        _wait_job(api, board, card)
        published: list[dict[str, Any]] = []
        while True:
            try:
                published.append(listener.get_nowait())
            except queue.Empty:
                break
    finally:
        events.unsubscribe_card(board["id"], card["id"], listener)

    assert [event["type"] for event in published] == ["agent_started", "agent_completed"]
    completed = published[-1]
    assert completed["card_id"] == card["id"]
    assert completed["payload"]["agent_name"] == agent["name"]
    # Events carry ids and counters only; the client refetches the comment itself.
    assert "content" not in completed["payload"]
    assert completed["payload"]["response_comment_id"]
    assert set(completed["payload"]) == {
        "job_id",
        "comment_id",
        "agent_id",
        "agent_name",
        "response_comment_id",
        "tokens_used",
        "duration_ms",
    }

    stored = api.data(api.get(f"{_urls(api, board, card)}/events/history"))
    assert [item["seq"] for item in stored["items"]] == [event["seq"] for event in published]

    with api.client.stream("GET", f"{_urls(api, board, card)}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines: list[str] = []
        seen = False
        for line in response.iter_lines():
            lines.append(line)
            if "event: agent_completed" in line:
                seen = True
            if seen and line == "":
                break
    assert any(line.startswith("id: ") for line in lines)
    payload = next(
        line for line in lines if line.startswith("data: ") and '"type": "agent_completed"' in line
    )
    assert json.loads(payload[len("data: ") :])["payload"]["agent_name"] == agent["name"]


def test_mention_endpoints_validate_the_card(api: Api, board: dict[str, Any]) -> None:
    base = f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/does-not-exist"
    assert api.get(f"{base}/mentions").status_code == 404
    assert api.get(f"{base}/events/history").status_code == 404
    assert api.client.get(f"{base}/events").status_code == 404
