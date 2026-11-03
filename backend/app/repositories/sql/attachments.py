"""``AttachmentRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import ATTACHMENTS_COLUMNS, AttachmentsRow

_ATTACHMENT = (
    f"SELECT {sql.column_list(ATTACHMENTS_COLUMNS)}"  # noqa: S608 - from ATTACHMENTS_COLUMNS
    " FROM attachments"
)
_LIVE = text(f"{_ATTACHMENT} WHERE deleted_at IS NULL ORDER BY created_at")
_LIVE_FOR_CARD = text(
    f"{_ATTACHMENT} WHERE deleted_at IS NULL AND card_id = :card_id ORDER BY created_at"
)
_GET_LIVE = text(f"{_ATTACHMENT} WHERE id = :id AND deleted_at IS NULL")
_LIVE_SIZE = text(
    "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM attachments WHERE deleted_at IS NULL"
)
_ADD = text(
    "INSERT INTO attachments"
    " (id, card_id, discussion_id, message_id, original_filename, stored_filename,"
    "  content_type, size_bytes, sha256, uploaded_by_actor_id, created_at, deleted_at)"
    " VALUES (:id, :card_id, :discussion_id, :message_id, :original_filename, :stored_filename,"
    "         :content_type, :size_bytes, :sha256, :uploaded_by_actor_id, :created_at,"
    "         :deleted_at)"
)
_MARK_DELETED = text("UPDATE attachments SET deleted_at = :now WHERE id = :id")


class SqlAttachmentRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def live(self, *, card_id: str | None) -> list[AttachmentsRow]:
        if card_id is None:
            result = self._connection.execute(_LIVE)
        else:
            result = self._connection.execute(_LIVE_FOR_CARD, {"card_id": card_id})
        return [AttachmentsRow.from_mapping(row) for row in result.mappings()]

    def get_live(self, attachment_id: str) -> AttachmentsRow | None:
        row = self._connection.execute(_GET_LIVE, {"id": attachment_id}).mappings().first()
        return None if row is None else AttachmentsRow.from_mapping(row)

    def live_size(self) -> int:
        row = self._connection.execute(_LIVE_SIZE).mappings().one()
        return values.integer(row, "total")

    def add(self, row: AttachmentsRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "card_id": row.card_id,
                "discussion_id": row.discussion_id,
                "message_id": row.message_id,
                "original_filename": row.original_filename,
                "stored_filename": row.stored_filename,
                "content_type": row.content_type,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
                "uploaded_by_actor_id": row.uploaded_by_actor_id,
                "created_at": row.created_at,
                "deleted_at": row.deleted_at,
            },
        )

    def mark_deleted(self, attachment_id: str, *, now: str) -> None:
        self._connection.execute(_MARK_DELETED, {"now": now, "id": attachment_id})
