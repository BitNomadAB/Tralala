"""``CommentRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import COMMENTS_COLUMNS, CommentsRow

_COMMENT = (
    f"SELECT {sql.column_list(COMMENTS_COLUMNS)}"  # noqa: S608 - from COMMENTS_COLUMNS
    " FROM comments"
)
_GET = text(f"{_COMMENT} WHERE id = :id")
_FOR_CARD = text(f"{_COMMENT} WHERE card_id = :id ORDER BY created_at, rowid")
_ADD = text(
    "INSERT INTO comments (id, card_id, actor_id, content, created_at, updated_at)"
    " VALUES (:id, :card_id, :actor_id, :content, :created_at, :updated_at)"
)
_EDIT = text("UPDATE comments SET content = :content, updated_at = :now WHERE id = :id")
_DELETE = text("DELETE FROM comments WHERE id = :id")


class SqlCommentRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, comment_id: str) -> CommentsRow | None:
        row = self._connection.execute(_GET, {"id": comment_id}).mappings().first()
        return None if row is None else CommentsRow.from_mapping(row)

    def for_card(self, card_id: str) -> list[CommentsRow]:
        result = self._connection.execute(_FOR_CARD, {"id": card_id}).mappings()
        return [CommentsRow.from_mapping(row) for row in result]

    def add(self, row: CommentsRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "card_id": row.card_id,
                "actor_id": row.actor_id,
                "content": row.content,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )

    def edit(self, comment_id: str, content: str, *, now: str) -> None:
        self._connection.execute(_EDIT, {"content": content, "now": now, "id": comment_id})

    def delete(self, comment_id: str) -> None:
        self._connection.execute(_DELETE, {"id": comment_id})
