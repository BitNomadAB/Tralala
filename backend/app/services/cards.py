"""Tickets: Loop-scoped cards with version checks, readiness and human gates.

A Ticket is the existing card resource, extended with Loop ownership, a stable key, its Phase and
its approved work definition. Completion stays explicit through ``completed_at``; a column name
never marks work done, and every completion transition runs through the same readiness rules an
agent's start request would face.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core import sql
from ..core.context import ActorContext
from ..core.dates import parse_due_filter
from ..core.errors import Conflict, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import BulkCardCreate, CardCreate, CardMove, CardUpdate
from ..storage.board_db import BoardDatabaseManager
from ..storage.registry import Registry
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import (
    LABEL_JOIN,
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

PLAN_CHANGE_CODE = "plan_change_required"

# What the card queries format into SQL text (see core/sql.py).
_CARD_FILTERS: sql.Filters = (
    ("loop", "c.loop_id = :loop_id"),
    ("unarchived", "c.archived_at IS NULL"),
    ("list", "c.list_id = :list_id"),
    ("q", "(c.title LIKE :q OR c.description LIKE :q)"),
    ("label", "(l.id = :label OR l.name = :label)"),
    ("priority", "c.priority = :priority"),
    ("due_before", "c.due_at IS NOT NULL AND c.due_at <= :due_before"),
    ("overdue", "c.due_at IS NOT NULL AND c.due_at < :now AND c.completed_at IS NULL"),
    ("completed", "c.completed_at IS NOT NULL"),
    ("open", "c.completed_at IS NULL"),
    ("unassigned", "c.assignee_actor_id IS NULL"),
    ("assignee", "c.assignee_actor_id = :assignee"),
)
_CARD_SORTS = ("created_at", "updated_at", "due_at", "title")
_BOARD_TICKET_FILTERS: sql.Filters = (
    ("open", "c.archived_at IS NULL AND l.completed_at IS NULL AND l.archived_at IS NULL"),
    ("q", "(c.title LIKE :q OR c.ticket_key LIKE :q)"),
)
_CARD_EDITABLE = (
    "title",
    "description",
    "priority",
    "due_at",
    "completed_at",
    "human_confirmed_at",
    "human_confirmed_by_actor_id",
    "assignee_actor_id",
    "assignee_type",
    "assignee_name",
    "assigned_at",
    "assigned_by_actor_id",
    "version",
    "updated_at",
)


class CardService:
    def __init__(
        self,
        board_service: BoardService,
        loop_service: Any | None = None,
        plan_service: Any | None = None,
        *,
        boards: BoardDatabaseManager,
        registry: Registry,
    ) -> None:
        self.board_service = board_service
        self.boards = boards
        self.registry = registry
        self.settings = board_service.settings
        self.loops = loop_service
        self.plans = plan_service

    # --- helpers ---------------------------------------------------------------

    def _loop_row(self, conn: Any, board_id: str, loop_id: str) -> dict[str, Any]:
        if self.loops is None:
            raise NotFound("Loop not found", code="loop_not_found")
        return self.loops.require_loop_row(conn, board_id, loop_id)

    def _card_row(self, conn: Any, board_id: str, loop_id: str, card_id: str) -> dict[str, Any]:
        row = one(conn, "SELECT * FROM cards WHERE id = :id", {"id": card_id})
        if row is None:
            raise NotFound("Card not found")
        if row["loop_id"] != loop_id:
            raise Conflict(
                "The Ticket belongs to another Loop",
                code="loop_mismatch",
                details={"loop_id": loop_id, "ticket_loop_id": row["loop_id"]},
            )
        del board_id
        return row

    def require_membership(self, board_id: str, loop_id: str, card_id: str) -> None:
        """Cheap ownership check for routes that address a Ticket through its Loop."""
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            self._card_row(conn, board_id, loop_id, card_id)

    def _require_writable(self, loop: dict[str, Any]) -> None:
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

    def _decorate(
        self, conn: Any, board_id: str, loop: dict[str, Any], cards: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        decorated = decorate_cards(conn, board_id, cards)
        readiness: dict[str, dict[str, Any]] = {}
        if loop.get("current_plan_id") and self.plans is not None:
            evaluation = self.plans.readiness(conn, loop)
            for item in evaluation["items"]:
                if item.get("card_id"):
                    readiness[item["card_id"]] = item
        for card in decorated:
            card["loop_id"] = loop["id"]
            item = readiness.get(card["id"])
            if item is not None:
                card["human_action_required"] = bool(item["human_action_required"])
            else:
                card["human_action_required"] = (
                    card.get("required_actor") == "human" and card.get("completed_at") is None
                )
            card["ready"] = bool(item["ready"]) if item else True
            card["blockers"] = item["blockers"] if item else []
            card["downstream_phase_numbers"] = (
                item["downstream_phase_numbers"] if item else []
            )
            card["acceptance_criteria"] = item["acceptance_criteria"] if item else []
            card["expected_evidence"] = item["expected_evidence"] if item else []
            card["phase_number"] = item["phase_number"] if item else None
        return decorated

    def _readiness_for(self, conn: Any, loop: dict[str, Any], card_id: str) -> dict[str,
    Any] | None:
        if not loop.get("current_plan_id") or self.plans is None:
            return None
        evaluation = self.plans.readiness(conn, loop)
        for item in evaluation["items"]:
            if item.get("card_id") == card_id:
                return item
        return None

    # --- queries ---------------------------------------------------------------

    def locate(self, board_id: str, card_id: str) -> tuple[str, dict[str, Any]]:
        """Which Loop owns a Ticket.

        Board-level callers (the worker tools) are handed a Ticket id and nothing else, so the
        owning Loop is resolved here instead of being guessed. The row is returned so a caller can
        use its version without a second read.
        """
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            row = one(conn, "SELECT * FROM cards WHERE id = :id", {"id": card_id})
            if row is None:
                raise NotFound("Ticket not found")
            loop = one(conn, "SELECT id FROM loops WHERE id = :id", {"id": row["loop_id"]})
            if loop is None:
                raise NotFound("Ticket not found")
            return str(row["loop_id"]), dict(row)

    def get(self, board_id: str, loop_id: str, card_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            row = self._card_row(conn, board_id, loop_id, card_id)
            return self._decorate(conn, board_id, loop, [row])[0]

    def list(
        self,
        board_id: str,
        loop_id: str,
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
        filters = ["loop"]
        params: dict[str, Any] = {"loop_id": loop_id}
        if not include_archived:
            filters.append("unarchived")
        if list_id:
            filters.append("list")
            params["list_id"] = list_id
        if q:
            filters.append("q")
            params["q"] = f"%{q}%"
        if label:
            filters.append("label")
            params["label"] = label
        if priority:
            filters.append("priority")
            params["priority"] = priority
        if due_before:
            filters.append("due_before")
            params["due_before"] = parse_due_filter(due_before)
        if overdue:
            filters.append("overdue")
            params["now"] = utcnow()
        if completed is not None:
            filters.append("completed" if completed else "open")
        if assignee:
            if assignee == "unassigned":
                filters.append("unassigned")
            else:
                filters.append("assignee")
                params["assignee"] = assignee
        joins = LABEL_JOIN if label else ""
        where = sql.where(_CARD_FILTERS, filters)
        sort_column = (
            f"c.{sql.identifier(sort, _CARD_SORTS)}" if sort in _CARD_SORTS else "c.position"
        )
        direction = "DESC" if order.lower() == "desc" else "ASC"
        with self.boards.reader(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            total = conn.execute(
                text(
                    "SELECT COUNT(DISTINCT c.id)"  # noqa: S608 - from LABEL_JOIN and _CARD_FILTERS
                    f" FROM cards c{joins}{where}"
                ),
                params,
            ).scalar_one()
            records = rows(
                conn,
                "SELECT DISTINCT c.*"  # noqa: S608 - from LABEL_JOIN, _CARD_FILTERS, _CARD_SORTS
                f" FROM cards c{joins}{where} ORDER BY {sort_column} {direction}, c.id"
                " LIMIT :limit OFFSET :offset",
                {**params, "limit": limit, "offset": offset},
            )
            return self._decorate(conn, board_id, loop, records), int(total)

    def list_board_tickets(
        self, board_id: str, *, q: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Explicit Board-level aggregate read; every row identifies its owning Loop."""
        self.board_service.require_row(board_id)
        filters = ["open"]
        params: dict[str, Any] = {"limit": limit}
        if q:
            filters.append("q")
            params["q"] = f"%{q}%"
        where = sql.where(_BOARD_TICKET_FILTERS, filters)
        with self.boards.reader(board_id) as conn:
            records = rows(
                conn,
                "SELECT c.*, l.key AS loop_key,"  # noqa: S608 - from _BOARD_TICKET_FILTERS
                " l.name AS loop_name, l.stage AS loop_stage"
                f" FROM cards c JOIN loops l ON l.id = c.loop_id{where}"
                " ORDER BY l.sequence, c.position, c.id LIMIT :limit",
                params,
            )
            decorated = decorate_cards(conn, board_id, records)
            for record in decorated:
                record["board_id"] = board_id
        return decorated

    def list_with_checklists(self, board_id: str, loop_id: str, card_id: str) -> dict[str, Any]:
        from .subresources import ChecklistService

        card = self.get(board_id, loop_id, card_id)
        card["checklists"] = ChecklistService(self.board_service, boards=self.boards).list(
            board_id, card_id
        )
        return card

    # --- mutations -------------------------------------------------------------

    def _active_list_ids(self, conn: Any, loop_id: str) -> set[str]:
        return {
            row["id"]
            for row in rows(
                conn,
                "SELECT id FROM lists WHERE loop_id = :loop_id AND archived_at IS NULL",
                {"loop_id": loop_id},
            )
        }

    def _insert_card(
        self,
        conn: Any,
        *,
        board_id: str,
        loop: dict[str, Any],
        list_id: str,
        payload: CardCreate,
        actor: ActorContext,
    ) -> dict[str, Any]:
        list_ids = self._active_list_ids(conn, loop["id"])
        if list_id not in list_ids:
            other = one(conn, "SELECT loop_id FROM lists WHERE id = :id", {"id": list_id})
            if other is not None and other["loop_id"] != loop["id"]:
                raise Conflict(
                    "The column belongs to another Loop",
                    code="loop_mismatch",
                    details={"list_id": list_id},
                )
            raise ValidationFailure(
                "List does not exist or is archived", details={"list_id": list_id}
            )
        card_id = str(uuid4())
        now = utcnow()
        position = position_for_index(conn, "cards", {"list_id": list_id}, None)
        conn.execute(
            text(
                "INSERT INTO cards (id, loop_id, list_id, title, description, position, priority,"
                " due_at, completed_at, created_at, updated_at, archived_at, version, kind)"
                " VALUES (:id, :loop_id, :list_id, :title, :description, :position, :priority,"
                " :due_at, NULL, :now, :now, NULL, 1, 'manual')"
            ),
            {
                "id": card_id,
                "loop_id": loop["id"],
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
        row = self._card_row(conn, board_id, loop["id"], card_id)
        log_activity(
            conn,
            actor,
            action="card.created",
            entity_type="card",
            entity_id=card_id,
            changes={"title": payload.title, "list_id": list_id, "loop_id": loop["id"]},
        )
        return row

    def _resolve_assignee(self, assignee_id: str) -> dict[str, Any]:
        """Validate a human actor or an enabled registry agent as the primary assignee."""
        registry = self.registry
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
        loop_id: str,
        payload: CardCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        fingerprint = request_fingerprint(
            {
                "op": "card.create",
                "board_id": board_id,
                "loop_id": loop_id,
                "payload": payload.model_dump(),
            }
        )

        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            if loop.get("current_plan_id"):
                raise Conflict(
                    "This Loop executes an approved plan; amend the plan to add work",
                    code=PLAN_CHANGE_CODE,
                    details={"loop_id": loop_id},
                )

            def action() -> dict[str, Any]:
                row = self._insert_card(
                    conn,
                    board_id=board_id,
                    loop=loop,
                    list_id=payload.list_id,
                    payload=payload,
                    actor=actor,
                )
                return self._decorate(conn, board_id, loop, [row])[0]

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
        loop_id: str,
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
            {
                "op": "card.bulk_create",
                "board_id": board_id,
                "loop_id": loop_id,
                "payload": payload.model_dump(),
            }
        )

        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            if loop.get("current_plan_id"):
                raise Conflict(
                    "This Loop executes an approved plan; amend the plan to add work",
                    code=PLAN_CHANGE_CODE,
                    details={"loop_id": loop_id},
                )

            def action() -> dict[str, Any]:
                created: list[dict[str, Any]] = []
                failed: list[dict[str, Any]] = []
                for index, card_payload in enumerate(payload.cards):
                    savepoint = conn.begin_nested()
                    try:
                        row = self._insert_card(
                            conn,
                            board_id=board_id,
                            loop=loop,
                            list_id=card_payload.list_id,
                            payload=card_payload,
                            actor=actor,
                        )
                        created.append(self._decorate(conn, board_id, loop, [row])[0])
                        savepoint.commit()
                    except (ValidationFailure, Conflict) as exc:
                        savepoint.rollback()
                        failed.append(
                            {
                                "index": index,
                                "code": "card_create_failed",
                                "message": exc.message,
                            }
                        )
                    except Exception:  # partial failure is the contract here
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
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: CardUpdate,
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._card_row(conn, board_id, loop_id, card_id)
            if existing["version"] != payload.version:
                raise VersionConflict(
                    "Card was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": existing["version"],
                    },
                )
            self._guard_plan_scope(existing, payload)
            self._guard_completion(conn, loop, existing, payload, actor)
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
                    if existing["required_actor"] == "human":
                        assignments["human_confirmed_at"] = utcnow()
                        assignments["human_confirmed_by_actor_id"] = actor.actor_id
                        changes["human_confirmation"] = {"actor_id": actor.actor_id}
                elif not payload.completed and already:
                    assignments["completed_at"] = None
                    assignments["human_confirmed_at"] = None
                    assignments["human_confirmed_by_actor_id"] = None
                    changes["completed"] = {"before": True, "after": False}
                    self._invalidate_after_reopen(conn, loop, existing)
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
                columns = sql.assignments(assignments, _CARD_EDITABLE)
                conn.execute(
                    text(
                        "UPDATE cards"  # noqa: S608 - from _CARD_EDITABLE
                        f" SET {columns} WHERE id = :id"
                    ),
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
            if "completed" in changes:
                self._refresh_loop(conn, loop_id)
            row = self._card_row(conn, board_id, loop_id, card_id)
            return self._decorate(conn, board_id, loop, [row])[0]

    @staticmethod
    def _guard_plan_scope(existing: dict[str, Any], payload: CardUpdate) -> None:
        """The approved work definition is not editable through a card endpoint."""
        if not existing.get("plan_item_id"):
            return
        if payload.title is not None and payload.title != existing["title"]:
            raise Conflict(
                "Changing an approved Ticket title needs a reviewed plan amendment",
                code=PLAN_CHANGE_CODE,
                details={"field": "title", "ticket_key": existing.get("ticket_key")},
            )
        if payload.description is not None and payload.description != existing["description"]:
            raise Conflict(
                "Changing approved instructions needs a reviewed plan amendment",
                code=PLAN_CHANGE_CODE,
                details={"field": "description", "ticket_key": existing.get("ticket_key")},
            )

    def _guard_completion(
        self,
        conn: Any,
        loop: dict[str, Any],
        existing: dict[str, Any],
        payload: CardUpdate,
        actor: ActorContext,
    ) -> None:
        if payload.completed is not True:
            return
        if existing["completed_at"] is not None:
            return
        if self.loops is None:
            raise Conflict(
                "Tickets must belong to a Loop before they can be completed",
                code="loop_required",
            )
        if loop["archived_at"] is not None:
            raise Conflict(
                "Archived Tickets cannot be completed", code="loop_read_only"
            )
        if existing["archived_at"] is not None:
            raise Conflict(
                "Archived Tickets cannot be completed; restore it first",
                code="ticket_blocked",
                details={"ticket_id": existing["id"]},
            )
        if existing.get("plan_item_id") or loop.get("current_plan_id"):
            self.loops.ensure_execution_allowed(loop)
        if existing["required_actor"] == "human":
            actor.require_human(f"Confirming {existing.get('ticket_key') or 'this Ticket'}")
        item = self._readiness_for(conn, loop, existing["id"])
        if item is not None and not item["ready"]:
            raise Conflict(
                "This Ticket is blocked by unresolved prerequisites",
                code="ticket_blocked",
                details={"blockers": item["blockers"], "ticket_key": existing.get("ticket_key")},
            )

    def _invalidate_after_reopen(
        self, conn: Any, loop: dict[str, Any], card: dict[str, Any]
    ) -> None:
        """Reopening a prerequisite invalidates QA evidence prepared against the old baseline."""
        now = utcnow()
        conn.execute(
            text(
                "UPDATE loop_qa_cycles SET status = 'superseded', updated_at = :now"
                " WHERE loop_id = :id AND status IN ('pending','instructions_ready','in_progress')"
            ),
            {"now": now, "id": loop["id"]},
        )
        conn.execute(
            text(
                "UPDATE loops SET implementation_approval_id = NULL, qa_approval_id = NULL,"
                " updated_at = :now WHERE id = :id"
            ),
            {"now": now, "id": loop["id"]},
        )
        log_activity(
            conn,
            ActorContext(actor_id="system", actor_type="system", actor_name="Tralala"),
            action="loop.reopened_work",
            entity_type="card",
            entity_id=card["id"],
            changes={"revalidation_required": True},
        )

    def _refresh_loop(self, conn: Any, loop_id: str) -> None:
        if self.loops is not None:
            self.loops.refresh_stage(conn, loop_id)

    def move(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: CardMove,
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._card_row(conn, board_id, loop_id, card_id)
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
            if target["loop_id"] != loop_id:
                raise Conflict(
                    "A Ticket cannot move to another Loop",
                    code="loop_mismatch",
                    details={"target_loop_id": target["loop_id"]},
                )
            position = position_for_index(
                conn, "cards", {"list_id": payload.list_id}, payload.position, exclude=card_id
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
            row = self._card_row(conn, board_id, loop_id, card_id)
            return self._decorate(conn, board_id, loop, [row])[0]

    def archive(
        self, actor: ActorContext, board_id: str, loop_id: str, card_id: str
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._card_row(conn, board_id, loop_id, card_id)
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
                    changes={
                        "completed": existing["completed_at"] is not None,
                        "still_required": existing.get("plan_item_id") is not None,
                    },
                )
            row = self._card_row(conn, board_id, loop_id, card_id)
            return self._decorate(conn, board_id, loop, [row])[0]

    def restore(
        self, actor: ActorContext, board_id: str, loop_id: str, card_id: str
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            loop = self._loop_row(conn, board_id, loop_id)
            self._require_writable(loop)
            existing = self._card_row(conn, board_id, loop_id, card_id)
            if existing["archived_at"] is not None:
                position = position_for_index(
                    conn, "cards", {"list_id": existing["list_id"]}, None
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
            row = self._card_row(conn, board_id, loop_id, card_id)
            return self._decorate(conn, board_id, loop, [row])[0]

    def transfer(
        self, actor: ActorContext, board_id: str, loop_id: str, card_id: str
    ) -> dict[str, Any]:
        """Cross-Loop and cross-Board moves bypass the approved plan; they are not supported."""
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.reader(board_id) as conn:
            self._loop_row(conn, board_id, loop_id)
            self._card_row(conn, board_id, loop_id, card_id)
        raise Conflict(
            "Tickets cannot be transferred between Loops or Boards; amend the destination plan",
            code=PLAN_CHANGE_CODE,
            details={"card_id": card_id, "loop_id": loop_id},
        )

    def stats(self, board_id: str, card_id: str) -> dict[str, int]:
        with self.boards.reader(board_id) as conn:
            return card_counts(conn, [card_id]).get(
                card_id, {"checklist_total": 0, "checklist_completed": 0, "comment_count": 0}
            )
