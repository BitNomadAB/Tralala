from __future__ import annotations

import contextlib
import io
import re
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, Protocol, TypedDict

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import NotFound, ValidationFailure
from ..core.identifiers import canonical_board_id
from ..core.integrity import SNAPSHOT_REFUSALS
from ..core.platform import remove_file, retry_io
from ..repositories.backups import BoardSnapshots, FileVerification
from ..repositories.board_files import BoardFiles
from .common import archive_file_name

BACKUP_PATTERN = re.compile(r"backup-[0-9]{8}T[0-9]{6}Z(?:-[a-z0-9-]+)?\.sqlite")


def is_backup_name(name: str) -> bool:
    """Whether ``name`` is a snapshot this service wrote, and so may be restored or pruned.

    The whole name must match: ``match`` with ``$`` would also accept a trailing newline. The digits
    are ``[0-9]`` because Python's digit class also matches other scripts' digits.
    """
    return BACKUP_PATTERN.fullmatch(name) is not None


class BoardChecks(Protocol):
    def require_row(self, board_id: str) -> object: ...

    def ensure_active(self, board_id: str) -> object: ...


class BackupEntry(TypedDict):
    name: str
    size_bytes: int
    has_attachments: bool
    attachments_size_bytes: int
    created_at: str


class ArchivedFiles(TypedDict):
    files: int
    size_bytes: int


class BackupCreated(TypedDict):
    name: str
    size_bytes: int
    attachments: ArchivedFiles
    created_at: str
    verification: FileVerification


class RestoredFiles(TypedDict):
    restored: int
    skipped: bool
    reason: NotRequired[str]


class BoardValidation(TypedDict):
    board_id: str
    integrity: str
    foreign_key_violations: list[dict[str, object]]
    schema_version: int
    schema_revision: str | None
    counts: dict[str, int]
    ok: bool


class BackupRestored(TypedDict):
    restored_from: str
    board_id: str
    attachments: RestoredFiles
    verification: BoardValidation
    warning: NotRequired[str]


def _now() -> datetime:
    return datetime.now(UTC)


