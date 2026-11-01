from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import Api
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.main import create_app
from app.services.backups import BACKUP_PATTERN
from app.storage.board_db import BoardDatabaseManager
from app.storage.migration_manager import MigrationManager
from app.storage.registry import Registry
from app.storage.schema import runner
from app.storage.sqlite import create_sqlite_engine

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _services(client: TestClient) -> Any:
    return client.app.state.services  # type: ignore[attr-defined]


def _make_board_legacy(services: Any, board_id: str) -> None:
    """Turn a current board into a pre-Alembic v1 database.

    The v1 schema has no completed-at index, no assignment columns and no attachments table, so all
    later revisions have real work to do when the board is adopted.
    """
    services.boards.close(board_id)
    engine = create_sqlite_engine(services.boards.path(board_id))
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS attachments")
        for table in (
            "card_events",
            "comment_mention_jobs",
            "discussion_rounds",
            "discussion_runs",
            "discussion_events",
            "discussion_outcomes",
            "discussion_votes",
            "discussion_messages",
            "discussion_participants",
            "discussion_threads",
        ):
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        for index in (
            "ix_cards_assignee",
            "ix_attachments_card",
            "ix_attachments_discussion",
            "ix_attachments_message",
            "ix_card_events_card",
            "ix_comment_mentions_card",
            "uq_comment_mentions_once",
            "idx_cards_completed_at",
        ):
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {index}")
        for column in (
            "assignee_actor_id",
            "assignee_type",
            "assignee_name",
            "assigned_at",
            "assigned_by_actor_id",
        ):
            conn.exec_driver_sql(f"ALTER TABLE cards DROP COLUMN {column}")
        conn.exec_driver_sql("DROP TABLE alembic_version")
        conn.exec_driver_sql("PRAGMA user_version=1")
    engine.dispose()


def _revision(services: Any, board_id: str) -> str | None:
    engine = services.boards.open(board_id)
    with engine.connect() as conn:
        return runner.current_revision("board", conn)


def _backup_files(settings: Settings, board_id: str) -> list[Path]:
    directory = Path(settings.data_dir) / "backups" / board_id
    return sorted(directory.glob("*.sqlite")) if directory.exists() else []


def test_fresh_install_creates_schema_at_head(api: Api, board: dict[str, Any]) -> None:
    services = _services(api.client)
    registry_engine = services.registry.engine
    with registry_engine.connect() as conn:
        assert runner.current_revision("registry", conn) == runner.head_revision("registry")

    assert _revision(services, board["id"]) == runner.head_revision("board")

    row = services.registry.board(board["id"])
    assert row["schema_revision"] == runner.head_revision("board")
    assert row["schema_version"] == runner.revision_count("board")

    engine = services.boards.open(board["id"])
    with engine.connect() as conn:
        metadata_version = conn.execute(
            text("SELECT schema_version FROM board_metadata")
        ).scalar_one()
        index = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND name='idx_cards_completed_at'"
            )
        ).first()
    assert metadata_version == runner.revision_count("board")
    assert index is not None


def test_legacy_board_is_adopted_and_upgraded_without_data_loss(
    api: Api, board: dict[str, Any], settings: Settings
) -> None:
    services = _services(api.client)
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={"list_id": lists[0]["id"], "title": "Survives the migration"},
        )
    )
    _make_board_legacy(services, board["id"])

    report = services.migrations.migrate_board(board["id"])

    assert report.status == "migrated"
    assert report.adopted is True
    assert report.from_revision == runner.CHAIN_BASELINES["board"]
    assert report.to_revision == runner.head_revision("board")
    assert report.backup is not None
    assert any(path.name == report.backup for path in _backup_files(settings, board["id"]))

    cards = api.data(api.get(f"/api/v1/boards/{board['id']}/cards"))
    assert [card["title"] for card in cards] == ["Survives the migration"]
    assert _revision(services, board["id"]) == runner.head_revision("board")

    validation = api.data(api.get(f"/api/v1/boards/{board['id']}/validate"))
    assert validation["ok"] is True
    assert validation["schema_revision"] == runner.head_revision("board")


def test_legacy_registry_is_stamped_and_batch_migrated(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key="test-secret")
    settings.ensure_dirs()
    registry = Registry(settings)
    board_id = str(uuid.uuid4())

    with registry.engine.begin() as conn:
        runner.upgrade("registry", conn, runner.CHAIN_BASELINES["registry"])
        conn.execute(
            text(
                "INSERT INTO boards (id, name, description, status, created_at, updated_at,"
                " archived_at, schema_version)"
                " VALUES (:id, 'Legacy board', '', 'active', '2026-01-01T00:00:00Z',"
                " '2026-01-01T00:00:00Z', NULL, 1)"
            ),
            {"id": board_id},
        )
        conn.exec_driver_sql("DROP TABLE alembic_version")
        conn.exec_driver_sql("PRAGMA user_version=1")

    boards = BoardDatabaseManager(settings)
    manager = MigrationManager(settings, registry, boards)
    report = manager.migrate_registry()

    assert report.status == "migrated"
    assert report.adopted is True
    with registry.engine.connect() as conn:
        assert runner.current_revision("registry", conn) == runner.head_revision("registry")
        assert "schema_revision" in {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(boards)").fetchall()
        }
        tables = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "board_templates" in tables
        # The rebuilt CHECK constraint accepts the new state.
        conn.execute(
            text("UPDATE boards SET status = 'migration_failed' WHERE id = :id"), {"id": board_id}
        )
        conn.execute(text("UPDATE boards SET status = 'active' WHERE id = :id"), {"id": board_id})
        assert registry.board(board_id)["name"] == "Legacy board"


