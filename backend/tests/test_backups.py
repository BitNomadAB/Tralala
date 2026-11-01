from __future__ import annotations

from typing import Any

from conftest import Api


def _card_titles(api: Api, board_id: str) -> list[str]:
    return [card["title"] for card in api.data(api.get(f"/api/v1/boards/{board_id}/cards"))]


def test_backup_create_list_and_restore(api: Api, board: dict[str, Any]) -> None:
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    todo = lists[1]["id"]
    api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards", json={"list_id": todo, "title": "Before"})
    )
    backup = api.data(api.post(f"/api/v1/boards/{board['id']}/backups"))
    assert backup["verification"]["ok"] is True
    listed = api.data(api.get(f"/api/v1/boards/{board['id']}/backups"))
    assert [item["name"] for item in listed] == [backup["name"]]

    api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards", json={"list_id": todo, "title": "After"})
    )
    assert len(_card_titles(api, board["id"])) == 2

    restored = api.data(api.post(f"/api/v1/boards/{board['id']}/backups/{backup['name']}/restore"))
    assert restored["verification"]["ok"] is True
    assert _card_titles(api, board["id"]) == ["Before"]


def test_validate_reports_integrity(api: Api, board: dict[str, Any]) -> None:
    report = api.data(api.get(f"/api/v1/boards/{board['id']}/validate"))
    assert report["ok"] is True
    assert report["integrity"] == "ok"
    assert report["foreign_key_violations"] == []
    assert report["counts"]["lists"] == 5


def test_restore_rejects_path_traversal(api: Api, board: dict[str, Any]) -> None:
    response = api.post(f"/api/v1/boards/{board['id']}/backups/..%2F..%2Fregistry.sqlite/restore")
    assert response.status_code in {404, 422}