class BackupService:
    def __init__(
        self,
        boards: BoardChecks,
        files: BoardFiles,
        snapshots: BoardSnapshots,
        *,
        backups_dir: Path,
        file_profile: str,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self.boards = boards
        self.files = files
        self.snapshots = snapshots
        self.backups_dir = backups_dir
        self.file_profile = file_profile
        self._now = now

    def _directory(self, board_id: str) -> Path:
        return self.backups_dir / canonical_board_id(board_id)

    def list(self, board_id: str) -> list[BackupEntry]:
        self.boards.require_row(board_id)
        directory = self._directory(board_id)
        if not directory.exists():
            return []
        items: list[BackupEntry] = []
        for file in sorted(directory.glob("*.sqlite"), reverse=True):
            stat = file.stat()
            sidecar = self._attachments_sidecar(file)
            items.append(
                {
                    "name": file.name,
                    "size_bytes": stat.st_size,
                    "has_attachments": sidecar.exists(),
                    "attachments_size_bytes": sidecar.stat().st_size if sidecar.exists() else 0,
                    "created_at": iso_utc(datetime.fromtimestamp(stat.st_mtime, tz=UTC)),
                }
            )
        return items

    def create(self, actor: ActorContext, board_id: str) -> BackupCreated:
        actor.require("boards:write")
        self.boards.ensure_active(board_id)
        moment = self._now()
        name = f"backup-{moment.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}.sqlite"
        directory = self._directory(board_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        self.files.snapshot(board_id, target)
        attachments = self._archive_attachments(board_id, target)
        return {
            "name": name,
            "size_bytes": target.stat().st_size,
            "attachments": attachments,
            "created_at": iso_utc(moment),
            "verification": self.snapshots.verify_file(target),
        }

    @staticmethod
    def _attachments_sidecar(snapshot: Path) -> Path:
        """The files that belong to a snapshot, as one zip next to it."""
        return snapshot.with_name(f"{snapshot.stem}-attachments.zip")

    def _archive_attachments(self, board_id: str, snapshot: Path) -> ArchivedFiles:
        directory = self.files.attachments_dir(board_id)
        files = (
            sorted(file for file in directory.glob("*") if file.is_file())
            if directory.exists()
            else []
        )
        sidecar = self._attachments_sidecar(snapshot)
        if not files:
            if sidecar.exists():
                sidecar.unlink()
            return {"files": 0, "size_bytes": 0}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                retry_io(
                    "backup_attachment",
                    self.file_profile,
                    lambda file=file: archive.write(file, f"attachments/{file.name}"),
                )
        sidecar.write_bytes(buffer.getvalue())
        return {"files": len(files), "size_bytes": sidecar.stat().st_size}

    def _restore_attachments(self, board_id: str, snapshot_name: str) -> RestoredFiles:
        sidecar = self._attachments_sidecar(self._directory(board_id) / snapshot_name)
        if not sidecar.exists():
            # Older snapshots carry no files; existing ones are left alone rather than deleted.
            return {"restored": 0, "skipped": True, "reason": "snapshot_has_no_file_archive"}
        directory = self.files.attachments_dir(board_id)
        directory.mkdir(parents=True, exist_ok=True)
        restored = 0
        with zipfile.ZipFile(sidecar) as archive:
            for entry in archive.namelist():
                if not entry.startswith("attachments/"):
                    continue
                name = archive_file_name(entry)
                (directory / name).write_bytes(archive.read(entry))
                restored += 1
        return {"restored": restored, "skipped": False}

    def prune(self, board_id: str, keep: int) -> list[str]:
        """Delete the oldest snapshots beyond ``keep``.

        Only files ``is_backup_name`` accepts are candidates: an operator may keep a hand-made copy
        in the same directory, and this must never delete it.
        """
        self.boards.require_row(board_id)
        if keep <= 0:
            return []
        directory = self._directory(board_id)
        if not directory.exists():
            return []
        snapshots = sorted(
            file for file in directory.iterdir() if file.is_file() and is_backup_name(file.name)
        )
        # Names carry the UTC timestamp, so lexical order is chronological order.
        stale = snapshots[:-keep] if len(snapshots) > keep else []
        # Pruning is best effort: one busy snapshot must not stop the others from being removed, and
        # a failure is reported by the next listing rather than by an exception here.
        removed: list[str] = []
        for file in stale:
            try:
                if not remove_file(file, profile=self.file_profile):
                    continue
            except OSError:
                continue
            removed.append(file.name)
            sidecar = self._attachments_sidecar(file)
            if sidecar.exists():
                with contextlib.suppress(OSError):
                    remove_file(sidecar, profile=self.file_profile)
        return removed

    def newest_age_hours(self, board_id: str) -> float | None:
        """Hours since the newest snapshot, or None when the board has never been backed up."""
        items = self.list(board_id)
        if not items:
            return None
        newest = datetime.fromisoformat(items[0]["created_at"].replace("Z", "+00:00"))
        return (self._now() - newest).total_seconds() / 3600

    def restore(self, actor: ActorContext, board_id: str, name: str) -> BackupRestored:
        actor.require("boards:admin")
        self.boards.require_row(board_id)
        if not is_backup_name(name):
            raise ValidationFailure("Invalid backup name")
        source = self._directory(board_id) / name
        if not source.exists():
            raise NotFound("Backup not found")
        # Before the board is touched, so a refused snapshot leaves its database as it was.
        problem = self.snapshots.check_snapshot(source)
        if problem is not None:
            raise ValidationFailure(
                SNAPSHOT_REFUSALS[problem.reason],
                code="board_backup_invalid",
                details={"name": name, "reason": problem.reason, "detail": problem.detail},
            )
        with self.files.locked(board_id):
            self.snapshots.close(board_id)
            self.snapshots.restore_snapshot(source, board_id)
            self.snapshots.close(board_id)
            attachments = self._restore_attachments(board_id, name)
        report = self.validate(board_id)
        result: BackupRestored = {
            "restored_from": name,
            "board_id": board_id,
            "attachments": attachments,
            "verification": report,
        }
        if attachments["skipped"]:
            # Saying nothing here would let an operator believe the files came back with the
            # database. The snapshot predates the file archive, so the board keeps its files.
            result["warning"] = (
                "This snapshot has no file archive; the board's current uploaded files stayed."
            )
        return result

    def validate(self, board_id: str) -> BoardValidation:
        self.boards.require_row(board_id)
        if not self.snapshots.exists(board_id):
            raise NotFound("Board database not found")
        health = self.snapshots.health(board_id)
        return {
            "board_id": board_id,
            "integrity": health["integrity"],
            "foreign_key_violations": health["foreign_key_violations"],
            "schema_version": health["schema_version"],
            "schema_revision": health["schema_revision"],
            "counts": health["counts"],
            "ok": health["integrity"] == "ok" and not health["foreign_key_violations"],
        }
