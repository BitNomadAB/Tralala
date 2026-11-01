from __future__ import annotations

from typing import Any

import pytest
from conftest import Api, loop_id
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _issue_token(api: Api, scopes: list[str]) -> str:
    response = api.post(
        "/api/v1/credentials", json={"name": "agent-1", "scopes": scopes, "expires_in_days": 30}
    )
    return api.data(response)["token"]


def test_agent_scopes_are_enforced(api: Api, client: TestClient, board: dict[str, Any]) -> None:
    token = _issue_token(api, ["boards:read"])
    headers = {"Authorization": f"Bearer {token}"}
    boards = client.get("/api/v1/boards", headers=headers)
    assert boards.status_code == 200
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    denied = client.post(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
        headers=headers,
        json={"list_id": lists[0]["id"], "title": "Nope"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"


def test_agent_writes_are_audited_as_agent(
    api: Api, client: TestClient, board: dict[str, Any]
) -> None:
    token = _issue_token(api, ["cards:read", "cards:write"])
    headers = {"Authorization": f"Bearer {token}"}
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    created = client.post(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
        headers=headers,
        json={"list_id": lists[0]["id"], "title": "By agent"},
    )
    assert created.status_code == 201, created.text
    activity = api.data(
        api.get(f"/api/v1/boards/{board['id']}/activity", params={"actor_type": "agent"})
    )
    assert activity[0]["action"] == "card.created"
    assert activity[0]["actor_type"] == "agent"


def test_revoked_token_is_rejected(api: Api, client: TestClient) -> None:
    credential = api.data(
        api.post(
            "/api/v1/credentials",
            json={"name": "revocable", "scopes": ["boards:read"]},
        )
    )
    headers = {"Authorization": f"Bearer {credential['token']}"}
    assert client.get("/api/v1/boards", headers=headers).status_code == 200
    api.data(api.post(f"/api/v1/credentials/{credential['id']}/revoke"))
    response = client.get("/api/v1/boards", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_revoked"


def test_unknown_scope_is_rejected(api: Api) -> None:
    response = api.post(
        "/api/v1/credentials", json={"name": "bad", "scopes": ["boards:read", "sql:write"]}
    )
    assert response.status_code == 422


def test_credentials_are_not_readable_after_creation(api: Api) -> None:
    created = api.data(
        api.post("/api/v1/credentials", json={"name": "listed", "scopes": ["boards:read"]})
    )
    listed = api.data(api.get("/api/v1/credentials"))
    assert all("token" not in entry for entry in listed)
    assert listed[0]["id"] == created["id"]


@pytest.fixture()
def limited_settings(tmp_path: Any) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret",
        bootstrap_password="test-password",
        rate_limit_per_minute=5,
        max_request_bytes=512,
    )


def test_rate_limit_returns_429(limited_settings: Settings) -> None:
    app = create_app(limited_settings)
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password"})
        statuses = [client.get("/api/v1/boards").status_code for _ in range(8)]
    assert 429 in statuses
    assert statuses.count(200) <= 6


def test_oversized_request_is_rejected(limited_settings: Settings) -> None:
    app = create_app(limited_settings)
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password"})
        csrf = client.cookies.get("tralala_csrf")
        response = client.post(
            "/api/v1/boards",
            content=b"x" * 5000,
            headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
