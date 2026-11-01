from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Forbidden, NotFound, ValidationFailure
from ..schemas.subresources import (
    ChecklistCreate,
    ChecklistItemCreate,
    ChecklistItemUpdate,
    ChecklistUpdate,
    CommentCreate,
    LabelCreate,
    LabelUpdate,
)
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import one, position_for_index, rows

logger = logging.getLogger(__name__)


class LabelService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards

    def list(self, board_id: str) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            return rows(conn, "SELECT id, name, color FROM labels ORDER BY name")

    def create(self, actor: ActorContext, board_id: str, payload: LabelCreate) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        label_id = str(uuid4())
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT id FROM labels WHERE name = :name", {"name": payload.name})
            if existing:
                raise ValidationFailure("A label with that name already exists")
            conn.execute(
                text("INSERT INTO labels (id, name, color) VALUES (:id, :name, :color)"),
                {"id": label_id, "name": payload.name, "color": payload.color},
            )
            log_activity(
                conn,
                actor,
                action="label.created",
                entity_type="label",
                entity_id=label_id,
                changes={"name": payload.name, "color": payload.color},
            )
        return {"id": label_id, "name": payload.name, "color": payload.color}

    def update(
        self, actor: ActorContext, board_id: str, label_id: str, payload: LabelUpdate
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM labels WHERE id = :id", {"id": label_id})
            if existing is None:
                raise NotFound("Label not found")
            updates = payload.model_dump(exclude_none=True)
            if updates:
                assignments = ", ".join(f"{key} = :{key}" for key in updates)
                conn.execute(
                    text(f"UPDATE labels SET {assignments} WHERE id = :id"),
                    {**updates, "id": label_id},
                )
                log_activity(
                    conn,
                    actor,
                    action="label.updated",
                    entity_type="label",
                    entity_id=label_id,
                    changes={"before": existing, "after": updates},
                )
            row = one(conn, "SELECT id, name, color FROM labels WHERE id = :id", {"id": label_id})
        return row or {}

    def delete(self, actor: ActorContext, board_id: str, label_id: str) -> None:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM labels WHERE id = :id", {"id": label_id})
            if existing is None:
                raise NotFound("Label not found")
            conn.execute(text("DELETE FROM labels WHERE id = :id"), {"id": label_id})
            log_activity(
                conn,
                actor,
                action="label.deleted",
                entity_type="label",
                entity_id=label_id,
                changes={"name": existing["name"]},
            )


class ChecklistService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards

    def _card(self, conn: Any, card_id: str) -> dict[str, Any]:
        card = one(conn, "SELECT * FROM cards WHERE id = :id", {"id": card_id})
        if card is None:
            raise NotFound("Card not found")
        return card

    def list(self, board_id: str, card_id: str) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            self._card(conn, card_id)
            checklists = rows(
                conn,
                "SELECT * FROM checklists WHERE card_id = :id ORDER BY position, id",
                {"id": card_id},
            )
            items = rows(
                conn,
                "SELECT i.* FROM checklist_items i JOIN checklists ch ON ch.id = i.checklist_id"
                " WHERE ch.card_id = :id ORDER BY i.position, i.id",
                {"id": card_id},
            )
        for checklist in checklists:
            checklist["items"] = [
                {
                    "id": item["id"],
                    "checklist_id": item["checklist_id"],
                    "text": item["text"],
                    "completed": bool(item["completed"]),
                    "position": item["position"],
                }
                for item in items
                if item["checklist_id"] == checklist["id"]
            ]
        return checklists

    def create(
        self, actor: ActorContext, board_id: str, card_id: str, payload: ChecklistCreate
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        checklist_id = str(uuid4())
        with self.boards.session(board_id) as conn:
            self._card(conn, card_id)
            position = position_for_index(
                conn, "checklists", "card_id = :card_id", {"card_id": card_id}, None
            )
            conn.execute(
                text(
                    "INSERT INTO checklists (id, card_id, title, position)"
                    " VALUES (:id, :card_id, :title, :position)"
                ),
                {
                    "id": checklist_id,
                    "card_id": card_id,
                    "title": payload.title,
                    "position": position,
                },
            )
            log_activity(
                conn,
                actor,
                action="checklist.created",
                entity_type="checklist",
                entity_id=checklist_id,
                changes={"card_id": card_id, "title": payload.title},
            )
        return {
            "id": checklist_id,
            "card_id": card_id,
            "title": payload.title,
            "position": position,
            "items": [],
        }

    def update(
        self, actor: ActorContext, board_id: str, checklist_id: str, payload: ChecklistUpdate
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM checklists WHERE id = :id", {"id": checklist_id})
            if existing is None:
                raise NotFound("Checklist not found")
            if payload.title is not None and payload.title != existing["title"]:
                conn.execute(
                    text("UPDATE checklists SET title = :title WHERE id = :id"),
                    {"title": payload.title, "id": checklist_id},
                )
                log_activity(
                    conn,
                    actor,
                    action="checklist.updated",
                    entity_type="checklist",
                    entity_id=checklist_id,
                    changes={"before": existing["title"], "after": payload.title},
                )
                existing["title"] = payload.title
        checklists = self.list(board_id, existing["card_id"])
        return next((c for c in checklists if c["id"] == checklist_id), existing)

    def delete(self, actor: ActorContext, board_id: str, checklist_id: str) -> None:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM checklists WHERE id = :id", {"id": checklist_id})
            if existing is None:
                raise NotFound("Checklist not found")
            conn.execute(text("DELETE FROM checklists WHERE id = :id"), {"id": checklist_id})
            log_activity(
                conn,
                actor,
                action="checklist.deleted",
                entity_type="checklist",
                entity_id=checklist_id,
                changes={"card_id": existing["card_id"]},
            )

    def add_item(
        self,
        actor: ActorContext,
        board_id: str,
        checklist_id: str,
        payload: ChecklistItemCreate,
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        item_id = str(uuid4())
        with self.boards.session(board_id) as conn:
            checklist = one(conn, "SELECT * FROM checklists WHERE id = :id", {"id": checklist_id})
            if checklist is None:
                raise NotFound("Checklist not found")
            position = position_for_index(
                conn,
                "checklist_items",
                "checklist_id = :checklist_id",
                {"checklist_id": checklist_id},
                payload.position,
            )
            conn.execute(
                text(
                    "INSERT INTO checklist_items"
                    " (id, checklist_id, text, completed, position)"
                    " VALUES (:id, :checklist_id, :text, 0, :position)"
                ),
                {
                    "id": item_id,
                    "checklist_id": checklist_id,
                    "text": payload.text,
                    "position": position,
                },
            )
            log_activity(
                conn,
                actor,
                action="checklist.item_added",
                entity_type="checklist_item",
                entity_id=item_id,
                changes={"checklist_id": checklist_id, "text": payload.text},
            )
        return {
            "id": item_id,
            "checklist_id": checklist_id,
            "text": payload.text,
            "completed": False,
            "position": position,
        }

    def update_item(
        self,
        actor: ActorContext,
        board_id: str,
        item_id: str,
        payload: ChecklistItemUpdate,
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM checklist_items WHERE id = :id", {"id": item_id})
            if existing is None:
                raise NotFound("Checklist item not found")
            updates: dict[str, Any] = {}
            if payload.text is not None:
                updates["text"] = payload.text
            if payload.completed is not None:
                updates["completed"] = 1 if payload.completed else 0
            if payload.position is not None:
                updates["position"] = position_for_index(
                    conn,
                    "checklist_items",
                    "checklist_id = :checklist_id AND id != :id",
                    {"checklist_id": existing["checklist_id"], "id": item_id},
                    payload.position,
                )
            if updates:
                assignments = ", ".join(f"{key} = :{key}" for key in updates)
                conn.execute(
                    text(f"UPDATE checklist_items SET {assignments} WHERE id = :id"),
                    {**updates, "id": item_id},
                )
                log_activity(
                    conn,
                    actor,
                    action="checklist.item_updated",
                    entity_type="checklist_item",
                    entity_id=item_id,
                    changes={key: value for key, value in updates.items()},
                )
            row = one(conn, "SELECT * FROM checklist_items WHERE id = :id", {"id": item_id})
        assert row is not None
        return {
            "id": row["id"],
            "checklist_id": row["checklist_id"],
            "text": row["text"],
            "completed": bool(row["completed"]),
            "position": row["position"],
        }

    def delete_item(self, actor: ActorContext, board_id: str, item_id: str) -> None:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM checklist_items WHERE id = :id", {"id": item_id})
            if existing is None:
                raise NotFound("Checklist item not found")
            conn.execute(text("DELETE FROM checklist_items WHERE id = :id"), {"id": item_id})
            log_activity(
                conn,
                actor,
                action="checklist.item_deleted",
                entity_type="checklist_item",
                entity_id=item_id,
                changes={"checklist_id": existing["checklist_id"], "text": existing["text"]},
            )


class CommentService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.registry = board_service.registry
        self.mentions: Any = None

    def _serialize(self, conn: Any, comment: dict[str, Any]) -> dict[str, Any]:
        return comment

    def _decorate(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actor_ids = {comment["actor_id"] for comment in comments}
        actors = (
            {
                actor["id"]: actor
                for actor in self.registry.read(
                    "SELECT id, name, type FROM actors WHERE id IN ({})".format(
                        ", ".join(f":a{i}" for i in range(len(actor_ids)))
                    ),
                    {f"a{i}": actor_id for i, actor_id in enumerate(actor_ids)},
                )
            }
            if actor_ids
            else {}
        )
        for comment in comments:
            actor = actors.get(comment["actor_id"])
            comment["actor_name"] = actor["name"] if actor else None
            comment["actor_type"] = actor["type"] if actor else None
        missing = {
            comment["actor_id"] for comment in comments if comment["actor_name"] is None
        }
        if missing:
            params = {f"a{index}": actor_id for index, actor_id in enumerate(missing)}
            placeholders = ", ".join(f":{key}" for key in params)
            agents = {
                row["id"]: row
                for row in self.registry.read(
                    f"SELECT id, name FROM agents WHERE id IN ({placeholders})", params
                )
            }
            for comment in comments:
                agent = agents.get(comment["actor_id"])
                if agent is not None:
                    comment["actor_name"] = agent["name"]
                    comment["actor_type"] = "agent"
        return comments

    def list(self, board_id: str, card_id: str) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            comments = rows(
                conn,
                "SELECT * FROM comments WHERE card_id = :id ORDER BY created_at, rowid",
                {"id": card_id},
            )
        return self._decorate(comments)

    def create(
        self, actor: ActorContext, board_id: str, card_id: str, payload: CommentCreate
    ) -> dict[str, Any]:
        actor.require("comments:write")
        self.board_service.ensure_active(board_id)
        comment_id = str(uuid4())
        now = utcnow()
        with self.boards.session(board_id) as conn:
            card = one(conn, "SELECT id FROM cards WHERE id = :id", {"id": card_id})
            if card is None:
                raise NotFound("Card not found")
            conn.execute(
                text(
                    "INSERT INTO comments (id, card_id, actor_id, content, created_at, updated_at)"
                    " VALUES (:id, :card_id, :actor_id, :content, :now, :now)"
                ),
                {
                    "id": comment_id,
                    "card_id": card_id,
                    "actor_id": actor.actor_id,
                    "content": payload.content,
                    "now": now,
                },
            )
            log_activity(
                conn,
                actor,
                action="comment.created",
                entity_type="comment",
                entity_id=comment_id,
                changes={"card_id": card_id},
            )
        if self.mentions is not None and "@" in payload.content:
            try:
                self.mentions.queue(actor, board_id, card_id, comment_id, payload.content)
            except Exception:  # noqa: BLE001 - the comment is saved; mentions are best effort
                logger.exception("Could not queue mentions for comment %s", comment_id)
        return self._decorate(
            [
                {
                    "id": comment_id,
                    "card_id": card_id,
                    "actor_id": actor.actor_id,
                    "content": payload.content,
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        )[0]

    def _require_owner(self, actor: ActorContext, comment: dict[str, Any]) -> None:
        if not actor.is_user and comment["actor_id"] != actor.actor_id:
            raise Forbidden("Agents may only modify their own comments")

    def update(
        self, actor: ActorContext, board_id: str, comment_id: str, payload: CommentCreate
    ) -> dict[str, Any]:
        actor.require("comments:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM comments WHERE id = :id", {"id": comment_id})
            if existing is None:
                raise NotFound("Comment not found")
            self._require_owner(actor, existing)
            conn.execute(
                text("UPDATE comments SET content = :content, updated_at = :now WHERE id = :id"),
                {"content": payload.content, "now": utcnow(), "id": comment_id},
            )
            log_activity(
                conn,
                actor,
                action="comment.updated",
                entity_type="comment",
                entity_id=comment_id,
                changes={"card_id": existing["card_id"]},
            )
            row = one(conn, "SELECT * FROM comments WHERE id = :id", {"id": comment_id})
        assert row is not None
        return self._decorate([row])[0]

    def delete(self, actor: ActorContext, board_id: str, comment_id: str) -> None:
        actor.require("comments:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = one(conn, "SELECT * FROM comments WHERE id = :id", {"id": comment_id})
            if existing is None:
                raise NotFound("Comment not found")
            self._require_owner(actor, existing)
            conn.execute(text("DELETE FROM comments WHERE id = :id"), {"id": comment_id})
            log_activity(
                conn,
                actor,
                action="comment.deleted",
                entity_type="comment",
                entity_id=comment_id,
                changes={"card_id": existing["card_id"]},
            )


def parse_changes(raw: str | None) -> dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
