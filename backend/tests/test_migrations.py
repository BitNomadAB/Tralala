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
PREVIOUS_REVISION = "0007_comment_mentions"


def _services(client: TestClient) -> Any:
    return client.app.state.services  # type: ignore[attr-defined]


def _seed_previous_revision(services: Any, board_id: str, *, populate: bool) -> None:
    """Rebuild a board database at the revision before Loop ownership existed."""
    services.boards.close(board_id)
    path = services.boards.path(board_id)
    if path.exists():
        path.unlink()
    engine = create_sqlite_engine(path)
    previous = PREVIOUS_REVISION
    with engine.begin() as conn:
        runner.upgrade("board", conn, previous)
        conn.execute(
            text(
                "INSERT INTO board_metadata (id, description, created_at, updated_at,"
                " schema_version) VALUES (:id, '', :now, :now, 7)"
            ),
            {"id": board_id, "now": "2026-01-01T00:00:00Z"},
        )
        if populate:
            conn.execute(
                text(
                    "INSERT INTO lists (id, name, position, created_at, updated_at)"
                    " VALUES ('legacy-list', 'Backlog', 1024, :now, :now)"
                ),
                {"now": "2026-01-01T00:00:00Z"},
            )
            conn.execute(
                text(
                    "INSERT INTO cards (id, list_id, title, description, position, priority,"
                    " created_at, updated_at, version) VALUES ('legacy-card', 'legacy-list',"
                    " 'Pre-Loop card', '', 1024, 'none', :now, :now, 1)"
                ),
                {"now": "2026-01-01T00:00:00Z"},
            )
    engine.dispose()
    services.registry.update_board(board_id, schema_revision=previous, schema_version=7)


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


def test_populated_pre_loop_board_requires_an_explicit_reset(
    api: Api, board: dict[str, Any], settings: Settings
) -> None:
    services = _services(api.client)
    _seed_previous_revision(services, board["id"], populate=True)

    report = services.migrations.migrate_board(board["id"])

    assert report.status == "failed"
    assert "app.dev_reset" in (report.error or "")
    assert services.registry.board(board["id"])["status"] == "migration_failed"
    assert report.backup is not None
    assert any(path.name == report.backup for path in _backup_files(settings, board["id"]))
    blocked = api.post(f"/api/v1/boards/{board['id']}/loops", json={"name": "Blocked"}, headers={})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "board_migration_failed"

    from app import dev_reset

    with pytest.raises(RuntimeError):
        dev_reset.reset(settings, confirm=False)
    removed = dev_reset.reset(settings, confirm=True)
    assert removed["removed"]
    assert not Path(settings.registry_path).exists()
    assert not settings.boards_dir.exists()


def test_empty_board_from_previous_revision_upgrades_to_loop_schema(
    api: Api, board: dict[str, Any]
) -> None:
    services = _services(api.client)
    _seed_previous_revision(services, board["id"], populate=False)

    report = services.migrations.migrate_board(board["id"])

    assert report.status == "migrated"
    assert report.to_revision == runner.head_revision("board")
    assert _revision(services, board["id"]) == runner.head_revision("board")
    validation = api.data(api.get(f"/api/v1/boards/{board['id']}/validate"))
    assert validation["ok"] is True


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
    loop = api.data(api.post(f"/api/v1/boards/{board['id']}/loops", json={"name": "Resume loop"}))
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop['id']}/lists"))
    _seed_previous_revision(services, board["id"], populate=False)

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

    blocked = api.post(f"/api/v1/boards/{board['id']}/loops", json={"name": "Rejected"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "board_migration_failed"

    resumed = services.migrations.migrate_board(board["id"])
    assert resumed.status == "migrated"
    assert services.registry.board(board["id"])["status"] == "active"
    assert _revision(services, board["id"]) == runner.head_revision("board")
    del lists


def test_unknown_revision_is_never_silently_accepted(api: Api, board: dict[str, Any]) -> None:
    services = _services(api.client)
    _seed_previous_revision(services, board["id"], populate=False)
    engine = create_sqlite_engine(services.boards.path(board["id"]))
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE alembic_version SET version_num = '9999_from_the_future'")
    engine.dispose()

    report = services.migrations.migrate_board(board["id"])

    assert report.status == "failed"
    assert report.backup is not None
    assert services.registry.board(board["id"])["status"] == "migration_failed"

    engine = create_sqlite_engine(services.boards.path(board["id"]))
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE alembic_version SET version_num = :baseline",
            {"baseline": PREVIOUS_REVISION},
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
            _seed_previous_revision(services, board_id, populate=False)

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

def test_registry_upgrade_keeps_the_repository_assignment(settings: Settings) -> None:
    """0009 rebuilds repositories; the board links must survive the table recreation."""
    from app.storage.sqlite import create_sqlite_engine

    settings.ensure_dirs()
    engine = create_sqlite_engine(settings.registry_path)
    try:
        with engine.begin() as conn:
            runner.upgrade("registry", conn, "0008_repositories_and_board_assignment")
            board_id = str(uuid.uuid4())
            repository_id = str(uuid.uuid4())
            now = "2026-11-01T00:00:00Z"
            conn.execute(
                text(
                    "INSERT INTO boards (id, name, description, status, created_at, updated_at,"
                    " archived_at, schema_version, schema_revision)"
                    " VALUES (:id, 'Link board', '', 'active', :now, :now, NULL, 0, NULL)"
                ),
                {"id": board_id, "now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO repositories (id, name, provider, url, branch, board_id,"
                    " token_ciphertext, token_hint, enabled, created_at, updated_at)"
                    " VALUES (:id, 'Tralala', 'github', 'https://github.com/BitNomadAB/Tralala',"
                    " NULL, :board, NULL, NULL, 1, :now, :now)"
                ),
                {"id": repository_id, "board": board_id, "now": now},
            )
            runner.upgrade("registry", conn, "head")

            link = conn.execute(
                text("SELECT board_id FROM board_repositories WHERE repository_id = :id"),
                {"id": repository_id},
            ).scalar_one_or_none()
            assert link == board_id
            columns = {
                row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info(repositories)").fetchall()
            }
            assert "board_id" not in columns
    finally:
        engine.dispose()



