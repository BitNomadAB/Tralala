from __future__ import annotations

import re
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
            items.append(
                {
                    "name": file.name,
                    "size_bytes": stat.st_size,
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
        return {
            "name": name,
            "size_bytes": target.stat().st_size,
            "created_at": utcnow(),
            "verification": self._check_file(target),
        }

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
        report = self.validate(board_id)
        return {"restored_from": name, "board_id": board_id, "verification": report}

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
