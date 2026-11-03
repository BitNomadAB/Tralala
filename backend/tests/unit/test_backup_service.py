"""BackupService and BackupScheduler on fakes: snapshots are files named by their UTC moment, a
refused snapshot never touches the board, pruning only ever deletes this service's own files, and
the scheduler backs up the active boards that are due."""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.context import ActorContext
from app.core.errors import Forbidden, NotFound, ValidationFailure
from app.core.integrity import SnapshotProblem
from app.repositories.backups import BoardHealth, BoardSnapshots, FileVerification
from app.services.backup_scheduler import Backups, BackupScheduler
from app.services.backups import BackupCreated, BackupService, BoardChecks, is_backup_name
from app.services.boards import BoardService
from tests.unit.fakes.board import BOARD_ID, FakeBoardChecks
from tests.unit.fakes.board_files import FakeBoardDatabases, as_files
from tests.unit.fakes.registry import RegistryState, board_row, registry_unit_of_work

MOMENT = datetime(2026, 11, 3, 10, 0, 0, tzinfo=UTC)
ADMIN = ActorContext(
    actor_id="actor-1",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"boards:write", "boards:admin"}),
)
WRITER = ActorContext(
    actor_id="actor-2", actor_type="user", actor_name="Bo", scopes=frozenset({"boards:write"})
)


def board_service_is_what_backups_need(service: BoardService) -> BoardChecks:
    """Never called: pyright proves that the BoardService wired in Services fits BoardChecks."""
    return service


def backup_service_is_what_the_scheduler_needs(service: BackupService) -> Backups:
    """Never called: pyright proves that BackupService fits the scheduler's Protocol."""
    return service


@dataclass
class FakeSnapshots:
    """The database side over the fake files: a snapshot is accepted unless listed as refused."""

    databases: FakeBoardDatabases
    refused: dict[str, SnapshotProblem] = field(default_factory=dict[str, SnapshotProblem])
    restored: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    violations: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    closed: list[str] = field(default_factory=list[str])

    def exists(self, board_id: str) -> bool:
        return self.databases.path(board_id).exists()

    def close(self, board_id: str) -> None:
        self.closed.append(board_id)

    def check_snapshot(self, source: Path) -> SnapshotProblem | None:
        return self.refused.get(source.name)

    def restore_snapshot(self, source: Path, board_id: str) -> None:
        self.restored.append((source.name, board_id))
        self.databases.path(board_id).write_bytes(source.read_bytes())

    def verify_file(self, path: Path) -> FileVerification:
        return {"integrity": "ok", "ok": path.exists()}

    def health(self, board_id: str) -> BoardHealth:
        del board_id
        return {
            "integrity": "ok",
            "foreign_key_violations": list(self.violations),
            "schema_version": 12,
            "schema_revision": "0012_referenced_table_keys",
            "counts": {"lists": 0},
        }


def as_snapshots(snapshots: FakeSnapshots) -> BoardSnapshots:
    return snapshots


class Clock:
    def __init__(self) -> None:
        self.moment = MOMENT

    def __call__(self) -> datetime:
        return self.moment


def make(
    tmp_path: Path,
) -> tuple[BackupService, FakeBoardDatabases, FakeSnapshots, FakeBoardChecks, Clock]:
    databases = FakeBoardDatabases(root=tmp_path / "boards")
    databases.create_database(BOARD_ID, "")
    snapshots = FakeSnapshots(databases)
    checks = FakeBoardChecks()
    clock = Clock()
    service = BackupService(
        checks,
        as_files(databases),
        as_snapshots(snapshots),
        backups_dir=tmp_path / "backups",
        file_profile="posix",
        now=clock,
    )
    return service, databases, snapshots, checks, clock


def test_only_this_services_names_are_backups() -> None:
    assert is_backup_name("backup-20261103T100000Z.sqlite")
    assert is_backup_name("backup-20261103T100000Z-before-migration.sqlite")
    assert not is_backup_name("backup-20261103T100000Z.sqlite\n")
    assert not is_backup_name("my-copy.sqlite")
    arabic_digits = "".join(chr(0x660 + int(digit)) for digit in "20261103")
    assert not is_backup_name(f"backup-{arabic_digits}T100000Z.sqlite")


def test_create_names_the_snapshot_by_its_utc_moment_and_verifies_it(tmp_path: Path) -> None:
    service, _, _, checks, _ = make(tmp_path)
    created = service.create(WRITER, BOARD_ID)
    assert created["name"] == "backup-20261103T100000Z.sqlite"
    assert created["created_at"] == "2026-11-03T10:00:00Z"
    assert created["verification"] == {"integrity": "ok", "ok": True}
    assert created["attachments"] == {"files": 0, "size_bytes": 0}
    assert ("ensure_active", BOARD_ID) in checks.calls


