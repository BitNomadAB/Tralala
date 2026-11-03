"""``LoopNoteRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import LOOP_NOTES_COLUMNS, LoopNotesRow

_NOTE = (
    f"SELECT {sql.column_list(LOOP_NOTES_COLUMNS)}"  # noqa: S608 - from LOOP_NOTES_COLUMNS
    " FROM loop_notes"
)
_ADD = text(
    "INSERT INTO loop_notes (id, loop_id, author_actor_id, author_actor_type, author_name,"
    " content, content_sha256, created_at) VALUES (:id, :loop_id, :author_actor_id,"
    " :author_actor_type, :author_name, :content, :content_sha256, :created_at)"
)
_LATEST = text(
    f"{_NOTE} WHERE loop_id = :id ORDER BY created_at DESC, rowid DESC LIMIT :limit"
)
_LATEST_BEFORE = text(
    f"{_NOTE} WHERE loop_id = :id AND (created_at, rowid) <"  # noqa: S608 - from LOOP_NOTES_COLUMNS
    " (SELECT created_at, rowid FROM loop_notes WHERE id = :before)"
    " ORDER BY created_at DESC, rowid DESC LIMIT :limit"
)
_FOR_LOOP = text(f"{_NOTE} WHERE loop_id = :id ORDER BY created_at, rowid")
_COUNT = text("SELECT COUNT(*) AS total FROM loop_notes WHERE loop_id = :id")
_LATEST_BY = text(
    f"{_NOTE} WHERE loop_id = :id AND author_actor_id = :actor AND content_sha256 = :sha"
    " ORDER BY created_at DESC, rowid DESC LIMIT 1"
)


class SqlLoopNoteRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, row: LoopNotesRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "loop_id": row.loop_id,
                "author_actor_id": row.author_actor_id,
                "author_actor_type": row.author_actor_type,
                "author_name": row.author_name,
                "content": row.content,
                "content_sha256": row.content_sha256,
                "created_at": row.created_at,
            },
        )

    def page(self, loop_id: str, *, limit: int, before: str | None) -> list[LoopNotesRow]:
        if before is None:
            result = self._connection.execute(_LATEST, {"id": loop_id, "limit": limit})
        else:
            result = self._connection.execute(
                _LATEST_BEFORE, {"id": loop_id, "before": before, "limit": limit}
            )
        newest_first = [LoopNotesRow.from_mapping(row) for row in result.mappings()]
        return newest_first[::-1]

    def for_loop(self, loop_id: str) -> list[LoopNotesRow]:
        result = self._connection.execute(_FOR_LOOP, {"id": loop_id}).mappings()
        return [LoopNotesRow.from_mapping(row) for row in result]

    def count(self, loop_id: str) -> int:
        row = self._connection.execute(_COUNT, {"id": loop_id}).mappings().one()
        return values.integer(row, "total")

    def latest_by(self, loop_id: str, actor_id: str, content_sha256: str) -> LoopNotesRow | None:
        row = (
            self._connection.execute(
                _LATEST_BY, {"id": loop_id, "actor": actor_id, "sha": content_sha256}
            )
            .mappings()
            .first()
        )
        return None if row is None else LoopNotesRow.from_mapping(row)
