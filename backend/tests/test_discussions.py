from __future__ import annotations

from typing import Any

from conftest import Api
from sqlalchemy import text


def _ticket(api: Api, board: dict[str, Any]) -> dict[str, Any]:
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={"list_id": lists[0]["id"], "title": "Auth review"},
        )
    )


def _agent(api: Api, name: str = "Forum Bot") -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == "security_engineer")
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


def test_create_discussion_snapshots_participant_roles(api: Api, board: dict[str, Any]) -> None:
    ticket = _ticket(api, board)
    agent = _agent(api)
    discussion = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions",
            json={
                "card_id": ticket["id"],
                "goal": "Which session strategy is safest?",
                "participant_ids": [agent["id"]],
            },
        )
    )
    assert discussion["card_id"] == ticket["id"]
    assert discussion["status"] == "open"
    assert discussion["card_title"] == "Auth review"
    assert discussion["participant_count"] == 1
    assert discussion["message_count"] == 1
    participant = discussion["participants"][0]
    assert participant["role_template_name"] == "Security Engineer"
    assert participant["system_prompt_sha256"]

    roles = api.data(api.get("/api/v1/role-templates"))
    security = next(entry for entry in roles if entry["builtin_key"] == "security_engineer")
    api.data(
        api.patch(
            f"/api/v1/role-templates/{security['id']}",
            json={"system_prompt": "Rewritten after the discussion started."},
        )
    )
    reloaded = api.data(api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"))
    snapshot = reloaded["participants"][0]
    assert snapshot["system_prompt_sha256"] == participant["system_prompt_sha256"]


def test_discussion_requires_existing_ticket(api: Api, board: dict[str, Any]) -> None:
    response = api.post(
        f"/api/v1/boards/{board['id']}/discussions",
        json={"card_id": "does-not-exist", "goal": "Orphan discussion"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_messages_are_threaded_and_listed(api: Api, board: dict[str, Any]) -> None:
    ticket = _ticket(api, board)
    discussion = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions",
            json={"card_id": ticket["id"], "goal": "Is CSRF protection sufficient?"},
        )
    )
    root_message = discussion["messages"][0]
    updated = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/messages",
            json={"content": "Follow-up question", "parent_message_id": root_message["id"]},
        )
    )
    assert updated["status"] == "discussing"
    assert len(updated["messages"]) == 2
    assert updated["messages"][1]["parent_message_id"] == root_message["id"]

    listing = api.data(api.get(f"/api/v1/boards/{board['id']}/discussions"))
    assert [item["id"] for item in listing["items"]] == [discussion["id"]]
    assert listing["items"][0]["message_count"] == 2


def test_discussions_require_auth(client: Any) -> None:
    board_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/boards/{board_id}/discussions").status_code == 401


def _set_activity(api: Api, board_id: str, value: str) -> None:
    services = api.client.app.state.services  # type: ignore[attr-defined]
    with services.boards.session(board_id) as conn:
        conn.execute(
            text("UPDATE discussion_threads SET last_activity_at = :value"),
            {"value": value},
        )


def test_board_overview_orders_boards_by_newest_discussion_activity(
    api: Api, board: dict[str, Any]
) -> None:
    other = api.data(api.post("/api/v1/boards", json={"name": "Second board"}))
    empty = api.data(api.post("/api/v1/boards", json={"name": "Empty board"}))
    for target in (board, other):
        ticket = _ticket(api, target)
        api.data(
            api.post(
                f"/api/v1/boards/{target['id']}/discussions",
                json={"card_id": ticket["id"], "goal": "Where does this board rank?"},
            )
        )

    _set_activity(api, board["id"], "2026-01-01T00:00:00Z")
    _set_activity(api, other["id"], "2026-02-01T00:00:00Z")

    overview = api.data(api.get("/api/v1/discussions/overview"))
    assert [entry["board_id"] for entry in overview["items"]] == [
        other["id"],
        board["id"],
        empty["id"],
    ]
    assert overview["total"] == 3
    latest = overview["items"][0]
    assert latest["board_name"] == "Second board"
    assert latest["last_activity_at"] == "2026-02-01T00:00:00Z"
    assert latest["discussion_count"] == 1
    assert latest["open_count"] == 1
    assert latest["status"] == "active"
    assert overview["items"][2]["last_activity_at"] is None
    assert overview["items"][2]["discussion_count"] == 0

    # New activity in the first board moves it to the top without touching the others.
    _set_activity(api, board["id"], "2026-03-01T00:00:00Z")
    overview = api.data(api.get("/api/v1/discussions/overview"))
    assert [entry["board_id"] for entry in overview["items"]][:2] == [board["id"], other["id"]]


def test_overview_requires_auth(client: Any) -> None:
    assert client.get("/api/v1/discussions/overview").status_code == 401


def _token(api: Api, scopes: list[str]) -> str:
    issued = api.data(
        api.post(
            "/api/v1/credentials",
            json={"name": "overview-token", "scopes": scopes, "expires_in_days": 1},
        )
    )
    return str(issued["token"])


def test_overview_requires_discussion_scope_for_tokens(api: Api, client: Any) -> None:
    # API tokens cannot be issued with discussion scopes today (see schemas/auth.py), so a token
    # holding only board access must still be refused.
    board_only = _token(api, ["boards:read"])
    denied = client.get(
        "/api/v1/discussions/overview",
        headers={"Authorization": f"Bearer {board_only}"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["details"]["required_scope"] == "discussions:read"

    allowed = client.get("/api/v1/discussions/overview")
    assert allowed.status_code == 200