def test_failed_migration_marks_board_and_allows_resume(
    api: Api, board: dict[str, Any], settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = _services(api.client)
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={"list_id": lists[0]["id"], "title": "Keep me"},
        )
    )
    _make_board_legacy(services, board["id"])

    original_upgrade = runner.upgrade

    def failing_upgrade(chain: str, connection: Any, revision: str = "head") -> None:
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(runner, "upgrade", failing_upgrade)
    report = services.migrations.migrate_board(board["id"])
    monkeypatch.setattr(runner, "upgrade", original_upgrade)

    assert report.status == "failed"
    assert "simulated migration failure" in (report.error or "")
    assert services.registry.board(board["id"])["status"] == "migration_failed"
    backups = _backup_files(settings, board["id"])
    assert report.backup is not None and len(backups) == 1
    assert (Path(settings.data_dir) / "backups" / board["id"] / report.backup).exists()

    blocked = api.post(
        f"/api/v1/boards/{board['id']}/cards",
        json={"list_id": lists[0]["id"], "title": "Should be rejected"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "board_migration_failed"

    resumed = services.migrations.migrate_board(board["id"])
    assert resumed.status == "migrated"
    assert services.registry.board(board["id"])["status"] == "active"
    cards = api.data(api.get(f"/api/v1/boards/{board['id']}/cards"))
    assert [card["title"] for card in cards] == ["Keep me"]


def test_unknown_revision_is_never_silently_accepted(api: Api, board: dict[str, Any]) -> None:
    services = _services(api.client)
    _make_board_legacy(services, board["id"])
    engine = create_sqlite_engine(services.boards.path(board["id"]))
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('9999_from_the_future')")
    engine.dispose()

    report = services.migrations.migrate_board(board["id"])

    assert report.status == "failed"
    assert report.backup is not None
    assert services.registry.board(board["id"])["status"] == "migration_failed"

    engine = create_sqlite_engine(services.boards.path(board["id"]))
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE alembic_version SET version_num = :baseline",
            {"baseline": runner.CHAIN_BASELINES["board"]},
        )
    engine.dispose()

    resumed = services.migrations.migrate_board(board["id"])
    assert resumed.status == "migrated"


def test_startup_migrates_every_board_before_serving(settings: Settings) -> None:
    first_app = create_app(settings)
    with TestClient(first_app) as client:
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password"})
        csrf = client.cookies.get("tralala_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        board_ids = []
        for name in ("Startup one", "Startup two"):
            response = client.post("/api/v1/boards", json={"name": name}, headers=headers)
            assert response.status_code == 201, response.text
            board_ids.append(response.json()["data"]["id"])
        services = _services(client)
        for board_id in board_ids:
            _make_board_legacy(services, board_id)

    second_app = create_app(settings)
    with TestClient(second_app) as client:
        services = _services(client)
        for board_id in board_ids:
            assert _revision(services, board_id) == runner.head_revision("board")
            assert services.registry.board(board_id)["schema_revision"] == runner.head_revision(
                "board"
            )
        assert {report.board_id for report in services.migration_reports} == set(board_ids)


def test_migration_is_idempotent(api: Api, board: dict[str, Any], settings: Settings) -> None:
    services = _services(api.client)
    first = services.migrations.migrate_all_boards()
    backups_after_first = _backup_files(settings, board["id"])
    second = services.migrations.migrate_all_boards()
    backups_after_second = _backup_files(settings, board["id"])

    assert all(report.status in {"up_to_date", "skipped"} for report in first + second)
    assert backups_after_first == backups_after_second


def test_schema_changes_only_happen_in_migrations() -> None:
    pattern = re.compile(
        r"\b(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+INDEX|DROP\s+INDEX)\b",
        re.IGNORECASE,
    )
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        if "storage/schema/fts.py" in path.as_posix():
            continue  # optional FTS index bootstrap, not part of the schema contract
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(APP_ROOT.parent)))
    assert offenders == []


def test_backup_pattern_accepts_pre_migration_snapshots() -> None:
    assert BACKUP_PATTERN.match("backup-20260101T000000Z-pre-migration.sqlite")
    assert BACKUP_PATTERN.match("backup-20260101T000000Z-pre-migration-2.sqlite")
    assert not BACKUP_PATTERN.match("backup-pre-migration.sqlite")


def test_retry_endpoint_requires_admin_and_reports(api: Api, board: dict[str, Any]) -> None:
    response = api.post(f"/api/v1/boards/{board['id']}/migrate")
    assert response.status_code == 200
    payload = api.data(response)
    assert payload["chain"] == "board"
    assert payload["status"] in {"up_to_date", "migrated"}
    assert payload["to_revision"] == runner.head_revision("board")


def test_meta_reports_migration_heads(api: Api) -> None:
    payload = api.data(api.get("/api/v1/meta"))
    assert payload["migrations"]["registry_head"] == runner.head_revision("registry")
    assert payload["migrations"]["board_head"] == runner.head_revision("board")
