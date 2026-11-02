"""Enrolment links: an administrator never has to know a user password."""

from __future__ import annotations

from typing import Any

from conftest import Api
from fastapi.testclient import TestClient
from sqlalchemy import text


def _create_user(api: Api, name: str, *, role: str = "member") -> dict[str, Any]:
    return api.data(
        api.post(
            "/api/v1/users",
            json={"name": name, "password": "start-password-1", "role": role},
        )
    )


def _invite(api: Api, user_id: str, **overrides: Any) -> dict[str, Any]:
    response = api.post(f"/api/v1/users/{user_id}/invite", json=overrides)
    assert response.status_code == 201, response.text
    return api.data(response)


def test_an_invite_lets_a_person_set_their_own_password(
    api: Api, client: TestClient
) -> None:
    user = _create_user(api, "Invited person")
    invite = _invite(api, user["id"])
    assert invite["path"] == f"/enrol?token={invite['token']}"
    assert invite["user_name"] == "Invited person"
    assert invite["expires_at"]

    # The stored token is a hash, never the value the administrator copies.
    stored = api.client.app.state.services.registry.read_one(
        "SELECT token_hash FROM user_invites WHERE actor_id = :id", {"id": user["id"]}
    )
    assert stored is not None
    assert stored["token_hash"] != invite["token"]

    enrolled = client.post(
        "/api/v1/auth/enrol",
        json={"token": invite["token"], "password": "chosen-by-the-user-9"},
    )
    assert enrolled.status_code == 200, enrolled.text
    body = enrolled.json()["data"]
    assert body["actor"]["name"] == "Invited person"
    assert body["csrf_token"]

    # The session from the response is usable straight away.
    assert client.get("/api/v1/auth/me").json()["data"]["name"] == "Invited person"

    fresh = TestClient(client.app)
    signed_in = fresh.post(
        "/api/v1/auth/login",
        json={"username": "Invited person", "password": "chosen-by-the-user-9"},
    )
    assert signed_in.status_code == 200, signed_in.text


def test_an_invite_works_once(api: Api, client: TestClient) -> None:
    user = _create_user(api, "Once only")
    invite = _invite(api, user["id"])
    first = client.post(
        "/api/v1/auth/enrol", json={"token": invite["token"], "password": "first-password-1"}
    )
    assert first.status_code == 200, first.text

    again = client.post(
        "/api/v1/auth/enrol", json={"token": invite["token"], "password": "second-password-2"}
    )
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "invite_used"


def test_an_expired_invite_is_refused(api: Api, client: TestClient) -> None:
    user = _create_user(api, "Too slow")
    invite = _invite(api, user["id"])
    registry = api.client.app.state.services.registry
    with registry.connect() as conn:
        conn.execute(
            text("UPDATE user_invites SET expires_at = '2000-01-01T00:00:00Z'"
                 " WHERE actor_id = :id"),
            {"id": user["id"]},
        )

    response = client.post(
        "/api/v1/auth/enrol", json={"token": invite["token"], "password": "late-password-9"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invite_expired"


def test_an_unknown_invite_reads_like_an_used_one(api: Api, client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/enrol", json={"token": "not-a-real-token", "password": "whatever-123"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invite_invalid"


def test_only_an_administrator_can_invite(api: Api) -> None:
    user = _create_user(api, "Member person")
    credential = api.data(
        api.post("/api/v1/credentials", json={"name": "agent", "scopes": ["boards:read"]})
    )
    headers = {"Authorization": f"Bearer {credential['token']}"}
    response = api.client.post(
        f"/api/v1/users/{user['id']}/invite", json={}, headers=headers
    )
    assert response.status_code == 403, response.text


def test_a_new_invite_replaces_the_previous_one(api: Api, client: TestClient) -> None:
    user = _create_user(api, "Two links")
    first = _invite(api, user["id"])
    second = _invite(api, user["id"])
    assert first["token"] != second["token"]

    stale = client.post(
        "/api/v1/auth/enrol", json={"token": first["token"], "password": "stale-password-1"}
    )
    assert stale.status_code == 401

    fresh = client.post(
        "/api/v1/auth/enrol", json={"token": second["token"], "password": "fresh-password-2"}
    )
    assert fresh.status_code == 200, fresh.text


def test_a_weak_password_is_refused_at_enrolment(api: Api, client: TestClient) -> None:
    user = _create_user(api, "Weak chooser")
    invite = _invite(api, user["id"])
    response = client.post(
        "/api/v1/auth/enrol", json={"token": invite["token"], "password": "password"}
    )
    assert response.status_code == 422, response.text
    # The link survives a rejected password: the person can try again.
    retry = client.post(
        "/api/v1/auth/enrol", json={"token": invite["token"], "password": "strong-enough-1"}
    )
    assert retry.status_code == 200, retry.text


def test_a_disabled_account_cannot_be_invited(api: Api) -> None:
    user = _create_user(api, "Disabled person")
    api.data(api.patch(f"/api/v1/users/{user['id']}", json={"disabled": True}))
    response = api.post(f"/api/v1/users/{user['id']}/invite", json={})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "user_disabled"
