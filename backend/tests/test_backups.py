from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import Api, loop_id


def _card_titles(api: Api, board_id: str) -> list[str]:
    return [
        card["title"]
        for card in api.data(
            api.get(f"/api/v1/boards/{board_id}/loops/{loop_id(api, board_id)}/cards")
        )
    ]


def test_backup_create_list_and_restore(api: Api, board: dict[str, Any]) -> None:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    todo = lists[1]["id"]
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": todo, "title": "Before"},
        )
    )
    backup = api.data(api.post(f"/api/v1/boards/{board['id']}/backups"))
    assert backup["verification"]["ok"] is True
    listed = api.data(api.get(f"/api/v1/boards/{board['id']}/backups"))
    assert [item["name"] for item in listed] == [backup["name"]]

    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": todo, "title": "After"},
        )
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
    assert report["counts"]["lists"] == 0
    assert report["counts"]["cards"] == 0


def test_restore_rejects_path_traversal(api: Api, board: dict[str, Any]) -> None:
    response = api.post(f"/api/v1/boards/{board['id']}/backups/..%2F..%2Fregistry.sqlite/restore")
    assert response.status_code in {404, 422}


def test_pruning_keeps_the_newest_and_never_touches_foreign_files(
    api: Api, board: dict[str, Any]
) -> None:
    services = api.client.app.state.services
    directory = services.backup._directory(board["id"])
    directory.mkdir(parents=True, exist_ok=True)
    names = [f"backup-2026010{index}T000000Z.sqlite" for index in range(1, 6)]
    for name in names:
        (directory / name).write_bytes(b"snapshot")
    (directory / "hand-made-copy.sqlite").write_bytes(b"keep me")

    removed = services.backup.prune(board["id"], 2)
    assert removed == names[:3]
    assert sorted(file.name for file in directory.iterdir()) == [
        "backup-20260104T000000Z.sqlite",
        "backup-20260105T000000Z.sqlite",
        "hand-made-copy.sqlite",
    ]


def test_the_scheduler_snapshots_a_board_that_is_due_and_then_waits(
    api: Api, board: dict[str, Any]
) -> None:
    services = api.client.app.state.services
    scheduler = services.backup_scheduler
    scheduler.interval_hours = 24
    scheduler.keep = 1

    first = scheduler.run_once()
    assert [entry["board_id"] for entry in first["created"]] == [board["id"]]
    created = api.data(api.get(f"/api/v1/boards/{board['id']}/backups"))
    assert len(created) == 1
    assert created[0]["name"].startswith("backup-")

    # Fresh snapshot: the next cycle has nothing to do.
    second = scheduler.run_once()
    assert second["created"] == []
    assert second["failed"] == []
    assert len(api.data(api.get(f"/api/v1/boards/{board['id']}/backups"))) == 1


def test_a_disabled_scheduler_does_nothing(api: Api, board: dict[str, Any]) -> None:
    scheduler = api.client.app.state.services.backup_scheduler
    scheduler.interval_hours = 0
    report = scheduler.run_once()
    assert report == {"created": [], "pruned": [], "failed": []}
    assert api.data(api.get(f"/api/v1/boards/{board['id']}/backups")) == []


def _upload_attachment(api: Api, board_id: str, card_id: str, name: str, body: bytes) -> Any:
    return api.post(
        f"/api/v1/boards/{board_id}/attachments",
        params={"card_id": card_id, "filename": name},
        content=body,
        headers={"Content-Type": "text/markdown"},
    )


