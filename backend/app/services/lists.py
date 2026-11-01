from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..schemas.lists import ListCreate, ListMove, ListUpdate
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import one, position_for_index, rows


class ListService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards

    def _row(self, conn: Any, list_id: str, board_id: str) -> dict[str, Any]:
        row = one(conn, "SELECT * FROM lists WHERE id = :id", {"id": list_id})
        if row is None:
            raise NotFound("List not found")
        del board_id
        return row

    def serialize(self, board_id: str, row: dict[str, Any], card_count: int = 0) -> dict[str, Any]:
        entry = dict(row)
        entry["board_id"] = board_id
        entry["card_count"] = card_count
        return entry

    def list(self, board_id: str, *, include_archived: bool = False) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        clause = "" if include_archived else " WHERE archived_at IS NULL"
        with self.boards.reader(board_id) as conn:
            lists = rows(conn, f"SELECT * FROM lists{clause} ORDER BY position, id")
            counts = {
                row["list_id"]: int(row["total"])
                for row in rows(
                    conn,
                    "SELECT list_id, COUNT(*) AS total FROM cards WHERE archived_at IS NULL"
                    " GROUP BY list_id",
                )
            }
        return [self.serialize(board_id, row, counts.get(row["id"], 0)) for row in lists]

    def get(self, board_id: str, list_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            row = self._row(conn, list_id, board_id)
            count = conn.execute(
                text("SELECT COUNT(*) FROM cards WHERE list_id = :id AND archived_at IS NULL"),
                {"id": list_id},
            ).scalar_one()
        return self.serialize(board_id, row, int(count))

    def create(self, actor: ActorContext, board_id: str, payload: ListCreate) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        list_id = str(uuid4())
        now = utcnow()
        with self.boards.session(board_id) as conn:
            position = position_for_index(
                conn, "lists", "archived_at IS NULL", {}, payload.position
            )
            conn.execute(
                text(
                    "INSERT INTO lists (id, name, position, created_at, updated_at)"
                    " VALUES (:id, :name, :position, :now, :now)"
                ),
                {"id": list_id, "name": payload.name, "position": position, "now": now},
            )
            log_activity(
                conn,
                actor,
                action="list.created",
                entity_type="list",
                entity_id=list_id,
                changes={"name": payload.name},
            )
            row = self._row(conn, list_id, board_id)
        return self.serialize(board_id, row)

    def update(
        self, actor: ActorContext, board_id: str, list_id: str, payload: ListUpdate
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self._row(conn, list_id, board_id)
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
            row = self._row(conn, list_id, board_id)
        return self.serialize(board_id, row)

    def move(
        self, actor: ActorContext, board_id: str, list_id: str, payload: ListMove
    ) -> list[dict[str, Any]]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            self._row(conn, list_id, board_id)
            position = position_for_index(
                conn,
                "lists",
                "archived_at IS NULL AND id != :id",
                {"id": list_id},
                payload.position,
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
        return self.list(board_id)

    def archive(self, actor: ActorContext, board_id: str, list_id: str) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self._row(conn, list_id, board_id)
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
            row = self._row(conn, list_id, board_id)
        return self.serialize(board_id, row)

    def restore(self, actor: ActorContext, board_id: str, list_id: str) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            existing = self._row(conn, list_id, board_id)
            if existing["archived_at"] is not None:
                position = position_for_index(conn, "lists", "archived_at IS NULL", {}, None)
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
            row = self._row(conn, list_id, board_id)
        return self.serialize(board_id, row)

    def delete(self, actor: ActorContext, board_id: str, list_id: str) -> None:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self._row(conn, list_id, board_id)
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
            conn.execute(text("DELETE FROM lists WHERE id = :id"), {"id": list_id})
            log_activity(
                conn,
                actor,
                action="list.deleted",
                entity_type="list",
                entity_id=list_id,
                changes={"name": existing["name"]},
            )
