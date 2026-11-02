from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from conftest import Api, loop_id


def test_create_board_creates_isolated_database(
    api: Api, board: dict[str, Any], settings: Any
) -> None:
    assert board["status"] == "active"
    database = Path(settings.data_dir) / "boards" / board["id"] / "board.sqlite"
    assert database.exists()
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


def test_board_listing_supports_search_and_status_filters(api: Api) -> None:
    api.data(api.post("/api/v1/boards", json={"name": "Alpha"}))
    second = api.data(api.post("/api/v1/boards", json={"name": "Beta"}))
    api.data(api.post(f"/api/v1/boards/{second['id']}/archive"))
    found = api.data(api.get("/api/v1/boards", params={"q": "Alph"}))
    assert [item["name"] for item in found] == ["Alpha"]
    archived = api.data(api.get("/api/v1/boards", params={"status": "archived"}))
    assert [item["id"] for item in archived] == [second["id"]]


def test_board_update_and_archive_roundtrip(api: Api, board: dict[str, Any]) -> None:
    updated = api.data(
        api.patch(f"/api/v1/boards/{board['id']}", json={"name": "Renamed", "description": "d"})
    )
    assert updated["name"] == "Renamed"
    archived = api.data(api.post(f"/api/v1/boards/{board['id']}/archive"))
    assert archived["status"] == "archived"
    restored = api.data(api.post(f"/api/v1/boards/{board['id']}/restore"))
    assert restored["status"] == "active"


def test_board_write_is_blocked_while_archived(api: Api, board: dict[str, Any]) -> None:
    api.data(api.post(f"/api/v1/boards/{board['id']}/loops", json={"name": "Archived loop"}))
    api.data(api.post(f"/api/v1/boards/{board['id']}/archive"))
    response = api.post(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists",
        json={"name": "Blocked"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "board_archived"


def test_board_creation_is_idempotent(api: Api) -> None:
    headers = {"Idempotency-Key": "board-create-1"}
    first = api.post("/api/v1/boards", json={"name": "Idem"}, headers=headers)
    second = api.post("/api/v1/boards", json={"name": "Idem"}, headers=headers)
    assert api.data(first)["id"] == api.data(second)["id"]
    conflict = api.post("/api/v1/boards", json={"name": "Other"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_reused"


def test_duplicate_board_copies_content(api: Api, board: dict[str, Any]) -> None:
    todo = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )[1]
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": todo["id"], "title": "Copied card"},
        )
    )
    duplicate = api.data(api.post(f"/api/v1/boards/{board['id']}/duplicate"))
    assert duplicate["id"] != board["id"]
    cards = api.data(
        api.get(f"/api/v1/boards/{duplicate['id']}/loops/{loop_id(api, duplicate['id'])}/cards")
    )
    assert [card["title"] for card in cards] == ["Copied card"]


def test_export_and_import_roundtrip(api: Api, board: dict[str, Any]) -> None:
    todo = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )[1]
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": todo["id"], "title": "Exported card", "priority": "high"},
        )
    )
    export = api.get(f"/api/v1/boards/{board['id']}/export")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert {"manifest.json", "board.sqlite"} <= set(archive.namelist())

    imported = api.post(
        "/api/v1/boards/import",
        content=export.content,
        headers={"Content-Type": "application/zip"},
    )
    assert imported.status_code == 201, imported.text
    new_board = imported.json()["data"]
    assert new_board["id"] != board["id"]
    cards = api.data(
        api.get(f"/api/v1/boards/{new_board['id']}/loops/{loop_id(api, new_board['id'])}/cards")
    )
    assert [card["title"] for card in cards] == ["Exported card"]
    assert cards[0]["priority"] == "high"


def test_import_rejects_invalid_archive(api: Api) -> None:
    response = api.post(
        "/api/v1/boards/import", content=b"not-a-zip", headers={"Content-Type": "application/zip"}
    )
    assert response.status_code == 422


def test_delete_requires_archive_and_matching_name(api: Api, board: dict[str, Any]) -> None:
    response = api.delete(f"/api/v1/boards/{board['id']}", json={"confirm_name": board["name"]})
    assert response.status_code == 409
    api.data(api.post(f"/api/v1/boards/{board['id']}/archive"))
    mismatch = api.delete(f"/api/v1/boards/{board['id']}", json={"confirm_name": "wrong"})
    assert mismatch.status_code == 422
    deleted = api.delete(f"/api/v1/boards/{board['id']}", json={"confirm_name": board["name"]})
    assert api.data(deleted)["deleted"] is True
    assert api.get(f"/api/v1/boards/{board['id']}").status_code == 404


def _upload_note(api: Api, board: dict[str, Any]) -> dict[str, Any]:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": lists[0]["id"], "title": "Attachment host"},
        )
    )
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/attachments",
            params={"card_id": card["id"], "filename": "notes.txt"},
            content=b"board file body",
            headers={"Content-Type": "text/plain"},
        )
    )


def test_deleting_a_board_with_attachments_removes_the_whole_directory(
    api: Api, board: dict[str, Any], settings: Any
) -> None:
    attachment = _upload_note(api, board)
    directory = Path(settings.data_dir) / "boards" / board["id"]
    assert (directory / "attachments" / f"{attachment['id']}.bin").exists()
    api.data(api.post(f"/api/v1/boards/{board['id']}/archive"))
    deleted = api.delete(f"/api/v1/boards/{board['id']}", json={"confirm_name": board["name"]})
    assert api.data(deleted)["deleted"] is True
    # A board is its database plus its files; leaving either behind both leaks data and leaves a
    # row that can never be opened again.
    assert not directory.exists()


def test_duplicating_a_board_copies_its_attachments(
    api: Api, board: dict[str, Any], settings: Any
) -> None:
    attachment = _upload_note(api, board)
    duplicate = api.data(api.post(f"/api/v1/boards/{board['id']}/duplicate"))
    copied = (
        Path(settings.data_dir)
        / "boards"
        / duplicate["id"]
        / "attachments"
        / f"{attachment['id']}.bin"
    )
    assert copied.read_bytes() == b"board file body"


def test_path_traversal_board_ids_are_rejected(api: Api) -> None:
    for candidate in ("..%2F..%2Fetc", "00000000-0000-0000-0000-000000000000"):
        response = api.get(f"/api/v1/boards/{candidate}")
        assert response.status_code == 404
