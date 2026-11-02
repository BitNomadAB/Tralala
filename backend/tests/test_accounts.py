from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import Api
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.context import SCOPES, ActorContext
from app.core.secrets import open_secret
from app.main import create_app
from app.schemas.agents import AgentCreate
from app.services import Services

ADMIN_SCOPES = frozenset(SCOPES)


def _admin_actor() -> ActorContext:
    return ActorContext(
        actor_id="service-test-admin",
        actor_type="user",
        actor_name="admin",
        scopes=ADMIN_SCOPES,
        role="admin",
    )


def _login(client: TestClient, username: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("tralala_csrf") or ""}


def _issue_token(api: Api, scopes: list[str], **extra: Any) -> dict[str, Any]:
    payload = {"name": "scoped-agent", "scopes": scopes, **extra}
    return api.data(api.post("/api/v1/credentials", json=payload))


def test_logout_revokes_the_session_row(api: Api) -> None:
    registry = api.client.app.state.services.registry
    assert registry.read("SELECT id FROM sessions WHERE revoked_at IS NULL")
    api.data(api.post("/api/v1/auth/logout"))
    rows = registry.read("SELECT revoked_at FROM sessions")
    assert rows and all(row["revoked_at"] for row in rows)


def test_password_change_requires_the_current_password(api: Api) -> None:
    response = api.post(
        "/api/v1/auth/password",
        json={"current_password": "not-the-password", "new_password": "a-long-new-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_password_change_revokes_every_session(api: Api) -> None:
    response = api.post(
        "/api/v1/auth/password",
        json={"current_password": "test-password", "new_password": "a-long-new-password"},
    )
    assert api.data(response)["changed"] is True
    assert api.get("/api/v1/auth/me").status_code == 401
    client = api.client
    assert _login(client, "admin", "test-password").status_code == 401
    assert _login(client, "admin", "a-long-new-password").status_code == 200


def test_short_password_is_rejected(api: Api) -> None:
    response = api.post(
        "/api/v1/auth/password",
        json={"current_password": "test-password", "new_password": "short"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_eight_character_password_is_accepted(api: Api) -> None:
    created = api.data(
        api.post(
            "/api/v1/users",
            json={"name": "eight", "password": "eight123", "role": "member"},
        )
    )
    assert created["name"] == "eight"
    assert created["role"] == "member"


def test_member_has_the_same_access_but_cannot_manage_users(api: Api) -> None:
    created = api.data(
        api.post(
            "/api/v1/users",
            json={"name": "sam", "password": "member-password-1", "role": "member"},
        )
    )
    assert created["role"] == "member"

    client = api.client
    client.cookies.clear()
    login = _login(client, "sam", "member-password-1")
    assert login.status_code == 200
    assert login.json()["data"]["actor"]["role"] == "member"

    board = client.post(
        "/api/v1/boards", json={"name": "Member board"}, headers=_csrf(client)
    )
    assert board.status_code == 201
    assert client.get("/api/v1/users").status_code == 403
    # A member keeps hold of their own agent access, but sees nothing of anybody else's.
    mine = client.get("/api/v1/credentials")
    assert mine.status_code == 200
    assert mine.json()["data"] == []


def test_a_member_manages_only_their_own_agent_access(api: Api) -> None:
    created = api.data(
        api.post(
            "/api/v1/users",
            json={"name": "kim", "password": "member-password-1", "role": "member"},
        )
    )
    assert created["role"] == "member"

    client = api.client
    client.cookies.clear()
    assert _login(client, "kim", "member-password-1").status_code == 200
    issued = client.post(
        "/api/v1/credentials",
        json={"name": "kim desktop", "scopes": ["boards:read", "loops:write"]},
        headers=_csrf(client),
    )
    assert issued.status_code == 201, issued.text
    mine = issued.json()["data"]
    assert mine["owner_actor_id"] == created["id"]
    assert mine["expires_at"]

    wide = client.post(
        "/api/v1/credentials",
        json={"name": "too wide", "scopes": ["boards:write"]},
        headers=_csrf(client),
    )
    assert wide.status_code == 422
    assert wide.json()["error"]["code"] == "forbidden_scope"

    # The administrator sees the member's access, and may revoke it.
    all_tokens = api.data(api.get("/api/v1/credentials"))
    assert [entry["name"] for entry in all_tokens] == ["kim desktop"]
    assert all_tokens[0]["owner_name"] == "kim"
    api.data(api.post(f"/api/v1/credentials/{mine['id']}/revoke"))

    other = client.post(f"/api/v1/credentials/{mine['id']}/revoke", headers=_csrf(client))
    assert other.status_code == 404


def test_the_last_admin_cannot_be_demoted(api: Api) -> None:
    me = api.data(api.get("/api/v1/auth/me"))
    response = api.patch(f"/api/v1/users/{me['id']}", json={"role": "member"})
    assert response.status_code == 409


def test_disabled_user_cannot_sign_in(api: Api) -> None:
    created = api.data(
        api.post(
            "/api/v1/users",
            json={"name": "robin", "password": "member-password-1", "role": "member"},
        )
    )
    api.data(api.patch(f"/api/v1/users/{created['id']}", json={"disabled": True}))
    api.client.cookies.clear()
    assert _login(api.client, "robin", "member-password-1").status_code == 401


def test_repeated_failed_sign_ins_are_throttled(client: TestClient) -> None:
    for _ in range(5):
        assert _login(client, "admin", "wrong-password").status_code == 401
    blocked = _login(client, "admin", "test-password")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["details"]["retry_after_seconds"] >= 1


def test_activity_feed_requires_card_read(api: Api, board: dict[str, Any]) -> None:
    token = _issue_token(api, ["boards:read"])["token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = api.client.get(f"/api/v1/boards/{board['id']}/activity", headers=headers)
    assert response.status_code == 403


def test_tokens_may_hold_discussion_scopes(api: Api) -> None:
    credential = _issue_token(api, ["discussions:read", "discussions:write"])
    assert credential["scopes"] == ["discussions:read", "discussions:write"]


def test_tokens_cannot_hold_administration_scopes(api: Api) -> None:
    response = api.post(
        "/api/v1/credentials", json={"name": "escalated", "scopes": ["users:admin"]}
    )
    assert response.status_code == 422


def test_credentials_expire_by_default(api: Api) -> None:
    credential = _issue_token(api, ["boards:read"])
    expires = datetime.strptime(credential["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    remaining = expires - datetime.now(UTC)
    assert timedelta(days=89) < remaining <= timedelta(days=90)


def test_rotating_a_credential_replaces_the_old_token(api: Api) -> None:
    original = _issue_token(api, ["boards:read"])
    rotated = api.data(api.post(f"/api/v1/credentials/{original['id']}/rotate"))
    assert rotated["token"] != original["token"]
    old_headers = {"Authorization": f"Bearer {original['token']}"}
    new_headers = {"Authorization": f"Bearer {rotated['token']}"}
    assert api.client.get("/api/v1/boards", headers=old_headers).status_code == 401
    assert api.client.get("/api/v1/boards", headers=new_headers).status_code == 200


@pytest.fixture()
def rotation_path(tmp_path: Path) -> Path:
    return tmp_path / "data"


def test_appearance_preferences_are_per_account(api: Api) -> None:
    api.data(
        api.post(
            "/api/v1/users",
            json={"name": "pref-user", "password": "member-password-1", "role": "member"},
        )
    )
    assert api.data(api.get("/api/v1/auth/preferences")) == {
        "theme_mode": None,
        "theme_kit": None,
    }
    updated = api.data(
        api.put(
            "/api/v1/auth/preferences",
            json={"theme_mode": "light", "theme_kit": "matchmap"},
        )
    )
    assert updated == {"theme_mode": "light", "theme_kit": "matchmap"}
    assert api.data(api.get("/api/v1/auth/me"))["preferences"]["theme_kit"] == "matchmap"

    client = api.client
    client.cookies.clear()
    assert _login(client, "pref-user", "member-password-1").status_code == 200
    assert client.get("/api/v1/auth/preferences").json()["data"] == {
        "theme_mode": None,
        "theme_kit": None,
    }
    response = client.put(
        "/api/v1/auth/preferences",
        json={"theme_kit": "classic"},
        headers=_csrf(client),
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"theme_mode": None, "theme_kit": "classic"}


def test_preferences_survive_a_new_session(api: Api) -> None:
    api.data(
        api.put(
            "/api/v1/auth/preferences",
            json={"theme_mode": "light", "theme_kit": "classic"},
        )
    )
    api.data(api.post("/api/v1/auth/logout"))
    login = _login(api.client, "admin", "test-password")
    assert login.json()["data"]["actor"]["preferences"] == {
        "theme_mode": "light",
        "theme_kit": "classic",
    }


def test_unknown_theme_kit_is_rejected(api: Api) -> None:
    response = api.put("/api/v1/auth/preferences", json={"theme_kit": "neon"})
    assert response.status_code == 422


def test_tokens_have_no_personal_preferences(api: Api) -> None:
    token = _issue_token(api, ["boards:read"])["token"]
    response = api.client.put(
        "/api/v1/auth/preferences",
        json={"theme_kit": "classic"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_previous_secret_rewraps_stored_agent_keys(rotation_path: Path) -> None:
    old_secret = "old-install-secret-" + "a" * 32
    new_secret = "new-install-secret-" + "b" * 32
    base = {
        "data_dir": rotation_path,
        "bootstrap_password": "test-password",
        "rate_limit_per_minute": 100000,
    }

    first = Services(Settings(secret_key=old_secret, **base))
    first.initialize()
    agent = first.agent.create(
        _admin_actor(),
        AgentCreate(
            name="Rotation agent",
            role_prompt_override="You review pull requests.",
            connection_type="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="sk-original-key-1234",
        ),
    )
    before = first.agent.get_row(agent["id"])["api_key_ciphertext"]
    first.shutdown()

    second = Services(
        Settings(secret_key=new_secret, previous_secret_key=old_secret, **base)
    )
    second.initialize()
    after = second.agent.get_row(agent["id"])["api_key_ciphertext"]
    assert after != before
    assert open_secret(Settings(secret_key=new_secret, **base), after) == "sk-original-key-1234"
    second.shutdown()

    # The previous secret can now be removed from the environment.
    final = Settings(secret_key=new_secret, **base)
    assert open_secret(final, after) == "sk-original-key-1234"


def test_application_starts_with_generated_bootstrap_password(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        secret_key="install-secret-" + "c" * 32,
        bootstrap_password="admin",
    )
    with TestClient(create_app(settings)):
        pass
    password_file = tmp_path / "data" / ".bootstrap-password"
    assert password_file.exists()
    generated = password_file.read_text(encoding="utf-8").strip()
    assert len(generated) >= 16
