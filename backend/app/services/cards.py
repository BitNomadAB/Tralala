from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.dates import parse_due_filter
from ..core.errors import NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import BulkCardCreate, CardCreate, CardMove, CardTransfer, CardUpdate
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import (
    card_counts,
    decorate_cards,
    one,
    position_for_index,
    request_fingerprint,
    resolve_label_ids,
    rows,
    run_idempotent,
    set_card_labels,
)

logger = logging.getLogger("tralala.cards")


class CardService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.settings = board_service.settings

    # --- queries ---------------------------------------------------------------

    def _card_row(self, conn: Any, card_id: str) -> dict[str, Any]:
        row = one(conn, "SELECT * FROM cards WHERE id = :id", {"id": card_id})
        if row is None:
            raise NotFound("Card not found")
        return row

    def get(self, board_id: str, card_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            row = self._card_row(conn, card_id)
            return decorate_cards(conn, board_id, [row])[0]

    def list(
        self,
        board_id: str,
        *,
        list_id: str | None = None,
        q: str | None = None,
        label: str | None = None,
        priority: str | None = None,
        due_before: str | None = None,
        overdue: bool = False,
        completed: bool | None = None,
        assignee: str | None = None,
        include_archived: bool = False,
        sort: str = "position",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        self.board_service.require_row(board_id)
        clauses: list[str] = []
        params: dict[str, Any] = {}
        joins = ""
        if not include_archived:
            clauses.append("c.archived_at IS NULL")
        if list_id:
            clauses.append("c.list_id = :list_id")
            params["list_id"] = list_id
        if q:
            clauses.append("(c.title LIKE :q OR c.description LIKE :q)")
            params["q"] = f"%{q}%"
        if label:
            joins += " JOIN card_labels cl ON cl.card_id = c.id JOIN labels l ON l.id = cl.label_id"
            clauses.append("(l.id = :label OR l.name = :label)")
            params["label"] = label
        if priority:
            clauses.append("c.priority = :priority")
            params["priority"] = priority
        if due_before:
            clauses.append("c.due_at IS NOT NULL AND c.due_at <= :due_before")
            params["due_before"] = parse_due_filter(due_before)
        if overdue:
            clauses.append("c.due_at IS NOT NULL AND c.due_at < :now AND c.completed_at IS NULL")
            params["now"] = utcnow()
        if completed is not None:
            clauses.append("c.completed_at IS NOT NULL" if completed else "c.completed_at IS NULL")
        if assignee:
            if assignee == "unassigned":
                clauses.append("c.assignee_actor_id IS NULL")
            else:
                clauses.append("c.assignee_actor_id = :assignee")
                params["assignee"] = assignee
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sort_column = (
            "c.position"
            if sort not in {"created_at", "updated_at", "due_at", "title"}
            else f"c.{sort}"
        )
        direction = "DESC" if order.lower() == "desc" else "ASC"
        base = f"FROM cards c{joins}{where}"
        with self.boards.reader(board_id) as conn:
            total = conn.execute(text(f"SELECT COUNT(DISTINCT c.id) {base}"), params).scalar_one()
            records = rows(
                conn,
                f"SELECT DISTINCT c.* {base}"
                f" ORDER BY {sort_column} {direction}, c.id"
                " LIMIT :limit OFFSET :offset",
                {**params, "limit": limit, "offset": offset},
            )
            return decorate_cards(conn, board_id, records), int(total)

    def list_with_checklists(self, board_id: str, card_id: str) -> dict[str, Any]:
        from .subresources import ChecklistService

        card = self.get(board_id, card_id)
        card["checklists"] = ChecklistService(self.board_service).list(board_id, card_id)
        return card

    # --- mutations -------------------------------------------------------------

    def _insert_card(
        self,
        conn: Any,
        *,
        board_id: str,
        list_id: str,
        payload: CardCreate,
        actor: ActorContext,
        list_ids: set[str],
    ) -> dict[str, Any]:
        if list_id not in list_ids:
            raise ValidationFailure(
                "List does not exist or is archived", details={"list_id": list_id}
            )
        card_id = str(uuid4())
        now = utcnow()
        position = position_for_index(
            conn, "cards", "list_id = :list_id AND archived_at IS NULL", {"list_id": list_id}, None
        )
        conn.execute(
            text(
                "INSERT INTO cards (id, list_id, title, description, position, priority, due_at,"
                " completed_at, created_at, updated_at, archived_at, version)"
                " VALUES (:id, :list_id, :title, :description, :position, :priority, :due_at,"
                "         NULL, :now, :now, NULL, 1)"
            ),
            {
                "id": card_id,
                "list_id": list_id,
                "title": payload.title,
                "description": payload.description,
                "position": position,
                "priority": payload.priority,
                "due_at": payload.due_at,
                "now": now,
            },
        )
        if payload.labels:
            set_card_labels(conn, card_id, resolve_label_ids(conn, payload.labels))
        row = self._card_row(conn, card_id)
        log_activity(
            conn,
            actor,
            action="card.created",
            entity_type="card",
            entity_id=card_id,
            changes={"title": payload.title, "list_id": list_id},
        )
        del board_id
        return row

    def _active_list_ids(self, conn: Any) -> set[str]:
        return {row["id"] for row in rows(conn, "SELECT id FROM lists WHERE archived_at IS NULL")}

    def _resolve_assignee(self, assignee_id: str) -> dict[str, Any]:
        """Validate a human actor or an enabled registry agent as the primary assignee."""
        registry = self.board_service.registry
        person = registry.read_one(
            "SELECT id, type, name FROM actors WHERE id = :id AND disabled_at IS NULL",
            {"id": assignee_id},
        )
        if person is not None:
            return {
                "assignee_actor_id": person["id"],
                "assignee_type": person["type"],
                "assignee_name": person["name"],
            }
        agent = registry.read_one(
            "SELECT id, name, enabled FROM agents WHERE id = :id", {"id": assignee_id}
        )
        if agent is None:
            raise ValidationFailure(
                "Assignee must be a human user or a registered agent",
                details={"assignee_actor_id": assignee_id},
            )
        if not agent["enabled"]:
            raise ValidationFailure(
                "Agent is disabled and cannot be assigned",
                details={"assignee_actor_id": assignee_id},
            )
        return {
            "assignee_actor_id": agent["id"],
            "assignee_type": "agent",
            "assignee_name": agent["name"],
        }

    def create(
        self,
        actor: ActorContext,
        board_id: str,
        payload: CardCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        fingerprint = request_fingerprint(
            {"op": "card.create", "board_id": board_id, "payload": payload.model_dump()}
        )

        with self.boards.session(board_id) as conn:
            created: dict[str, Any] = {}

            def action() -> dict[str, Any]:
                row = self._insert_card(
                    conn,
                    board_id=board_id,
                    list_id=payload.list_id,
                    payload=payload,
                    actor=actor,
                    list_ids=self._active_list_ids(conn),
                )
                card = decorate_cards(conn, board_id, [row])[0]
                created.update(card)
                return card

            result, replayed = run_idempotent(
                conn,
                actor_id=actor.actor_id,
                key=idempotency_key,
                fingerprint=fingerprint,
                ttl_seconds=self.settings.idempotency_ttl_seconds,
                action=action,
            )
        return result, replayed

    def bulk_create(
        self,
        actor: ActorContext,
        board_id: str,
        payload: BulkCardCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        if len(payload.cards) > self.settings.bulk_limit:
            raise ValidationFailure(
                "Bulk request exceeds the configured limit",
                details={"limit": self.settings.bulk_limit},
            )
        fingerprint = request_fingerprint(
            {"op": "card.bulk_create", "board_id": board_id, "payload": payload.model_dump()}
        )

        with self.boards.session(board_id) as conn:

            def action() -> dict[str, Any]:
                created: list[dict[str, Any]] = []
                failed: list[dict[str, Any]] = []
                list_ids = self._active_list_ids(conn)
                for index, card_payload in enumerate(payload.cards):
                    savepoint = conn.begin_nested()
                    try:
                        row = self._insert_card(
                            conn,
                            board_id=board_id,
                            list_id=card_payload.list_id,
                            payload=card_payload,
                            actor=actor,
                            list_ids=list_ids,
                        )
                        created.append(decorate_cards(conn, board_id, [row])[0])
                        savepoint.commit()
                    except ValidationFailure as exc:
                        savepoint.rollback()
                        failed.append(
                            {
                                "index": index,
                                "code": "card_create_failed",
                                "message": exc.message,
                            }
                        )
                    except Exception:  # noqa: BLE001 - partial failure is contract
                        savepoint.rollback()
                        logger.exception("bulk card creation failed", extra={"index": index})
                        failed.append(
                            {
                                "index": index,
                                "code": "card_create_failed",
                                "message": "Card could not be created",
                            }
                        )
                return {"created": created, "failed": failed}

            result, replayed = run_idempotent(
                conn,
                actor_id=actor.actor_id,
                key=idempotency_key,
                fingerprint=fingerprint,
                ttl_seconds=self.settings.idempotency_ttl_seconds,
                action=action,
            )
        return result, replayed

    def update(
        self, actor: ActorContext, board_id: str, card_id: str, payload: CardUpdate
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self._card_row(conn, card_id)
            if existing["version"] != payload.version:
                raise VersionConflict(
                    "Card was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": existing["version"],
                    },
                )
            changes: dict[str, Any] = {}
            assignments: dict[str, Any] = {}
            if payload.title is not None and payload.title != existing["title"]:
                assignments["title"] = payload.title
                changes["title"] = {"before": existing["title"], "after": payload.title}
            if payload.description is not None and payload.description != existing["description"]:
                assignments["description"] = payload.description
                changes["description"] = {"changed": True}
            if payload.priority is not None and payload.priority != existing["priority"]:
                assignments["priority"] = payload.priority
                changes["priority"] = {
                    "before": existing["priority"],
                    "after": payload.priority,
                }
            if payload.clear_due_at:
                assignments["due_at"] = None
                changes["due_at"] = {"before": existing["due_at"], "after": None}
            elif payload.due_at is not None and payload.due_at != existing["due_at"]:
                assignments["due_at"] = payload.due_at
                changes["due_at"] = {"before": existing["due_at"], "after": payload.due_at}
            if payload.completed is not None:
                already = existing["completed_at"] is not None
                if payload.completed and not already:
                    assignments["completed_at"] = utcnow()
                    changes["completed"] = {"before": False, "after": True}
                elif not payload.completed and already:
                    assignments["completed_at"] = None
                    changes["completed"] = {"before": True, "after": False}
            if payload.labels is not None:
                label_ids = resolve_label_ids(conn, payload.labels)
                set_card_labels(conn, card_id, label_ids)
                changes["labels"] = {"after": payload.labels}
            if payload.clear_assignee:
                assignments["assignee_actor_id"] = None
                assignments["assignee_type"] = None
                assignments["assignee_name"] = None
                assignments["assigned_at"] = None
                assignments["assigned_by_actor_id"] = None
                changes["assignee"] = {
                    "before": existing.get("assignee_actor_id"),
                    "after": None,
                }
            elif payload.assignee_actor_id is not None:
                assignee = self._resolve_assignee(payload.assignee_actor_id)
                if assignee["assignee_actor_id"] != existing.get("assignee_actor_id"):
                    assignments.update(assignee)
                    assignments["assigned_at"] = utcnow()
                    assignments["assigned_by_actor_id"] = actor.actor_id
                    changes["assignee"] = {
                        "before": existing.get("assignee_actor_id"),
                        "after": assignee["assignee_actor_id"],
                        "name": assignee["assignee_name"],
                        "type": assignee["assignee_type"],
                    }
            if assignments:
                assignments["version"] = existing["version"] + 1
                assignments["updated_at"] = utcnow()
                columns = ", ".join(f"{column} = :{column}" for column in assignments)
                conn.execute(
                    text(f"UPDATE cards SET {columns} WHERE id = :id"),
                    {**assignments, "id": card_id},
                )
            if changes:
                log_activity(
                    conn,
                    actor,
                    action="card.updated",
                    entity_type="card",
                    entity_id=card_id,
                    changes=changes,
                )
            row = self._card_row(conn, card_id)
            card = decorate_cards(conn, board_id, [row])[0]
        return card

    def move(
        self, actor: ActorContext, board_id: str, card_id: str, payload: CardMove
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self._card_row(conn, card_id)
            if existing["version"] != payload.version:
                raise VersionConflict(
                    "Card was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": existing["version"],
                    },
                )
            target = one(conn, "SELECT * FROM lists WHERE id = :id", {"id": payload.list_id})
            if target is None or target["archived_at"] is not None:
                raise ValidationFailure(
                    "Target list does not exist or is archived",
                    details={"list_id": payload.list_id},
                )
            position = position_for_index(
                conn,
                "cards",
                "list_id = :list_id AND archived_at IS NULL AND id != :id",
                {"list_id": payload.list_id, "id": card_id},
                payload.position,
            )
            conn.execute(
                text(
                    "UPDATE cards SET list_id = :list_id, position = :position,"
                    " version = version + 1, updated_at = :now WHERE id = :id"
                ),
                {
                    "list_id": payload.list_id,
                    "position": position,
                    "now": utcnow(),
                    "id": card_id,
                },
            )
            log_activity(
                conn,
                actor,
                action="card.moved",
                entity_type="card",
                entity_id=card_id,
                changes={
                    "from_list_id": existing["list_id"],
                    "to_list_id": payload.list_id,
                    "position": payload.position,
                },
            )
            row = self._card_row(conn, card_id)
            card = decorate_cards(conn, board_id, [row])[0]
        return card

    def archive(self, actor: ActorContext, board_id: str, card_id: str) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self._card_row(conn, card_id)
            if existing["archived_at"] is None:
                conn.execute(
                    text(
                        "UPDATE cards SET archived_at = :now, updated_at = :now,"
                        " version = version + 1 WHERE id = :id"
                    ),
                    {"now": utcnow(), "id": card_id},
                )
            log_activity(
                conn,
                actor,
                action="card.archived",
                entity_type="card",
                entity_id=card_id,
            )
            row = self._card_row(conn, card_id)
            card = decorate_cards(conn, board_id, [row])[0]
        return card

    def restore(self, actor: ActorContext, board_id: str, card_id: str) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            existing = self._card_row(conn, card_id)
            if existing["archived_at"] is not None:
                position = position_for_index(
                    conn,
                    "cards",
                    "list_id = :list_id AND archived_at IS NULL",
                    {"list_id": existing["list_id"]},
                    None,
                )
                conn.execute(
                    text(
                        "UPDATE cards SET archived_at = NULL, position = :position,"
                        " updated_at = :now, version = version + 1 WHERE id = :id"
                    ),
                    {"position": position, "now": now, "id": card_id},
                )
            log_activity(
                conn,
                actor,
                action="card.restored",
                entity_type="card",
                entity_id=card_id,
            )
            row = self._card_row(conn, card_id)
            card = decorate_cards(conn, board_id, [row])[0]
        return card

    def transfer(
        self, actor: ActorContext, board_id: str, card_id: str, payload: CardTransfer
    ) -> dict[str, Any]:
        """Cross-board move using a recoverable copy-and-finalize workflow."""
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        target_board_id = self.boards.validate_board_id(payload.target_board_id)
        if target_board_id == board_id:
            raise ValidationFailure("Source and target board are identical")
        self.board_service.ensure_active(target_board_id)

        with self.boards.reader(board_id) as conn:
            source = self._card_row(conn, card_id)
            if source["version"] != payload.version:
                raise VersionConflict(
                    "Card was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": source["version"],
                    },
                )
            labels = [
                row["name"]
                for row in rows(
                    conn,
                    "SELECT l.name FROM card_labels cl JOIN labels l ON l.id = cl.label_id"
                    " WHERE cl.card_id = :id",
                    {"id": card_id},
                )
            ]
            checklists = rows(
                conn,
                "SELECT * FROM checklists WHERE card_id = :id ORDER BY position",
                {"id": card_id},
            )
            items = rows(
                conn,
                "SELECT i.* FROM checklist_items i JOIN checklists ch ON ch.id = i.checklist_id"
                " WHERE ch.card_id = :id ORDER BY i.position",
                {"id": card_id},
            )
            comments = rows(
                conn,
                "SELECT * FROM comments WHERE card_id = :id ORDER BY created_at",
                {"id": card_id},
            )

        new_card_id = str(uuid4())
        now = utcnow()
        with self.boards.session(target_board_id) as conn:
            target_list = one(
                conn, "SELECT * FROM lists WHERE id = :id", {"id": payload.target_list_id}
            )
            if target_list is None or target_list["archived_at"] is not None:
                raise ValidationFailure(
                    "Target list does not exist or is archived",
                    details={"list_id": payload.target_list_id},
                )
            position = position_for_index(
                conn,
                "cards",
                "list_id = :list_id AND archived_at IS NULL",
                {"list_id": payload.target_list_id},
                None,
            )
            conn.execute(
                text(
                    "INSERT INTO cards (id, list_id, title, description, position,"
                    " priority, due_at,"
                    " completed_at, created_at, updated_at, archived_at, version)"
                    " VALUES (:id, :list_id, :title, :description, :position, :priority, :due_at,"
                    "         :completed_at, :created_at, :now, NULL, 1)"
                ),
                {
                    "id": new_card_id,
                    "list_id": payload.target_list_id,
                    "title": source["title"],
                    "description": source["description"],
                    "position": position,
                    "priority": source["priority"],
                    "due_at": source["due_at"],
                    "completed_at": source["completed_at"],
                    "created_at": source["created_at"],
                    "now": now,
                },
            )
            if labels:
                set_card_labels(conn, new_card_id, resolve_label_ids(conn, labels))
            for checklist in checklists:
                new_checklist_id = str(uuid4())
                conn.execute(
                    text(
                        "INSERT INTO checklists (id, card_id, title, position)"
                        " VALUES (:id, :card_id, :title, :position)"
                    ),
                    {
                        "id": new_checklist_id,
                        "card_id": new_card_id,
                        "title": checklist["title"],
                        "position": checklist["position"],
                    },
                )
                for item in [i for i in items if i["checklist_id"] == checklist["id"]]:
                    conn.execute(
                        text(
                            "INSERT INTO checklist_items"
                            " (id, checklist_id, text, completed, position)"
                            " VALUES (:id, :checklist_id, :text, :completed, :position)"
                        ),
                        {
                            "id": str(uuid4()),
                            "checklist_id": new_checklist_id,
                            "text": item["text"],
                            "completed": item["completed"],
                            "position": item["position"],
                        },
                    )
            for comment in comments:
                conn.execute(
                    text(
                        "INSERT INTO comments"
                        " (id, card_id, actor_id, content, created_at, updated_at)"
                        " VALUES (:id, :card_id, :actor_id, :content, :created_at, :updated_at)"
                    ),
                    {
                        "id": str(uuid4()),
                        "card_id": new_card_id,
                        "actor_id": comment["actor_id"],
                        "content": comment["content"],
                        "created_at": comment["created_at"],
                        "updated_at": comment["updated_at"],
                    },
                )
            log_activity(
                conn,
                actor,
                action="card.received",
                entity_type="card",
                entity_id=new_card_id,
                changes={"source_board_id": board_id, "source_card_id": card_id},
            )
            new_card = decorate_cards(conn, target_board_id, [self._card_row(conn, new_card_id)])[0]

        finalized = True
        warning: str | None = None
        try:
            with self.boards.session(board_id) as conn:
                conn.execute(text("DELETE FROM cards WHERE id = :id"), {"id": card_id})
                log_activity(
                    conn,
                    actor,
                    action="card.transferred",
                    entity_type="card",
                    entity_id=card_id,
                    changes={
                        "target_board_id": target_board_id,
                        "target_card_id": new_card_id,
                    },
                )
        except Exception:  # noqa: BLE001 - recovery path is part of the contract
            logger.exception("card transfer finalize failed", extra={"card_id": card_id})
            finalized = False
            warning = "Card was copied but the source copy could not be removed"
            try:
                with self.boards.session(board_id) as conn:
                    now = utcnow()
                    conn.execute(
                        text(
                            "UPDATE cards SET archived_at = :now, updated_at = :now,"
                            " version = version + 1 WHERE id = :id AND archived_at IS NULL"
                        ),
                        {"now": now, "id": card_id},
                    )
                    log_activity(
                        conn,
                        actor,
                        action="card.transfer_incomplete",
                        entity_type="card",
                        entity_id=card_id,
                        changes={
                            "target_board_id": target_board_id,
                            "target_card_id": new_card_id,
                            "reason": "source_delete_failed",
                        },
                    )
                warning += "; the source card was archived so it is not visible twice"
            except Exception:  # noqa: BLE001 - best-effort containment
                warning += "; the source card could not be archived and may appear twice"

        return {
            "card": new_card,
            "source_board_id": board_id,
            "source_card_id": card_id,
            "finalized": finalized,
            "warning": warning,
        }

    def stats(self, board_id: str, card_id: str) -> dict[str, int]:
        with self.boards.reader(board_id) as conn:
            return card_counts(conn, [card_id]).get(
                card_id, {"checklist_total": 0, "checklist_completed": 0, "comment_count": 0}
            )