def test_a_backup_carries_the_uploaded_files_and_restores_them(
    api: Api, board: dict[str, Any]
) -> None:
    """A snapshot without the board's files is not a restorable board."""
    loop = loop_id(api, board["id"])
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop}/lists"))
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop}/cards",
            json={"list_id": lists[0]["id"], "title": "Has a file"},
        )
    )
    uploaded = api.data(_upload_attachment(api, board["id"], card["id"], "notes.md", b"# hello"))
    services = api.client.app.state.services
    stored = services.attachment.file_path(board["id"], uploaded["stored_filename"])
    assert stored.exists()

    backup = api.data(api.post(f"/api/v1/boards/{board['id']}/backups"))
    assert backup["attachments"]["files"] == 1
    sidecar = services.backup._attachments_sidecar(
        board["id"], services.backup._directory(board["id"]) / backup["name"]
    )
    assert sidecar.exists()

    listed = api.data(api.get(f"/api/v1/boards/{board['id']}/backups"))
    assert listed[0]["has_attachments"] is True
    assert listed[0]["attachments_size_bytes"] > 0

    # Lose the file, then restore: the snapshot brings it back with the database.
    stored.unlink()
    assert not stored.exists()
    restored = api.data(
        api.post(f"/api/v1/boards/{board['id']}/backups/{backup['name']}/restore")
    )
    assert restored["attachments"] == {"restored": 1, "skipped": False}
    assert stored.read_bytes() == b"# hello"


def test_pruning_removes_a_snapshot_with_its_files(api: Api, board: dict[str, Any]) -> None:
    services = api.client.app.state.services
    directory = services.backup._directory(board["id"])
    directory.mkdir(parents=True, exist_ok=True)
    for index in (1, 2):
        (directory / f"backup-2026010{index}T000000Z.sqlite").write_bytes(b"db")
        (directory / f"backup-2026010{index}T000000Z-attachments.zip").write_bytes(b"zip")

    removed = services.backup.prune(board["id"], 1)
    assert removed == ["backup-20260101T000000Z.sqlite"]
    assert sorted(file.name for file in directory.iterdir()) == [
        "backup-20260102T000000Z-attachments.zip",
        "backup-20260102T000000Z.sqlite",
    ]


def test_an_export_and_import_keep_the_uploaded_files(api: Api, board: dict[str, Any]) -> None:
    loop = loop_id(api, board["id"])
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop}/lists"))
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop}/cards",
            json={"list_id": lists[0]["id"], "title": "Export me"},
        )
    )
    uploaded = api.data(_upload_attachment(api, board["id"], card["id"], "spec.md", b"body"))
    archive = api.get(f"/api/v1/boards/{board['id']}/export").content

    imported = api.data(api.post("/api/v1/boards/import", content=archive))
    services = api.client.app.state.services
    restored = services.attachment.file_path(imported["id"], uploaded["stored_filename"])
    assert restored.read_bytes() == b"body"
    rows = api.data(api.get(f"/api/v1/boards/{imported['id']}/attachments"))
    assert [entry["original_filename"] for entry in rows] == ["spec.md"]


def test_restore_says_when_the_snapshot_has_no_file_archive(
    api: Api, board: dict[str, Any], settings: Any
) -> None:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": lists[0]["id"], "title": "Has a file"},
        )
    )
    _upload_attachment(api, board["id"], card["id"], "notes.txt", b"board file body")
    snapshot = api.data(api.post(f"/api/v1/boards/{board['id']}/backups"))["name"]

    sidecar_name = snapshot.replace(".sqlite", "-attachments.zip")
    sidecar = Path(settings.data_dir) / "backups" / board["id"] / sidecar_name
    assert sidecar.exists()
    sidecar.unlink()

    restored = api.data(
        api.post(f"/api/v1/boards/{board['id']}/backups/{snapshot}/restore")
    )
    assert restored["attachments"]["skipped"] is True
    assert restored["attachments"]["reason"] == "snapshot_has_no_file_archive"
    assert "warning" in restored
    # The files were kept rather than silently dropped, which is what the warning promises.
    files = api.data(api.get(f"/api/v1/boards/{board['id']}/attachments?card_id={card['id']}"))
    assert [item["original_filename"] for item in files] == ["notes.txt"]
