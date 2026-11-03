"""Interaction agent access: a person's own token, owned, limited and revocable by an admin."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import Api
from fastapi.testclient import TestClient

MEMBER_SCOPES = [
    "boards:read",
    "cards:read",
    "cards:write",
    "comments:write",
    "loops:read",
    "loops:write",
    "loops:generate",
    "history:read",
    "discussions:read",
    "discussions:write",
]


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("tralala_csrf") or ""}


@pytest.fixture()
def visitor(client: TestClient) -> TestClient:
    """A second browser on the same application, so admin and member sessions coexist.

    It is deliberately not entered as a context manager: the lifespan that initialises the data
    directory already ran for the shared client, and running it twice would take the process lock.
    """
    return TestClient(client.app)


def _create_user(api: Api, name: str, *, role: str = "member") -> dict[str, Any]:
    return api.data(
        api.post(
            "/api/v1/users",
            json={"name": name, "password": f"{name}-password-1", "role": role},
        )
    )


def _sign_in(client: TestClient, name: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login", json={"username": name, "password": f"{name}-password-1"}
    )
    assert response.status_code == 200, response.text


def _issue(client: TestClient, name: str, scopes: list[str], **extra: Any) -> Any:
    return client.post(
        "/api/v1/credentials",
        json={"name": name, "scopes": scopes, **extra},
        headers=_csrf(client),
    )


def test_a_member_token_works_through_mcp(
    api: Api, client: TestClient, visitor: TestClient
) -> None:
    _create_user(api, "ada")
    board = api.data(api.post("/api/v1/boards", json={"name": "Shared board"}))
    _sign_in(visitor, "ada")
    created = _issue(visitor, "ada desktop", MEMBER_SCOPES)
    assert created.status_code == 201, created.text
    token = created.json()["data"]["token"]

    headers = {"Authorization": f"Bearer {token}"}
    tools = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=headers,
    )
    assert tools.status_code == 200
    names = {tool["name"] for tool in tools.json()["result"]["tools"]}
    assert {"read_board", "create_loop", "write_info", "ask_agents"} <= names

    read = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "read_board", "arguments": {"board_id": board["id"]}},
        },
        headers=headers,
    )
    assert read.status_code == 200
    assert read.json()["result"]["isError"] is False


def test_a_member_cannot_hold_administration_scopes(
    api: Api, visitor: TestClient
) -> None:
    _create_user(api, "bea")
    _sign_in(visitor, "bea")
    # Grantable in general, but outside the member vocabulary.
    for scope in ("boards:write", "boards:admin"):
        response = _issue(visitor, f"bad {scope}", [scope])
        assert response.status_code == 422, scope
        assert response.json()["error"]["code"] == "forbidden_scope", scope
    # Never grantable to any token, so the schema refuses them before policy runs.
    for scope in ("users:admin", "agents:write", "credentials:admin"):
        response = _issue(visitor, f"bad {scope}", [scope])
        assert response.status_code == 422, scope
        assert response.json()["error"]["code"] == "validation_failed", scope


def test_a_member_token_needs_an_expiry(api: Api, visitor: TestClient) -> None:
    _create_user(api, "cleo")
    _sign_in(visitor, "cleo")
    response = _issue(visitor, "forever", MEMBER_SCOPES, expires_in_days=0)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "expiry_required"
    capped = _issue(visitor, "long", MEMBER_SCOPES, expires_in_days=5000)
    assert capped.status_code == 422  # rejected by the schema bound before any policy runs


def test_a_member_may_not_exceed_the_live_token_limit(
    api: Api, visitor: TestClient, settings: Any
) -> None:
    _create_user(api, "dana")
    _sign_in(visitor, "dana")
    limit = int(settings.member_token_limit)
    for index in range(limit):
        assert _issue(visitor, f"agent {index}", MEMBER_SCOPES).status_code == 201
    blocked = _issue(visitor, "one more", MEMBER_SCOPES)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "agent_access_limit"


def test_mine_lists_only_my_own_access(
    api: Api, client: TestClient, visitor: TestClient
) -> None:
    _create_user(api, "eli")
    _create_user(api, "finn")
    _sign_in(visitor, "eli")
    _issue(visitor, "eli desktop", MEMBER_SCOPES)
    _sign_in(visitor, "finn")
    _issue(visitor, "finn desktop", MEMBER_SCOPES)

    mine = visitor.get("/api/v1/credentials/mine")
    assert mine.status_code == 200
    assert [entry["name"] for entry in mine.json()["data"]] == ["finn desktop"]

    everything = api.data(api.get("/api/v1/credentials"))
    assert {entry["name"] for entry in everything} == {"eli desktop", "finn desktop"}


def test_an_owner_can_rotate_and_revoke_but_not_touch_another_token(
    api: Api, visitor: TestClient
) -> None:
    _create_user(api, "gina")
    _create_user(api, "hugo")
    _sign_in(visitor, "gina")
    gina_token = _issue(visitor, "gina desktop", MEMBER_SCOPES).json()["data"]
    _sign_in(visitor, "hugo")
    hugo_token = _issue(visitor, "hugo desktop", MEMBER_SCOPES).json()["data"]

    stolen = visitor.post(
        f"/api/v1/credentials/{gina_token['id']}/revoke", headers=_csrf(visitor)
    )
    assert stolen.status_code == 404
    rotated = visitor.post(
        f"/api/v1/credentials/{hugo_token['id']}/rotate", headers=_csrf(visitor)
    )
    assert rotated.status_code == 201
    rotated_body = rotated.json()["data"]
    assert rotated_body["owner_actor_id"] == hugo_token["owner_actor_id"]
    assert rotated_body["token"] != hugo_token["token"]

    old = visitor.get(
        "/api/v1/boards", headers={"Authorization": f"Bearer {hugo_token['token']}"}
    )
    assert old.status_code == 401


def test_admin_sees_the_key_count_and_disabling_revokes_the_access(
    api: Api, client: TestClient, visitor: TestClient
) -> None:
    user = _create_user(api, "iris")
    _sign_in(visitor, "iris")
    issued = _issue(visitor, "iris desktop", MEMBER_SCOPES).json()["data"]

    listed = {entry["name"]: entry for entry in api.data(api.get("/api/v1/users"))}
    assert listed["iris"]["agent_access_count"] == 1
    assert listed["admin"]["agent_access_count"] == 0

    api.data(api.patch(f"/api/v1/users/{user['id']}", json={"disabled": True}))
    headers = {"Authorization": f"Bearer {issued['token']}"}
    assert client.get("/api/v1/boards", headers=headers).status_code == 401

    listed_after = {entry["name"]: entry for entry in api.data(api.get("/api/v1/users"))}
    assert listed_after["iris"]["agent_access_count"] == 0

    # Re-enabling the account does not resurrect a token that was revoked with it.
    api.data(api.patch(f"/api/v1/users/{user['id']}", json={"disabled": False}))
    assert client.get("/api/v1/boards", headers=headers).status_code == 401


def test_meta_publishes_the_member_vocabulary(api: Api, client: TestClient) -> None:
    meta = api.data(api.get("/api/v1/meta"))
    assert meta["member_token_scopes"]
    assert "boards:write" not in meta["member_token_scopes"]
    assert meta["member_token_limits"]["live"] >= 1
    assert meta["can_issue_tokens"] is True
