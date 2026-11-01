"""GitHub repositories: registry list, board assignment, sealed token, access check."""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import Api

from app.services import repositories


def _create(api: Api, **overrides: Any) -> dict[str, Any]:
    payload = {
        "url": "https://github.com/BitNomadAB/Tralala",
        "branch": "main",
        "token": "github_pat_11ABCDEFG_secret_value",
        **overrides,
    }
    response = api.post("/api/v1/repositories", json=payload)
    assert response.status_code == 201, response.text
    return api.data(response)


def test_a_token_is_stored_sealed_and_never_returned(api: Api, board: dict[str, Any]) -> None:
    created = _create(api)
    assert created["name"] == "Tralala"
    assert created["boards"] == []
    assert created["has_token"] is True
    assert created["token_hint"]
    assert "github_pat" not in json.dumps(created)

    stored = api.client.app.state.services.registry.read_one(
        "SELECT token_ciphertext FROM repositories WHERE id = :id", {"id": created["id"]}
    )
    assert stored is not None
    assert "github_pat" not in stored["token_ciphertext"]
    assert api.client.app.state.services.repository.token(created["id"]) == (
        "github_pat_11ABCDEFG_secret_value"
    )

    fetched = api.data(api.get(f"/api/v1/repositories/{created['id']}"))
    assert "github_pat" not in json.dumps(fetched)


def test_a_board_can_select_several_repositories(api: Api) -> None:
    first = _create(api, url="https://github.com/BitNomadAB/Tralala")
    second = _create(api, url="https://github.com/BitNomadAB/other", name="Other")
    board = api.data(
        api.post(
            "/api/v1/boards",
            json={"name": "Linked board", "repository_ids": [first["id"], second["id"]]},
        )
    )
    assert set(board["repository_ids"]) == {first["id"], second["id"]}

    selected = api.data(api.get("/api/v1/repositories", params={"board_id": board["id"]}))
    assert {item["id"] for item in selected} == {first["id"], second["id"]}
    assert [entry["name"] for entry in selected[0]["boards"]] == ["Linked board"]


def test_editing_a_board_replaces_its_repository_selection(api: Api) -> None:
    first = _create(api, url="https://github.com/BitNomadAB/Tralala")
    second = _create(api, url="https://github.com/BitNomadAB/other", name="Other")
    board = api.data(
        api.post("/api/v1/boards", json={"name": "Editable", "repository_ids": [first["id"]]})
    )
    assert board["repository_ids"] == [first["id"]]

    kept = api.data(
        api.patch(f"/api/v1/boards/{board['id']}", json={"description": "Only a description"})
    )
    assert kept["repository_ids"] == [first["id"]]

    replaced = api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}", json={"repository_ids": [second["id"]]}
        )
    )
    assert replaced["repository_ids"] == [second["id"]]

    cleared = api.data(
        api.patch(f"/api/v1/boards/{board['id']}", json={"repository_ids": []})
    )
    assert cleared["repository_ids"] == []


def test_one_repository_may_serve_two_boards(api: Api) -> None:
    shared = _create(api)
    first = api.data(
        api.post("/api/v1/boards", json={"name": "First", "repository_ids": [shared["id"]]})
    )
    second = api.data(
        api.post("/api/v1/boards", json={"name": "Second", "repository_ids": [shared["id"]]})
    )
    boards = api.data(api.get(f"/api/v1/repositories/{shared['id']}"))["boards"]
    assert {entry["id"] for entry in boards} == {first["id"], second["id"]}
    listed = api.data(api.get("/api/v1/repositories"))
    assert [item["id"] for item in listed] == [shared["id"]]


