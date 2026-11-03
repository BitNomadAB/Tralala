"""Tickets: Loop-scoped cards with version checks, readiness and human gates.

A Ticket is the existing card resource, extended with Loop ownership, a stable key, its Phase and
its approved work definition. Completion stays explicit through ``completed_at``; a column name
never marks work done, and every completion transition runs through the same readiness rules an
agent's start request would face.

The service reaches the board database only through the board unit of work, the registry (to
check an assignee) only through the registry unit of work, the board's registry row through
``BoardChecks`` and the plan through ``PlanViews``; the clock and the id source are passed in, so
every rule here runs in a unit test without a database.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NotRequired, TypedDict
from uuid import uuid4

from pydantic import JsonValue

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc, parse_due_filter
from ..core.errors import Conflict, NotFound, ValidationFailure, VersionConflict
from ..db.generated.board import CardsRow, LabelsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.cards import CardChanges, CardCounts, CardQuery, CardSort
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.cards import BulkCardCreate, CardCreate, CardMove, CardUpdate
from . import idempotency
from .activity import activity_entry
from .lists import BoardChecks
from .loops import ensure_execution_allowed, readiness_item, refresh_stage, require_loop
from .ordering import place
from .plan_views import Blocker, PlanViews, ReadinessItem
from .subresources import ChecklistEntry, CommentEntry, LabelEntry, label_entries

logger = logging.getLogger("tralala.cards")

PLAN_CHANGE_CODE = "plan_change_required"
NEW_LABEL_COLOR = "#64748b"
SYSTEM_ACTOR = ActorContext(actor_id="system", actor_type="system", actor_name="Tralala")


class CardRecord(TypedDict):
    """A card's row as the API returns it."""

    id: str
    list_id: str
    title: str
    description: str
    position: int
    priority: str
    due_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    version: int
    assignee_actor_id: str | None
    assignee_type: str | None
    assignee_name: str | None
    assigned_at: str | None
    assigned_by_actor_id: str | None
    loop_id: str
    phase_id: str | None
    plan_item_id: str | None
    ticket_key: str | None
    kind: str
    required_actor: str
    execution_mode: str
    human_action_reason: str
    human_instructions: str
    human_confirmed_at: str | None
    human_confirmed_by_actor_id: str | None
    plan_revision_id: str | None


class CardEntry(CardRecord):
    """A Ticket as the API returns it: its row, labels and counts, and its readiness."""

    board_id: str
    labels: list[LabelEntry]
    checklist_total: int
    checklist_completed: int
    comment_count: int
    human_action_required: bool
    ready: bool
    blockers: list[Blocker]
    downstream_phase_numbers: list[int]
    acceptance_criteria: JsonValue
    expected_evidence: JsonValue
    phase_number: int | None
    # The card route adds these when the request asks for them (``?include=``).
    checklists: NotRequired[list[ChecklistEntry]]
    comments: NotRequired[list[CommentEntry]]


class BoardTicketEntry(CardRecord):
    """A Ticket in the board-wide list: its row, its Loop, its labels and counts."""

    loop_key: str
    loop_name: str
    loop_stage: str
    board_id: str
    labels: list[LabelEntry]
    checklist_total: int
    checklist_completed: int
    comment_count: int


class BulkFailure(TypedDict):
    index: int
    code: str
    message: str


class BulkResult(TypedDict):
    created: list[CardEntry]
    failed: list[BulkFailure]


@dataclass(frozen=True, slots=True, kw_only=True)
class Assignee:
    actor_id: str
    type: str
    name: str


def card_record(row: CardsRow) -> CardRecord:
    return {
        "id": row.id,
        "list_id": row.list_id,
        "title": row.title,
        "description": row.description,
        "position": row.position,
        "priority": row.priority,
        "due_at": row.due_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "archived_at": row.archived_at,
        "version": row.version,
        "assignee_actor_id": row.assignee_actor_id,
        "assignee_type": row.assignee_type,
        "assignee_name": row.assignee_name,
        "assigned_at": row.assigned_at,
        "assigned_by_actor_id": row.assigned_by_actor_id,
        "loop_id": row.loop_id,
        "phase_id": row.phase_id,
        "plan_item_id": row.plan_item_id,
        "ticket_key": row.ticket_key,
        "kind": row.kind,
        "required_actor": row.required_actor,
        "execution_mode": row.execution_mode,
        "human_action_reason": row.human_action_reason,
        "human_instructions": row.human_instructions,
        "human_confirmed_at": row.human_confirmed_at,
        "human_confirmed_by_actor_id": row.human_confirmed_by_actor_id,
        "plan_revision_id": row.plan_revision_id,
    }


