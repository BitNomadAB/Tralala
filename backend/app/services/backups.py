from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.context import ActorContext
from ..core.errors import NotFound, ValidationFailure
from ..storage.sqlite import snapshot_database, utcnow
from .boards import BoardService

BACKUP_PATTERN = re.compile(r"^backup-\d{8}T\d{6}Z(?:-[a-z0-9-]+)?\.sqlite$")


class BackupService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.settings = board_service.settings

    def _directory(self, board_id: str) -> Path:
        return self.settings.backups_dir / self.boards.validate_board_id(board_id)

    def list(self, board_id: str) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        directory = self._directory(board_id)
        if not directory.exists():
            return []
        items = []
        for file in sorted(directory.glob("*.sqlite"), reverse=True):
            stat = file.stat()
            sidecar = self._attachments_sidecar(board_id, file)
            items.append(
                {
                    "name": file.name,
                    "size_bytes": stat.st_size,
                    "has_attachments": sidecar.exists(),
                    "attachments_size_bytes": sidecar.stat().st_size if sidecar.exists() else 0,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
        return items

    def create(self, actor: ActorContext, board_id: str) -> dict[str, Any]:
        actor.require("boards:write")
        self.board_service.ensure_active(board_id)
        name = f"backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.sqlite"
        directory = self._directory(board_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        snapshot_database(self.boards.path(board_id), target)
        attachments = self._archive_attachments(board_id, target)
        return {
            "name": name,
            "size_bytes": target.stat().st_size,
            "attachments": attachments,
            "created_at": utcnow(),
            "verification": self._check_file(target),
        }

    def _attachments_sidecar(self, board_id: str, snapshot: Path) -> Path:
        """The files that belong to a snapshot, as one zip next to it."""
        return snapshot.with_name(f"{snapshot.stem}-attachments.zip")

    def _archive_attachments(self, board_id: str, snapshot: Path) -> dict[str, Any]:
        directory = self.boards.attachments_dir(board_id)
        files = (
            sorted(file for file in directory.glob("*") if file.is_file())
            if directory.exists()
            else []
        )
        sidecar = self._attachments_sidecar(board_id, snapshot)
        if not files:
            if sidecar.exists():
                sidecar.unlink()
            return {"files": 0, "size_bytes": 0}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, f"attachments/{file.name}")
        sidecar.write_bytes(buffer.getvalue())
        return {"files": len(files), "size_bytes": sidecar.stat().st_size}

    def _restore_attachments(self, board_id: str, snapshot_name: str) -> dict[str, Any]:
        sidecar = self._attachments_sidecar(board_id, self._directory(board_id) / snapshot_name)
        if not sidecar.exists():
            # Older snapshots carry no files; existing ones are left alone rather than deleted.
            return {"restored": 0, "skipped": True, "reason": "snapshot_has_no_file_archive"}
        directory = self.boards.attachments_dir(board_id)
        directory.mkdir(parents=True, exist_ok=True)
        restored = 0
        with zipfile.ZipFile(sidecar) as archive:
            for entry in archive.namelist():
                if not entry.startswith("attachments/"):
                    continue
                name = Path(entry).name
                if not name:
                    continue
                (directory / name).write_bytes(archive.read(entry))
                restored += 1
        return {"restored": restored, "skipped": False}

    def prune(self, board_id: str, keep: int) -> list[str]:
        """Delete the oldest snapshots beyond ``keep``.

        Only files matching ``BACKUP_PATTERN`` are candidates: an operator may keep a hand-made copy
        in the same directory, and this must never delete it.
        """
        self.board_service.require_row(board_id)
        if keep <= 0:
            return []
        directory = self._directory(board_id)
        if not directory.exists():
            return []
        snapshots = sorted(
            file
            for file in directory.iterdir()
            if file.is_file() and BACKUP_PATTERN.match(file.name)
        )
        # Names carry the UTC timestamp, so lexical order is chronological order.
        stale = snapshots[:-keep] if len(snapshots) > keep else []
        removed = []
        for file in stale:
            try:
                file.unlink()
                removed.append(file.name)
            except OSError:
                continue
            sidecar = self._attachments_sidecar(board_id, file)
            if sidecar.exists():
                try:
                    sidecar.unlink()
                except OSError:
                    pass
        return removed

    def newest_age_hours(self, board_id: str) -> float | None:
        """Hours since the newest snapshot, or None when the board has never been backed up."""
        items = self.list(board_id)
        if not items:
            return None
        newest = datetime.fromisoformat(items[0]["created_at"].replace("Z", "+00:00"))
        return (datetime.now(UTC) - newest).total_seconds() / 3600

    @staticmethod
    def _check_file(path: Path) -> dict[str, Any]:
        import sqlite3

        from ..storage.sqlite import connect_sqlite

        try:
            connection = connect_sqlite(path)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return {"integrity": f"unreadable: {exc}", "ok": False}
        return {"integrity": integrity, "ok": integrity == "ok"}

    def restore(self, actor: ActorContext, board_id: str, name: str) -> dict[str, Any]:
        actor.require("boards:admin")
        self.board_service.require_row(board_id)
        if not BACKUP_PATTERN.match(name):
            raise ValidationFailure("Invalid backup name")
        source = self._directory(board_id) / name
        if not source.exists():
            raise NotFound("Backup not found")
        verification = self._check_file(source)
        if not verification["ok"]:
            raise ValidationFailure(
                "Backup failed its integrity check and was not restored",
                details={"name": name, **verification},
            )
        destination = self.boards.path(board_id)
        with self.boards.locked(board_id):
            self.boards.close(board_id)
            snapshot_database(source, destination)
            self.boards.close(board_id)
            attachments = self._restore_attachments(board_id, name)
        report = self.validate(board_id)
        result: dict[str, Any] = {
            "restored_from": name,
            "board_id": board_id,
            "attachments": attachments,
            "verification": report,
        }
        if attachments.get("skipped"):
            # Saying nothing here would let an operator believe the files came back with the
            # database. The snapshot predates the file archive, so the board keeps its files.
            result["warning"] = (
                "This snapshot has no file archive; the board's current uploaded files stayed."
            )
        return result

    def validate(self, board_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        with self.boards.reader(board_id) as conn:
            integrity = conn.exec_driver_sql("PRAGMA integrity_check").scalar_one()
            foreign_keys = [
                dict(row)
                for row in conn.exec_driver_sql("PRAGMA foreign_key_check").mappings().all()
            ]
            from ..storage.schema import runner

            revision = runner.current_revision("board", conn)
            version = runner.revision_count("board")
            counts = {
                table: conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one()
                for table in (
                    "lists",
                    "cards",
                    "labels",
                    "checklists",
                    "comments",
                    "activity_log",
                )
            }
        return {
            "board_id": board_id,
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
            "schema_version": version,
            "schema_revision": revision,
            "counts": counts,
            "ok": integrity == "ok" and not foreign_keys,
        }
