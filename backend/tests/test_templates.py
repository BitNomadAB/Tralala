from __future__ import annotations

from typing import Any

from conftest import Api, loop_id


def _template(api: Api, name: str = "Sprint", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "description": "Two week delivery board",
        "lists": ["Ideas", "Doing", "Done"],
        "labels": [{"name": "bug", "color": "#ef4444"}],
        **overrides,
    }
    return api.data(api.post("/api/v1/templates", json=payload))


def test_template_crud_roundtrip(api: Api) -> None:
    created = _template(api)
    assert created["lists"] == ["Ideas", "Doing", "Done"]
    assert created["list_count"] == 3
    assert created["description"] == "Two week delivery board"
    assert created["labels"] == [{"name": "bug", "color": "#ef4444"}]

    listing = api.data(api.get("/api/v1/templates"))
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == created["id"]

    fetched = api.data(api.get(f"/api/v1/templates/{created['id']}"))
    assert fetched["name"] == "Sprint"

    updated = api.data(
        api.patch(
            f"/api/v1/templates/{created['id']}",
            json={
                "name": "Sprint v2",
                "description": "Revised",
                "lists": ["Ready", "Doing", "Review", "Done"],
            },
        )
    )
    assert updated["name"] == "Sprint v2"
    assert updated["lists"] == ["Ready", "Doing", "Review", "Done"]
    assert updated["labels"] == [{"name": "bug", "color": "#ef4444"}]
    assert updated["created_at"] == created["created_at"]

    api.data(api.delete(f"/api/v1/templates/{created['id']}"))
    assert api.data(api.get("/api/v1/templates"))["total"] == 0
    assert api.get(f"/api/v1/templates/{created['id']}").status_code == 404


def test_create_board_from_template_applies_description_lists_and_labels(api: Api) -> None:
    template = _template(api)
    board = api.data(
        api.post(
            "/api/v1/boards",
            json={"name": "Sprint 42", "template_id": template["id"]},
        )
    )
    assert board["description"] == "Two week delivery board"
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    assert [item["name"] for item in lists] == ["Ideas", "Doing", "Done"]
    labels = api.data(api.get(f"/api/v1/boards/{board['id']}/labels"))
    assert [(item["name"], item["color"]) for item in labels] == [("bug", "#ef4444")]


def test_board_description_overrides_template(api: Api) -> None:
    template = _template(api)
    board = api.data(
        api.post(
            "/api/v1/boards",
            json={
                "name": "Custom",
                "description": "Own words",
                "template_id": template["id"],
                "lists": ["Only"],
            },
        )
    )
    assert board["description"] == "Own words"
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    assert [item["name"] for item in lists] == ["Only"]


def test_blank_board_uses_default_lists(api: Api) -> None:
    _template(api)
    board = api.data(api.post("/api/v1/boards", json={"name": "Blank"}))
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    assert [item["name"] for item in lists] == [
        "Backlog",
        "Todo",
        "In Progress",
        "Review",
        "Done",
    ]
    assert api.data(api.get(f"/api/v1/boards/{board['id']}/labels")) == []


def test_create_board_with_unknown_template_is_rejected(api: Api) -> None:
    response = api.post("/api/v1/boards", json={"name": "Ghost", "template_id": "missing-template"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert api.data(api.get("/api/v1/boards")) == []


def test_template_without_lists_falls_back_to_defaults(api: Api) -> None:
    template = _template(api, name="Empty", lists=[])
    board = api.data(
        api.post("/api/v1/boards", json={"name": "From empty", "template_id": template["id"]})
    )
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    assert len(lists) == 5


def test_template_names_are_unique(api: Api) -> None:
    _template(api, name="Shared")
    response = api.post("/api/v1/templates", json={"name": "shared"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "template_name_taken"


def test_duplicate_template_list_names_are_rejected(api: Api) -> None:
    response = api.post("/api/v1/templates", json={"name": "Dup", "lists": ["Todo", "todo"]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_save_board_as_template_snapshots_structure(api: Api, board: dict[str, Any]) -> None:
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/labels",
            json={"name": "urgent", "color": "#f97316"},
        )
    )
    template = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/templates",
            json={"name": "From board", "description": "Copied structure"},
        )
    )
    assert template["description"] == "Copied structure"
    assert template["lists"] == ["Backlog", "Todo", "In Progress", "Review", "Done"]
    assert template["labels"] == [{"name": "urgent", "color": "#f97316"}]

    clone = api.data(
        api.post("/api/v1/boards", json={"name": "Clone", "template_id": template["id"]})
    )
    lists = api.data(
        api.get(f"/api/v1/boards/{clone['id']}/loops/{loop_id(api, clone['id'])}/lists")
    )
    assert [item["name"] for item in lists] == template["lists"]


def test_template_endpoints_require_auth(client: Any) -> None:
    assert client.get("/api/v1/templates").status_code == 401
    assert client.post("/api/v1/templates", json={"name": "Nope"}).status_code == 401