def card_entry(
    board_id: str,
    row: CardsRow,
    labels: list[LabelsRow],
    counts: CardCounts,
    item: ReadinessItem | None,
) -> CardEntry:
    """A Ticket's JSON; ``item`` is its planned Ticket's readiness, if the plan has one."""
    if item is not None:
        human_action_required = bool(item["human_action_required"])
    else:
        human_action_required = row.required_actor == "human" and row.completed_at is None
    return {
        **card_record(row),
        "board_id": board_id,
        "labels": label_entries(labels),
        "checklist_total": counts.checklist_total,
        "checklist_completed": counts.checklist_completed,
        "comment_count": counts.comment_count,
        "human_action_required": human_action_required,
        "ready": bool(item["ready"]) if item is not None else True,
        "blockers": item["blockers"] if item is not None else [],
        "downstream_phase_numbers": item["downstream_phase_numbers"] if item is not None else [],
        "acceptance_criteria": item["acceptance_criteria"] if item is not None else [],
        "expected_evidence": item["expected_evidence"] if item is not None else [],
        "phase_number": item["phase_number"] if item is not None else None,
    }


def card_sort(sort: str) -> CardSort:
    """A sort column the list knows; anything else sorts by position."""
    match sort:
        case "created_at" | "updated_at" | "due_at" | "title":
            return sort
        case _:
            return "position"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class CardService:
    def __init__(
        self,
        settings: Settings,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        accounts: RegistryUnitOfWork,
        *,
        plans: PlanViews,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.settings = settings
        self.boards = boards
        self.store = store
        self.accounts = accounts
        self.plans = plans
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    # --- rules -----------------------------------------------------------------------------------

    @staticmethod
    def _card(repos: BoardRepositories, loop_id: str, card_id: str) -> CardsRow:
        row = repos.cards.get(card_id)
        if row is None:
            raise NotFound("Card not found")
        if row.loop_id != loop_id:
            raise Conflict(
                "The Ticket belongs to another Loop",
                code="loop_mismatch",
                details={"loop_id": loop_id, "ticket_loop_id": row.loop_id},
            )
        return row

    @staticmethod
    def _require_writable(loop: LoopsRow) -> None:
        if loop.completed_at is not None or loop.stage == "completed":
            raise Conflict(
                "This Loop is completed and read-only",
                code="loop_read_only",
                details={"loop_id": loop.id},
            )
        if loop.archived_at is not None or loop.cancelled_at is not None:
            raise Conflict(
                "This Loop is not editable",
                code="loop_read_only",
                details={"loop_id": loop.id},
            )

    @staticmethod
    def _check_version(card: CardsRow, expected: int) -> None:
        if card.version != expected:
            raise VersionConflict(
                "Card was modified by another actor",
                details={"expected_version": expected, "current_version": card.version},
            )

    def _readiness_for(
        self, repos: BoardRepositories, loop: LoopsRow, card_id: str
    ) -> ReadinessItem | None:
        if not loop.current_plan_id:
            return None
        return readiness_item(self.plans.readiness(repos, loop), card_id)

    def _decorate(
        self, repos: BoardRepositories, board_id: str, loop: LoopsRow, rows: Sequence[CardsRow]
    ) -> list[CardEntry]:
        ids = [row.id for row in rows]
        labels = repos.cards.labels(ids)
        counts = repos.cards.counts(ids)
        readiness: dict[str, ReadinessItem] = {}
        if loop.current_plan_id:
            for item in self.plans.readiness(repos, loop)["items"]:
                if item["card_id"]:
                    readiness[item["card_id"]] = item
        return [
            card_entry(board_id, row, labels[row.id], counts[row.id], readiness.get(row.id))
            for row in rows
        ]

    def _position(
        self,
        repos: BoardRepositories,
        list_id: str,
        index: int | None,
        *,
        exclude: str | None = None,
    ) -> int:
        placement = place(repos.cards.positions(list_id, exclude=exclude), index)
        if placement.renumbered:
            repos.cards.renumber(placement.renumbered)
        return placement.position

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        card_id: str,
        changes: Mapping[str, object] | None = None,
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="card",
                entity_id=card_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=self._now(),
            )
        )

    # --- reads -----------------------------------------------------------------------------------

    def require_membership(self, board_id: str, loop_id: str, card_id: str) -> None:
        """Cheap ownership check for routes that address a Ticket through its Loop."""
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            self._card(repos, loop_id, card_id)

    def locate(self, board_id: str, card_id: str) -> tuple[str, CardRecord]:
        """Which Loop owns a Ticket.

        Board-level callers (the worker tools) are handed a Ticket id and nothing else, so the
        owning Loop is resolved here instead of being guessed. The row is returned so a caller can
        use its version without a second read.
        """
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            row = repos.cards.get(card_id)
            if row is None or repos.loops.get(row.loop_id) is None:
                raise NotFound("Ticket not found")
        return row.loop_id, card_record(row)

    def get(self, board_id: str, loop_id: str, card_id: str) -> CardEntry:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            loop = require_loop(repos, loop_id)
            row = self._card(repos, loop_id, card_id)
            return self._decorate(repos, board_id, loop, [row])[0]

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
    ) -> tuple[list[CardEntry], int]:
        self.boards.require_row(board_id)
        due = parse_due_filter(due_before) if due_before else None
        query = CardQuery(
            loop_id=loop_id,
            include_archived=include_archived,
            list_id=list_id or None,
            contains=q or None,
            label=label or None,
            priority=priority or None,
            due_before=due,
            overdue_at=self._now() if overdue else None,
            completed=completed,
            unassigned=assignee == "unassigned",
            assignee=assignee or None,
        )
        with self.store.reader(board_id) as repos:
            loop = require_loop(repos, loop_id)
            if due_before and due is None:
                # A blank due filter compares with NULL, which matches no card (it always did).
                return [], 0
            total = repos.cards.count(query)
            rows = repos.cards.page(
                query,
                sort=card_sort(sort),
                descending=order.lower() == "desc",
                limit=limit,
                offset=offset,
            )
            return self._decorate(repos, board_id, loop, rows), total

    def list_board_tickets(
        self, board_id: str, *, q: str | None = None, limit: int = 200
    ) -> list[BoardTicketEntry]:
        """Explicit Board-level aggregate read; every row identifies its owning Loop."""
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            tickets = repos.cards.board_tickets(contains=q or None, limit=limit)
            ids = [ticket.card.id for ticket in tickets]
            labels = repos.cards.labels(ids)
            counts = repos.cards.counts(ids)
        return [
            {
                **card_record(ticket.card),
                "loop_key": ticket.loop_key,
                "loop_name": ticket.loop_name,
                "loop_stage": ticket.loop_stage,
                "board_id": board_id,
                "labels": label_entries(labels[ticket.card.id]),
                "checklist_total": counts[ticket.card.id].checklist_total,
                "checklist_completed": counts[ticket.card.id].checklist_completed,
                "comment_count": counts[ticket.card.id].comment_count,
            }
            for ticket in tickets
        ]

    # --- writes ----------------------------------------------------------------------------------

    def _label_ids(self, repos: BoardRepositories, references: Sequence[str]) -> list[str]:
        """Labels may be referenced by id or by name; unknown names are created."""
        resolved: list[str] = []
        for raw in references:
            reference = raw.strip()
            if not reference:
                continue
            found = repos.labels.find(reference)
            if found is None:
                label_id = self._new_id()
                repos.labels.add(LabelsRow(id=label_id, name=reference, color=NEW_LABEL_COLOR))
            else:
                label_id = found.id
            if label_id not in resolved:
                resolved.append(label_id)
        return resolved

    def _insert_card(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        loop: LoopsRow,
        payload: CardCreate,
    ) -> CardsRow:
        list_id = payload.list_id
        active = {row.id for row in repos.lists.for_loop(loop.id, include_archived=False)}
        if list_id not in active:
            other = repos.lists.get(list_id)
            if other is not None and other.loop_id != loop.id:
                raise Conflict(
                    "The column belongs to another Loop",
                    code="loop_mismatch",
                    details={"list_id": list_id},
                )
            raise ValidationFailure(
                "List does not exist or is archived", details={"list_id": list_id}
            )
        card_id = self._new_id()
        now = self._now()
        repos.cards.add(
            CardsRow(
                id=card_id,
                list_id=list_id,
                title=payload.title,
                description=payload.description,
                position=self._position(repos, list_id, None),
                priority=payload.priority,
                due_at=payload.due_at,
                completed_at=None,
                created_at=now,
                updated_at=now,
                archived_at=None,
                version=1,
                assignee_actor_id=None,
                assignee_type=None,
                assignee_name=None,
                assigned_at=None,
                assigned_by_actor_id=None,
                loop_id=loop.id,
                phase_id=None,
                plan_item_id=None,
                ticket_key=None,
                kind="manual",
                required_actor="any",
                execution_mode="normal",
                human_action_reason="",
                human_instructions="",
                human_confirmed_at=None,
                human_confirmed_by_actor_id=None,
                plan_revision_id=None,
            )
        )
        if payload.labels:
            repos.cards.set_labels(card_id, self._label_ids(repos, payload.labels))
        row = self._card(repos, loop.id, card_id)
        self._log(
            repos,
            actor,
            "card.created",
            card_id,
            {"title": payload.title, "list_id": list_id, "loop_id": loop.id},
        )
        return row

    def _loop_taking_new_work(self, repos: BoardRepositories, loop_id: str) -> LoopsRow:
        loop = require_loop(repos, loop_id)
        self._require_writable(loop)
        if loop.current_plan_id:
            raise Conflict(
                "This Loop executes an approved plan; amend the plan to add work",
                code=PLAN_CHANGE_CODE,
                details={"loop_id": loop_id},
            )
        return loop

    def create(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: CardCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[CardEntry | idempotency.JsonObject, bool]:
        """The new Ticket and False, or the answer stored for a replayed key and True."""
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        fingerprint = idempotency.request_fingerprint(
            {
                "op": "card.create",
                "board_id": board_id,
                "loop_id": loop_id,
                "payload": payload.model_dump(),
            }
        )
        with self.store.writer(board_id) as repos:
            loop = self._loop_taking_new_work(repos, loop_id)
            if idempotency_key:
                stored = self._stored(repos, actor, idempotency_key, fingerprint)
                if stored is not None:
                    return stored, True
            row = self._insert_card(repos, actor, loop, payload)
            entry = self._decorate(repos, board_id, loop, [row])[0]
            if idempotency_key:
                self._remember(repos, actor, idempotency_key, fingerprint, entry)
        return entry, False

    def bulk_create(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: BulkCardCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[BulkResult | idempotency.JsonObject, bool]:
        """Each card in its own savepoint: one that fails is reported and leaves the others."""
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        if len(payload.cards) > self.settings.bulk_limit:
            raise ValidationFailure(
                "Bulk request exceeds the configured limit",
                details={"limit": self.settings.bulk_limit},
            )
        fingerprint = idempotency.request_fingerprint(
            {
                "op": "card.bulk_create",
                "board_id": board_id,
                "loop_id": loop_id,
                "payload": payload.model_dump(),
            }
        )
        with self.store.writer(board_id) as repos:
            loop = self._loop_taking_new_work(repos, loop_id)
            if idempotency_key:
                stored = self._stored(repos, actor, idempotency_key, fingerprint)
                if stored is not None:
                    return stored, True
            result: BulkResult = {"created": [], "failed": []}
            for index, card_payload in enumerate(payload.cards):
                try:
                    with repos.savepoint():
                        row = self._insert_card(repos, actor, loop, card_payload)
                        result["created"].append(self._decorate(repos, board_id, loop, [row])[0])
                except (ValidationFailure, Conflict) as exc:
                    result["failed"].append(
                        {"index": index, "code": "card_create_failed", "message": exc.message}
                    )
                except Exception:  # partial failure is the contract here
                    logger.exception("bulk card creation failed", extra={"index": index})
                    result["failed"].append(
                        {
                            "index": index,
                            "code": "card_create_failed",
                            "message": "Card could not be created",
                        }
                    )
            if idempotency_key:
                self._remember(repos, actor, idempotency_key, fingerprint, result)
        return result, False

    def _stored(
        self, repos: BoardRepositories, actor: ActorContext, key: str, fingerprint: str
    ) -> idempotency.JsonObject | None:
        return idempotency.stored_answer(
            repos.idempotency,
            actor_id=actor.actor_id,
            key=key,
            fingerprint=fingerprint,
            now=self._clock(),
        )

    def _remember(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        key: str,
        fingerprint: str,
        answer: Mapping[str, object],
    ) -> None:
        idempotency.remember(
            repos.idempotency,
            actor_id=actor.actor_id,
            key=key,
            fingerprint=fingerprint,
            answer=answer,
            now=self._clock(),
            ttl_seconds=self.settings.idempotency_ttl_seconds,
        )

    def _resolve_assignee(self, assignee_id: str) -> Assignee:
        """Validate a human actor or an enabled registry agent as the primary assignee."""
        with self.accounts.reader() as registry:
            person = registry.actors.enabled(assignee_id)
            agent = None if person is not None else registry.agents.get(assignee_id)
        if person is not None:
            return Assignee(actor_id=person.id, type=person.type, name=person.name)
        if agent is None:
            raise ValidationFailure(
                "Assignee must be a human user or a registered agent",
                details={"assignee_actor_id": assignee_id},
            )
        if not agent.enabled:
            raise ValidationFailure(
                "Agent is disabled and cannot be assigned",
                details={"assignee_actor_id": assignee_id},
            )
        return Assignee(actor_id=agent.id, type="agent", name=agent.name)

    def update(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: CardUpdate,
    ) -> CardEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            self._require_writable(loop)
            existing = self._card(repos, loop_id, card_id)
            self._check_version(existing, payload.version)
            self._guard_plan_scope(existing, payload)
            self._guard_completion(repos, loop, existing, payload, actor)
            logged: dict[str, object] = {}
            changes: CardChanges = {}
            if payload.title is not None and payload.title != existing.title:
                changes["title"] = payload.title
                logged["title"] = {"before": existing.title, "after": payload.title}
            if payload.description is not None and payload.description != existing.description:
                changes["description"] = payload.description
                logged["description"] = {"changed": True}
            if payload.priority is not None and payload.priority != existing.priority:
                changes["priority"] = payload.priority
                logged["priority"] = {"before": existing.priority, "after": payload.priority}
            if payload.clear_due_at:
                changes["due_at"] = None
                logged["due_at"] = {"before": existing.due_at, "after": None}
            elif payload.due_at is not None and payload.due_at != existing.due_at:
                changes["due_at"] = payload.due_at
                logged["due_at"] = {"before": existing.due_at, "after": payload.due_at}
            if payload.completed is not None:
                already = existing.completed_at is not None
                if payload.completed and not already:
                    changes["completed_at"] = self._now()
                    logged["completed"] = {"before": False, "after": True}
                    if existing.required_actor == "human":
                        changes["human_confirmed_at"] = self._now()
                        changes["human_confirmed_by_actor_id"] = actor.actor_id
                        logged["human_confirmation"] = {"actor_id": actor.actor_id}
                elif not payload.completed and already:
                    changes["completed_at"] = None
                    changes["human_confirmed_at"] = None
                    changes["human_confirmed_by_actor_id"] = None
                    logged["completed"] = {"before": True, "after": False}
                    self._invalidate_after_reopen(repos, loop, existing)
            if payload.labels is not None:
                repos.cards.set_labels(card_id, self._label_ids(repos, payload.labels))
                logged["labels"] = {"after": payload.labels}
            if payload.clear_assignee:
                changes["assignee_actor_id"] = None
                changes["assignee_type"] = None
                changes["assignee_name"] = None
                changes["assigned_at"] = None
                changes["assigned_by_actor_id"] = None
                logged["assignee"] = {"before": existing.assignee_actor_id, "after": None}
            elif payload.assignee_actor_id is not None:
                assignee = self._resolve_assignee(payload.assignee_actor_id)
                if assignee.actor_id != existing.assignee_actor_id:
                    changes["assignee_actor_id"] = assignee.actor_id
                    changes["assignee_type"] = assignee.type
                    changes["assignee_name"] = assignee.name
                    changes["assigned_at"] = self._now()
                    changes["assigned_by_actor_id"] = actor.actor_id
                    logged["assignee"] = {
                        "before": existing.assignee_actor_id,
                        "after": assignee.actor_id,
                        "name": assignee.name,
                        "type": assignee.type,
                    }
            if changes:
                changes["version"] = existing.version + 1
                changes["updated_at"] = self._now()
                repos.cards.update(card_id, changes)
            if logged:
                self._log(repos, actor, "card.updated", card_id, logged)
            if "completed" in logged:
                refresh_stage(repos, loop_id, now=self._now())
            row = self._card(repos, loop_id, card_id)
            return self._decorate(repos, board_id, loop, [row])[0]

    @staticmethod
    def _guard_plan_scope(existing: CardsRow, payload: CardUpdate) -> None:
        """The approved work definition is not editable through a card endpoint."""
        if not existing.plan_item_id:
            return
        if payload.title is not None and payload.title != existing.title:
            raise Conflict(
                "Changing an approved Ticket title needs a reviewed plan amendment",
                code=PLAN_CHANGE_CODE,
                details={"field": "title", "ticket_key": existing.ticket_key},
            )
        if payload.description is not None and payload.description != existing.description:
            raise Conflict(
                "Changing approved instructions needs a reviewed plan amendment",
                code=PLAN_CHANGE_CODE,
                details={"field": "description", "ticket_key": existing.ticket_key},
            )

    def _guard_completion(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        existing: CardsRow,
        payload: CardUpdate,
        actor: ActorContext,
    ) -> None:
        """Completing a Ticket faces the rules an agent's start would: stage, human, readiness.

        The Loop is writable here (``update`` checked it), so it is neither archived nor done.
        """
        if payload.completed is not True:
            return
        if existing.completed_at is not None:
            return
        if existing.archived_at is not None:
            raise Conflict(
                "Archived Tickets cannot be completed; restore it first",
                code="ticket_blocked",
                details={"ticket_id": existing.id},
            )
        if existing.plan_item_id or loop.current_plan_id:
            ensure_execution_allowed(loop)
        if existing.required_actor == "human":
            actor.require_human(f"Confirming {existing.ticket_key or 'this Ticket'}")
        item = self._readiness_for(repos, loop, existing.id)
        if item is not None and not item["ready"]:
            raise Conflict(
                "This Ticket is blocked by unresolved prerequisites",
                code="ticket_blocked",
                details={"blockers": item["blockers"], "ticket_key": existing.ticket_key},
            )

    def _invalidate_after_reopen(
        self, repos: BoardRepositories, loop: LoopsRow, card: CardsRow
    ) -> None:
        """Reopening a prerequisite invalidates QA evidence prepared against the old baseline."""
        now = self._now()
        repos.qa.supersede_open(loop.id, now=now)
        repos.loops.clear_delivery_approvals(loop.id, now=now)
        self._log(
            repos, SYSTEM_ACTOR, "loop.reopened_work", card.id, {"revalidation_required": True}
        )

    def move(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: CardMove,
    ) -> CardEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            self._require_writable(loop)
            existing = self._card(repos, loop_id, card_id)
            self._check_version(existing, payload.version)
            target = repos.lists.get(payload.list_id)
            if target is None or target.archived_at is not None:
                raise ValidationFailure(
                    "Target list does not exist or is archived",
                    details={"list_id": payload.list_id},
                )
            if target.loop_id != loop_id:
                raise Conflict(
                    "A Ticket cannot move to another Loop",
                    code="loop_mismatch",
                    details={"target_loop_id": target.loop_id},
                )
            position = self._position(repos, payload.list_id, payload.position, exclude=card_id)
            repos.cards.move(card_id, payload.list_id, position, now=self._now())
            self._log(
                repos,
                actor,
                "card.moved",
                card_id,
                {
                    "from_list_id": existing.list_id,
                    "to_list_id": payload.list_id,
                    "position": payload.position,
                },
            )
            row = self._card(repos, loop_id, card_id)
            return self._decorate(repos, board_id, loop, [row])[0]

    def archive(
        self, actor: ActorContext, board_id: str, loop_id: str, card_id: str
    ) -> CardEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            self._require_writable(loop)
            existing = self._card(repos, loop_id, card_id)
            if existing.archived_at is None:
                repos.cards.archive(card_id, now=self._now())
                self._log(
                    repos,
                    actor,
                    "card.archived",
                    card_id,
                    {
                        "completed": existing.completed_at is not None,
                        "still_required": existing.plan_item_id is not None,
                    },
                )
            row = self._card(repos, loop_id, card_id)
            return self._decorate(repos, board_id, loop, [row])[0]

    def restore(
        self, actor: ActorContext, board_id: str, loop_id: str, card_id: str
    ) -> CardEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        now = self._now()
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            self._require_writable(loop)
            existing = self._card(repos, loop_id, card_id)
            if existing.archived_at is not None:
                position = self._position(repos, existing.list_id, None)
                repos.cards.restore(card_id, position, now=now)
                self._log(repos, actor, "card.restored", card_id)
            row = self._card(repos, loop_id, card_id)
            return self._decorate(repos, board_id, loop, [row])[0]