def test_create_archives_the_attachments_next_to_the_snapshot(tmp_path: Path) -> None:
    service, databases, _, _, _ = make(tmp_path)
    files = databases.attachments_dir(BOARD_ID)
    files.mkdir(parents=True)
    (files / "a.txt").write_text("alpha", encoding="utf-8")
    created = service.create(WRITER, BOARD_ID)
    assert created["attachments"]["files"] == 1
    sidecar = tmp_path / "backups" / BOARD_ID / "backup-20261103T100000Z-attachments.zip"
    with zipfile.ZipFile(sidecar) as archive:
        assert archive.namelist() == ["attachments/a.txt"]


def test_a_backup_is_one_boards_files_and_never_holds_a_repository_mirror(tmp_path: Path) -> None:
    """``tmp_path`` is the data directory. ``<data>/repos`` caches the repositories' Git mirrors:
    a backup is per board (its database and its attachments), so it writes beside the board's other
    backups only, and nothing under ``repos/`` is in it or touched by it."""
    service, databases, _, _, _ = make(tmp_path)
    attachments = databases.attachments_dir(BOARD_ID)
    attachments.mkdir(parents=True)
    (attachments / "a.txt").write_text("alpha", encoding="utf-8")
    mirror = tmp_path / "repos" / "8c1f6c5e-2b7d-4e8a-9f3c-0d1e2f3a4b5c" / "mirror.git"
    mirror.mkdir(parents=True)
    (mirror / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    (mirror.parent / "state.json").write_bytes(b"{}\n")

    def tree() -> dict[str, bytes]:
        return {
            path.relative_to(tmp_path).as_posix(): path.read_bytes()
            for path in tmp_path.rglob("*")
            if path.is_file()
        }

    before = tree()
    service.create(WRITER, BOARD_ID)
    after = tree()
    written = sorted(set(after) - set(before))
    assert written == [
        f"backups/{BOARD_ID}/backup-20261103T100000Z-attachments.zip",
        f"backups/{BOARD_ID}/backup-20261103T100000Z.sqlite",
    ]
    assert {name: after[name] for name in before} == before
    with zipfile.ZipFile(tmp_path / written[0]) as archive:
        assert archive.namelist() == ["attachments/a.txt"]
    assert b"refs/heads" not in after[written[1]]


def test_create_needs_the_board_write_scope(tmp_path: Path) -> None:
    service, _, _, _, _ = make(tmp_path)
    reader = ActorContext(actor_id="r", actor_type="agent", actor_name="R", scopes=frozenset())
    with pytest.raises(Forbidden):
        service.create(reader, BOARD_ID)


def test_list_answers_newest_first_with_the_sidecar(tmp_path: Path) -> None:
    service, _, _, _, clock = make(tmp_path)
    service.create(WRITER, BOARD_ID)
    clock.moment = MOMENT + timedelta(hours=1)
    service.create(WRITER, BOARD_ID)
    names = [entry["name"] for entry in service.list(BOARD_ID)]
    assert names == ["backup-20261103T110000Z.sqlite", "backup-20261103T100000Z.sqlite"]


def test_prune_keeps_the_newest_and_never_touches_a_hand_made_copy(tmp_path: Path) -> None:
    service, _, _, _, clock = make(tmp_path)
    for hour in range(3):
        clock.moment = MOMENT + timedelta(hours=hour)
        service.create(WRITER, BOARD_ID)
    (tmp_path / "backups" / BOARD_ID / "my-copy.sqlite").write_bytes(b"mine")
    removed = service.prune(BOARD_ID, 1)
    assert removed == ["backup-20261103T100000Z.sqlite", "backup-20261103T110000Z.sqlite"]
    left = sorted(path.name for path in (tmp_path / "backups" / BOARD_ID).iterdir())
    assert left == ["backup-20261103T120000Z.sqlite", "my-copy.sqlite"]
    assert service.prune(BOARD_ID, 0) == []


def test_newest_age_is_measured_from_the_newest_snapshot(tmp_path: Path) -> None:
    service, _, _, _, clock = make(tmp_path)
    assert service.newest_age_hours(BOARD_ID) is None
    service.create(WRITER, BOARD_ID)
    snapshot = tmp_path / "backups" / BOARD_ID / "backup-20261103T100000Z.sqlite"
    stamp = MOMENT.timestamp()
    os.utime(snapshot, (stamp, stamp))
    clock.moment = MOMENT + timedelta(hours=5)
    assert service.newest_age_hours(BOARD_ID) == pytest.approx(5.0)


def test_restore_refuses_a_name_this_service_did_not_write(tmp_path: Path) -> None:
    service, _, snapshots, _, _ = make(tmp_path)
    with pytest.raises(ValidationFailure):
        service.restore(ADMIN, BOARD_ID, "../board.sqlite")
    with pytest.raises(NotFound):
        service.restore(ADMIN, BOARD_ID, "backup-20261103T100000Z.sqlite")
    assert snapshots.restored == []


def test_a_refused_snapshot_never_touches_the_board(tmp_path: Path) -> None:
    service, databases, snapshots, _, _ = make(tmp_path)
    name = service.create(WRITER, BOARD_ID)["name"]
    before = databases.path(BOARD_ID).read_bytes()
    snapshots.refused[name] = SnapshotProblem(
        reason="foreign_key_check_failed", detail="cards rowid 1 -> lists"
    )
    with pytest.raises(ValidationFailure) as refused:
        service.restore(ADMIN, BOARD_ID, name)
    assert refused.value.code == "board_backup_invalid"
    assert refused.value.details == {
        "name": name,
        "reason": "foreign_key_check_failed",
        "detail": "cards rowid 1 -> lists",
    }
    assert snapshots.restored == []
    assert databases.path(BOARD_ID).read_bytes() == before


def test_restore_replaces_the_database_under_the_lock_and_reports_its_health(
    tmp_path: Path,
) -> None:
    service, databases, snapshots, _, _ = make(tmp_path)
    name = service.create(WRITER, BOARD_ID)["name"]
    restored = service.restore(ADMIN, BOARD_ID, name)
    assert snapshots.restored == [(name, BOARD_ID)]
    assert snapshots.closed == [BOARD_ID, BOARD_ID]
    assert databases.locked_boards == [BOARD_ID]
    assert restored["verification"]["ok"] is True
    # The snapshot had no attachments archive, so the board's files stayed and the answer says so.
    assert restored["attachments"] == {
        "restored": 0,
        "skipped": True,
        "reason": "snapshot_has_no_file_archive",
    }
    assert "warning" in restored


def test_restore_needs_the_board_admin_scope(tmp_path: Path) -> None:
    service, _, _, _, _ = make(tmp_path)
    with pytest.raises(Forbidden):
        service.restore(WRITER, BOARD_ID, "backup-20261103T100000Z.sqlite")


def test_validate_reports_a_broken_reference_as_not_ok(tmp_path: Path) -> None:
    service, _, snapshots, _, _ = make(tmp_path)
    assert service.validate(BOARD_ID)["ok"] is True
    snapshots.violations.append({"table": "cards", "rowid": 1, "parent": "lists"})
    assert service.validate(BOARD_ID)["ok"] is False


# --- the scheduler -------------------------------------------------------------------------------


@dataclass
class FakeBackups:
    ages: dict[str, float | None] = field(default_factory=dict[str, float | None])
    failing: set[str] = field(default_factory=set[str])
    created: list[str] = field(default_factory=list[str])

    def newest_age_hours(self, board_id: str) -> float | None:
        return self.ages.get(board_id)

    def create(self, actor: ActorContext, board_id: str) -> BackupCreated:
        del actor
        if board_id in self.failing:
            raise OSError("disk full")
        self.created.append(board_id)
        return {
            "name": f"backup-{board_id}.sqlite",
            "size_bytes": 1,
            "attachments": {"files": 0, "size_bytes": 0},
            "created_at": "2026-11-03T10:00:00Z",
            "verification": {"integrity": "ok", "ok": True},
        }

    def prune(self, board_id: str, keep: int) -> list[str]:
        del board_id, keep
        return []


def scheduler(backups: FakeBackups, *, interval_hours: int = 24) -> BackupScheduler:
    state = RegistryState()
    for board_id, name, status in (
        ("b-2", "Beta", "active"),
        ("b-1", "Alpha", "active"),
        ("b-3", "Gamma", "archived"),
    ):
        state.boards[board_id] = board_row(board_id, name=name, status=status)
    return BackupScheduler(
        backups, store=registry_unit_of_work(state), interval_hours=interval_hours, keep=3
    )


def test_the_scheduler_backs_up_active_boards_that_are_due_by_name() -> None:
    backups = FakeBackups(ages={"b-1": None, "b-2": 30.0})
    report = scheduler(backups).run_once()
    assert backups.created == ["b-1", "b-2"]
    assert [entry["board_id"] for entry in report["created"]] == ["b-1", "b-2"]


def test_the_scheduler_skips_a_board_backed_up_within_the_interval() -> None:
    backups = FakeBackups(ages={"b-1": 2.0, "b-2": None})
    scheduler(backups).run_once()
    assert backups.created == ["b-2"]


def test_one_failing_board_does_not_stop_the_others() -> None:
    backups = FakeBackups(failing={"b-1"})
    report = scheduler(backups).run_once()
    assert backups.created == ["b-2"]
    assert report["failed"] == [{"board_id": "b-1", "error": "OSError"}]


def test_a_disabled_scheduler_does_nothing() -> None:
    backups = FakeBackups()
    assert scheduler(backups, interval_hours=0).run_once() == {
        "created": [],
        "pruned": [],
        "failed": [],
    }
    assert backups.created == []
