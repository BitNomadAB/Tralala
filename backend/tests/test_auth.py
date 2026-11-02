from __future__ import annotations

from pathlib import Path

from conftest import Api
from fastapi.testclient import TestClient


def test_login_rejects_bad_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "invalid_credentials"
    assert body["request_id"]


def test_login_sets_session_and_csrf_cookies(login: TestClient) -> None:
    assert "tralala_session" in login.cookies
    assert "tralala_csrf" in login.cookies
    me = login.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["name"] == "admin"


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_write_requires_csrf_header(login: TestClient) -> None:
    response = login.post("/api/v1/boards", json={"name": "No csrf"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_logout_clears_session(api: Api) -> None:
    response = api.post("/api/v1/auth/logout")
    assert api.data(response)["logged_out"] is True
    assert api.get("/api/v1/auth/me").status_code == 401


def test_unknown_fields_are_rejected(api: Api) -> None:
    response = api.post("/api/v1/boards", json={"name": "x", "unexpected": True})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert any("unexpected" in field["loc"] for field in error["details"])


def test_error_envelope_is_machine_readable(api: Api) -> None:
    response = api.get("/api/v1/boards/not-a-uuid")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["retryable"] is False
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_a_published_password_never_becomes_the_administrator_password(tmp_path: Path) -> None:
    """A copied old .env must not produce an administrator anyone can sign in as."""
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret-key-with-at-least-32-chars",
        bootstrap_username="admin",
        bootstrap_password="tralala-dev-1",
        rate_limit_per_minute=100000,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        generated = (settings.data_dir / ".bootstrap-password").read_text(encoding="utf-8").strip()
        assert generated and generated != "tralala-dev-1"

        refused = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "tralala-dev-1"},
        )
        assert refused.status_code == 401

        accepted = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": generated},
        )
        assert accepted.status_code == 200, accepted.text
