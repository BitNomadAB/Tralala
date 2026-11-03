"""Loop-owned Kanban columns.

Columns belong to exactly one Loop. Ordering, counts, reorder normalization and archive queries
are all scoped to that Loop, so two Loops in one Board never share or reorder each other's lists.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core import sql
from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..schemas.lists import ListCreate, ListMove, ListUpdate
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import one, position_for_index, rows

# What the list query formats into SQL text (see core/sql.py).
_LIST_FILTERS: sql.Filters = (("loop", "loop_id = :loop_id"), ("unarchived", "archived_at IS NULL"))


class ListService:
    def __init__(self, board_service: BoardService, loop_service: Any | None = None) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.loops = loop_service

    def _loop_row(self, conn: Any, board_id: str, loop_id: str) -> dict[str, Any]:
        if self.loops is None:
            raise NotFound("Loop not found", code="loop_not_found")
        return self.loops.require_loop_row(conn, board_id, loop_id)

    def _row(self, conn: Any, board_id: str, loop_id: str, list_id: str) -> dict[str, Any]:
        row = one(conn, "SELECT * FROM lists WHERE id = :id", {"id": list_id})
        if row is None:
            raise NotFound("List not found")
        if row["loop_id"] != loop_id:
            raise Conflict(
                "The list belongs to another Loop",
                code="loop_mismatch",
                details={"loop_id": loop_id, "list_loop_id": row["loop_id"]},
            )
        del board_id
        return row

    def serialize(self, board_id: str, row: dict[str, Any], card_count: int = 0) -> dict[str, Any]:
        entry = dict(row)
        entry["board_id"] = board_id
        entry["card_count"] = card_count
        return entry

    def list(
        self, board_id: str, loop_id: str, *, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        where = sql.where(_LIST_FILTERS, ["loop"] if include_archived else ["loop", "unarchived"])
        with self.boards.reader(board_id) as conn:
            self._loop_row(conn, board_id, loop_id)
            lists = rows(
                conn,
                "SELECT * FROM lists"  # noqa: S608 - from _LIST_FILTERS
                f"{where} ORDER BY position, id",
                {"loop_id": loop_id},
            )
            counts = {
                row["list_id"]: int(row["total"])
                for row in rows(
                    conn,
                    "SELECT list_id, COUNT(*) AS total FROM cards WHERE loop_id = :loop_id"
                    " AND archived_at IS NULL GROUP BY list_id",
                    {"loop_id": loop_id},
                )
            }
        return [self.serialize(board_id, row, counts.get(row["id"], 0)) for row in lists]

    def get(self, board_id: str, loop_id: str, list_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            self._loop_row(conn, board_id, loop_id)
            row = self._row(conn, board_id, loop_id, list_id)
            count = conn.execute(
                text("SELECT COUNT(*) FROM cards WHERE list_id = :id AND archived_at IS NULL"),
                {"id": list_id},
            ).scalar_one()
        return self.serialize(board_id, row, int(count))

    def create(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: ListCreate
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        list_id = str(uuid4())
        now = utcnow()
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            position = position_for_index(conn, "lists", {"loop_id": loop_id}, payload.position)
            conn.execute(
                text(
                    "INSERT INTO lists (id, loop_id, name, position, created_at, updated_at)"
                    " VALUES (:id, :loop_id, :name, :position, :now, :now)"
                ),
                {
                    "id": list_id,
                    "loop_id": loop_id,
                    "name": payload.name,
                    "position": position,
                    "now": now,
                },
            )
            log_activity(
                conn,
                actor,
                action="list.created",
                entity_type="list",
                entity_id=list_id,
                changes={"name": payload.name, "loop_id": loop_id},
            )
            row = self._row(conn, board_id, loop_id, list_id)
        return self.serialize(board_id, row)

    def update(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        list_id: str,
        payload: ListUpdate,
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._row(conn, board_id, loop_id, list_id)
            if payload.name is None:
                return self.serialize(board_id, existing)
            conn.execute(
                text("UPDATE lists SET name = :name, updated_at = :now WHERE id = :id"),
                {"name": payload.name, "now": utcnow(), "id": list_id},
            )
            log_activity(
                conn,
                actor,
                action="list.renamed",
                entity_type="list",
                entity_id=list_id,
                changes={"before": existing["name"], "after": payload.name},
            )
            row = self._row(conn, board_id, loop_id, list_id)
        return self.serialize(board_id, row)

    def move(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        list_id: str,
        payload: ListMove,
    ) -> list[dict[str, Any]]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            self._row(conn, board_id, loop_id, list_id)
            position = position_for_index(
                conn, "lists", {"loop_id": loop_id}, payload.position, exclude=list_id
            )
            conn.execute(
                text("UPDATE lists SET position = :position, updated_at = :now WHERE id = :id"),
                {"position": position, "now": now, "id": list_id},
            )
            log_activity(
                conn,
                actor,
                action="list.moved",
                entity_type="list",
                entity_id=list_id,
                changes={"position": payload.position},
            )
        return self.list(board_id, loop_id)

    def archive(
        self, actor: ActorContext, board_id: str, loop_id: str, list_id: str
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._row(conn, board_id, loop_id, list_id)
            if existing["archived_at"] is None:
                conn.execute(
                    text("UPDATE lists SET archived_at = :now, updated_at = :now WHERE id = :id"),
                    {"now": utcnow(), "id": list_id},
                )
            log_activity(
                conn,
                actor,
                action="list.archived",
                entity_type="list",
                entity_id=list_id,
            )
            row = self._row(conn, board_id, loop_id, list_id)
        return self.serialize(board_id, row)

    def restore(
        self, actor: ActorContext, board_id: str, loop_id: str, list_id: str
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._row(conn, board_id, loop_id, list_id)
            if existing["archived_at"] is not None:
                position = position_for_index(conn, "lists", {"loop_id": loop_id}, None)
                conn.execute(
                    text(
                        "UPDATE lists SET archived_at = NULL, position = :position,"
                        " updated_at = :now WHERE id = :id"
                    ),
                    {"position": position, "now": now, "id": list_id},
                )
            log_activity(
                conn,
                actor,
                action="list.restored",
                entity_type="list",
                entity_id=list_id,
            )
            row = self._row(conn, board_id, loop_id, list_id)
        return self.serialize(board_id, row)

    def delete(self, actor: ActorContext, board_id: str, loop_id: str, list_id: str) -> None:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._row(conn, board_id, loop_id, list_id)
            if existing["archived_at"] is None:
                raise Conflict("Archive the list before deleting it")
            active_cards = conn.execute(
                text("SELECT COUNT(*) FROM cards WHERE list_id = :id AND archived_at IS NULL"),
                {"id": list_id},
            ).scalar_one()
            if active_cards:
                raise ValidationFailure(
                    "Archive or move the cards in this list before deleting it",
                    details={"active_cards": int(active_cards)},
                )
            required = conn.execute(
                text(
                    "SELECT COUNT(*) FROM cards WHERE list_id = :id AND plan_item_id IS NOT NULL"
                ),
                {"id": list_id},
            ).scalar_one()
            if required:
                raise Conflict(
                    "This column still holds planned Tickets; keep them traceable",
                    code="plan_change_required",
                    details={"planned_cards": int(required)},
                )
            conn.execute(text("DELETE FROM lists WHERE id = :id"), {"id": list_id})
            log_activity(
                conn,
                actor,
                action="list.deleted",
                entity_type="list",
                entity_id=list_id,
                changes={"name": existing["name"]},
            )

    @staticmethod
    def _require_writable(loop: dict[str, Any]) -> None:
        if loop["completed_at"] is not None or loop["stage"] == "completed":
            raise Conflict(
                "This Loop is completed and read-only",
                code="loop_read_only",
                details={"loop_id": loop["id"]},
            )
        if loop["archived_at"] is not None or loop["cancelled_at"] is not None:
            raise Conflict(
                "This Loop is not editable",
                code="loop_read_only",
                details={"loop_id": loop["id"]},
            )