def test_an_unknown_repository_cannot_be_selected(api: Api) -> None:
    response = api.post(
        "/api/v1/boards",
        json={
            "name": "Broken link",
            "repository_ids": ["0f0f0f0f-0000-0000-0000-000000000000"],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "repository_not_found"
    assert api.data(api.get("/api/v1/boards")) == []

    board = api.data(api.post("/api/v1/boards", json={"name": "Kept"}))
    rejected = api.patch(
        f"/api/v1/boards/{board['id']}",
        json={"name": "Renamed", "repository_ids": ["0f0f0f0f-0000-0000-0000-000000000000"]},
    )
    assert rejected.status_code == 404
    unchanged = api.data(api.get(f"/api/v1/boards/{board['id']}"))
    assert unchanged["name"] == "Kept"
    assert unchanged["repository_ids"] == []


def test_deleting_a_repository_detaches_it_from_boards(api: Api) -> None:
    repository = _create(api)
    board = api.data(
        api.post(
            "/api/v1/boards",
            json={"name": "Detach board", "repository_ids": [repository["id"]]},
        )
    )
    api.data(api.delete(f"/api/v1/repositories/{repository['id']}"))
    refreshed = api.data(api.get(f"/api/v1/boards/{board['id']}"))
    assert refreshed["repository_ids"] == []


def test_clearing_the_token_keeps_the_repository(api: Api, board: dict[str, Any]) -> None:
    created = _create(api)
    cleared = api.data(
        api.patch(f"/api/v1/repositories/{created['id']}", json={"clear_token": True})
    )
    assert cleared["has_token"] is False
    assert cleared["token_hint"] is None
    assert cleared["url"].endswith("BitNomadAB/Tralala")
    assert api.client.app.state.services.repository.token(created["id"]) is None


def test_a_token_and_clear_token_together_are_rejected(api: Api, board: dict[str, Any]) -> None:
    created = _create(api)
    response = api.patch(
        f"/api/v1/repositories/{created['id']}",
        json={"token": "github_pat_x", "clear_token": True},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/BitNomadAB/Tralala",
        "https://user:secret@github.com/BitNomadAB/Tralala",
        "https://gitlab.com/BitNomadAB/Tralala",
        "https://github.com/BitNomadAB",
        "https://github.com/BitNomadAB/Tralala/tree/main",
        "file:///etc/passwd",
    ],
)
def test_only_a_github_repository_url_is_accepted(api: Api, url: str) -> None:
    response = api.post("/api/v1/repositories", json={"url": url})
    assert response.status_code == 422, response.text


def test_a_trailing_git_suffix_is_tolerated() -> None:
    assert repositories.RepositoryService.parse(
        "https://github.com/BitNomadAB/Tralala.git"
    ) == ("BitNomadAB", "Tralala")


def test_check_reports_the_repository_without_echoing_the_token(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    created = _create(api)
    calls: list[tuple[str, str | None]] = []

    def fake_get(url: str, *, token: str | None, timeout: float = 10.0):
        calls.append((url, token))
        if url.endswith("/branches/main"):
            return 200, {"name": "main"}
        return 200, {"default_branch": "main", "private": True, "size": 512}

    monkeypatch.setattr(repositories, "_github_get", fake_get)
    result = api.data(api.post(f"/api/v1/repositories/{created['id']}/check"))
    assert result["status"] == "ok"
    assert result["default_branch"] == "main"
    assert result["private"] is True
    assert result["size_kb"] == 512
    assert "github_pat" not in json.dumps(result)
    assert calls[0][1] == "github_pat_11ABCDEFG_secret_value"

    stored = api.data(api.get(f"/api/v1/repositories/{created['id']}"))
    assert stored["last_check_status"] == "ok"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "unauthorized"), (404, "not_found"), (403, "forbidden"), (502, "unreachable")],
)
def test_check_maps_failures_to_a_stable_status(
    api: Api, board: dict[str, Any], monkeypatch: Any, status_code: int, expected: str
) -> None:
    created = _create(api)
    monkeypatch.setattr(
        repositories, "_github_get", lambda url, *, token, timeout=10.0: (status_code, None)
    )
    result = api.data(api.post(f"/api/v1/repositories/{created['id']}/check"))
    assert result["status"] == expected
    assert result["detail"]


def test_check_names_a_missing_branch(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    created = _create(api, branch="does-not-exist")
    monkeypatch.setattr(
        repositories,
        "_github_get",
        lambda url, *, token, timeout=10.0: (200 if url.endswith("/Tralala") else 404, {}),
    )
    result = api.data(api.post(f"/api/v1/repositories/{created['id']}/check"))
    assert result["status"] == "branch_missing"


def test_deleting_a_repository_removes_it_from_the_list(
    api: Api, board: dict[str, Any]
) -> None:
    created = _create(api)
    api.data(api.delete(f"/api/v1/repositories/{created['id']}"))
    assert api.data(api.get("/api/v1/repositories", params={"board_id": board["id"]})) == []
    assert api.get(f"/api/v1/repositories/{created['id']}").status_code == 404


def test_unknown_repository_is_reported(api: Api) -> None:
    response = api.get("/api/v1/repositories/0f0f0f0f-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "repository_not_found"


def test_tokens_are_resealed_after_a_secret_rotation(tmp_path: Any) -> None:
    from app.core.config import Settings
    from app.schemas.repositories import RepositoryCreate
    from app.services import Services

    base = {
        "data_dir": tmp_path / "data",
        "bootstrap_password": "test-password",
        "rate_limit_per_minute": 100000,
    }
    first = Services(Settings(secret_key="a" * 32, **base))
    first.initialize()
    try:
        created = first.repository.create(
            _admin_actor(),
            RepositoryCreate(
                url="https://github.com/BitNomadAB/Tralala", token="github_pat_rotate"
            ),
        )
    finally:
        first.shutdown()

    second = Services(Settings(secret_key="b" * 32, previous_secret_key="a" * 32, **base))
    second.initialize()
    try:
        assert second.repository.token(created["id"]) == "github_pat_rotate"
        # Already sealed with the current secret, so a second start reseals nothing.
        assert second.repository.reseal_tokens() == 0
    finally:
        second.shutdown()


def _admin_actor() -> Any:
    from app.core.context import SCOPES, ActorContext

    return ActorContext(
        actor_id="actor-admin",
        actor_type="user",
        actor_name="admin",
        role="admin",
        scopes=frozenset(SCOPES),
    )


def test_a_board_reader_gets_no_credential_hint_or_check_history(api: Api) -> None:
    """Administration detail stays with administrators; the list itself stays usable."""
    created = _create(api)
    credential = api.data(
        api.post(
            "/api/v1/credentials",
            json={"name": "planner agent", "scopes": ["boards:read", "loops:read"]},
        )
    )
    headers = {"Authorization": f"Bearer {credential['token']}"}

    listed = api.client.get("/api/v1/repositories", headers=headers)
    assert listed.status_code == 200, listed.text
    entry = listed.json()["data"][0]
    assert set(entry) == {
        "id",
        "name",
        "provider",
        "url",
        "branch",
        "enabled",
        "has_token",
        "boards",
        "created_at",
        "updated_at",
    }
    assert entry["id"] == created["id"]

    single = api.client.get(f"/api/v1/repositories/{created['id']}", headers=headers)
    assert single.status_code == 200, single.text
    assert "token_hint" not in single.json()["data"]

    admin_view = api.data(api.get(f"/api/v1/repositories/{created['id']}"))
    assert admin_view["token_hint"] == created["token_hint"]
