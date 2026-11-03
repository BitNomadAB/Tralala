"""Loop ownership, lifecycle stage and machine-readable readiness.

A Loop owns its Kanban, planning documents, Phases and Tickets. A Board is a container of Loops
and its database remains the storage boundary. Every other Loop service takes its ownership
checks and stage computation from here so REST, the UI and WebMCP cannot disagree.

The rules are module functions over typed rows and the board repositories (``require_loop``,
``ensure_writable``, ``ensure_execution_allowed``, ``refresh_stage`` and the pure stage functions),
so ``CardService`` and the Loop workflow services share them; ``LoopService`` reaches the board
database only through the board unit of work, the registry only through ``BoardChecks`` and the
plan only through ``PlanViews``, and takes the clock and the id source as arguments, so every rule
here runs in a unit test without a database.

The stage rules live in ``loops_stage``, the Loop's JSON in ``loops_views`` and the shared rules
in ``loops_rules``; this module keeps ``LoopService`` and re-exports their names, so every caller
imports them from here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from pydantic import JsonValue

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, NotFound, ValidationFailure, VersionConflict
from ..db.generated.board import ListsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.loops import LoopChanges
from ..schemas.loops import (
    DOCUMENT_KINDS,
    HumanConfirmation,
    LoopCancel,
    LoopCreate,
    LoopUpdate,
)
from . import idempotency
from .activity import activity_entry
from .lists import BoardChecks
from .loop_identifiers import format_loop_key, loop_prefix
from .loops_rules import (
    ensure_execution_allowed,
    ensure_ticket_writable,
    ensure_writable,
    readiness_item,
    refresh_stage,
    require_loop,
)
from .loops_stage import (
    ANALYSIS_KINDS,
    EXECUTION_STAGES,
    OPEN_STAGES,
    QA_OPEN_STATUSES,
    ROADMAP_KINDS,
    Approvals,
    DocumentEntry,
    DocumentSlot,
    DocumentSlots,
    DocumentState,
    StaleReasons,
    analysis_approved,
    compute_stage,
    document_entry,
    document_slots,
    document_state,
    latest_approvals,
    roadmap_approved,
    stale_reasons,
)
from .loops_views import (
    LoopEntry,
    LoopFacts,
    LoopWarning,
    PlanSummary,
    Progress,
    QaSummary,
    board_loop_facts,
    loop_entry,
    loop_facts,
    loop_warnings,
    plan_summary,
    progress_entry,
    qa_summary,
)
from .plan_views import PlanView, PlanViews, Readiness

if TYPE_CHECKING:
    from .cards import CardEntry


# --- the service ---------------------------------------------------------------------------------


class TicketReader(Protocol):
    """What LoopService needs from CardService: a Ticket as the API returns it."""

    def get(self, board_id: str, loop_id: str, card_id: str) -> CardEntry: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


def _column_names(raw: str) -> list[JsonValue]:
    """The stored default column names, as iterating the decoded JSON always read them: a list's
    items, an object's keys, a string's characters; unreadable JSON or ``null`` names none, and a
    number raises the ``TypeError`` iterating it raised."""
    try:
        value: JsonValue = json.loads(raw)
    except ValueError:
        return []
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value)
    if isinstance(value, str):
        return list(value)
    raise TypeError(f"'{type(value).__name__}' object is not iterable")


class LoopService:
    def __init__(
        self,
        settings: Settings,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        *,
        plans: PlanViews,
        tickets: TicketReader,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.settings = settings
        self.boards = boards
        self.store = store
        self.plans = plans
        self.tickets = tickets
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    # --- reads -----------------------------------------------------------------------------------

    def list(
        self,
        board_id: str,
        *,
        include_completed: bool = False,
        stage: str | None = None,
        include_archived: bool = False,
    ) -> list[LoopEntry]:
        self.boards.require_row(board_id)
        if not self.store.exists(board_id):
            raise NotFound("Board database not found")
        with self.store.reader(board_id) as repos:
            loops = repos.loops.listing(
                include_archived=include_archived,
                include_completed=include_completed,
                stage=stage or None,
            )
            if not loops:
                return []
            facts = board_loop_facts(repos)
        return [loop_entry(board_id, loop, facts.get(loop.id, LoopFacts())) for loop in loops]

    def get(self, board_id: str, loop_id: str) -> LoopEntry:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return self.serialize(repos, board_id, require_loop(repos, loop_id))

    @staticmethod
    def serialize(repos: BoardRepositories, board_id: str, loop: LoopsRow) -> LoopEntry:
        return loop_entry(board_id, loop, loop_facts(repos, loop.id))

    def plan(self, board_id: str, loop_id: str) -> PlanView:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return self.plans.plan_view(repos, require_loop(repos, loop_id))

    def readiness(self, board_id: str, loop_id: str) -> Readiness:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return self.plans.readiness(repos, require_loop(repos, loop_id))

    # --- writes ----------------------------------------------------------------------------------

    def create(
        self,
        actor: ActorContext,
        board_id: str,
        payload: LoopCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[LoopEntry | idempotency.JsonObject, bool]:
        """The new Loop and False, or the answer stored for a replayed key and True."""
        actor.require("loops:write")
        self.boards.ensure_active(board_id)
        fingerprint = idempotency.request_fingerprint(
            {"op": "loop.create", "board_id": board_id, "payload": payload.model_dump()}
        )
        loop_id = self._new_id()
        now = self._now()
        with self.store.writer(board_id) as repos:
            if idempotency_key:
                stored = idempotency.stored_answer(
                    repos.idempotency,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    now=self._clock(),
                )
                if stored is not None:
                    return stored, True
            loop = self._create(repos, actor, board_id, loop_id, payload, now)
            if idempotency_key:
                idempotency.remember(
                    repos.idempotency,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    answer=loop,
                    now=self._clock(),
                    ttl_seconds=self.settings.idempotency_ttl_seconds,
                )
        return loop, False

    def _create(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: LoopCreate,
        now: str,
    ) -> LoopEntry:
        sequence = repos.loops.next_sequence()
        prefix = loop_prefix(payload.name)
        key = format_loop_key(prefix, sequence)
        repos.loops.add(
            LoopsRow(
                id=loop_id,
                name=payload.name,
                goal=payload.goal,
                sequence=sequence,
                key_prefix=prefix,
                key=key,
                stage="draft",
                version=1,
                current_plan_id=None,
                analysis_approval_id=None,
                roadmap_approval_id=None,
                implementation_approval_id=None,
                qa_approval_id=None,
                active_qa_cycle_id=None,
                history_id=None,
                created_by_actor_id=actor.actor_id,
                created_by_actor_type=actor.actor_type,
                created_by_name=actor.actor_name,
                created_at=now,
                updated_at=now,
                archived_at=None,
                cancelled_at=None,
                completed_at=None,
            )
        )
        names = payload.column_names or self._default_columns(repos)
        if not names:
            names = list(self.settings.list_names)
        for index, name in enumerate(names):
            repos.lists.add(
                ListsRow(
                    id=self._new_id(),
                    name=name,
                    position=(index + 1) * 1024,
                    created_at=now,
                    updated_at=now,
                    archived_at=None,
                    loop_id=loop_id,
                )
            )
        self._log(
            repos,
            actor,
            "loop.created",
            "loop",
            loop_id,
            {"name": payload.name, "key": key, "columns": names},
        )
        return self.serialize(repos, board_id, require_loop(repos, loop_id))

    @staticmethod
    def _default_columns(repos: BoardRepositories) -> list[str]:
        """The board's default columns for a new Loop; blank names are left out."""
        row = repos.loop_defaults.get()
        names = _column_names(row.column_names_json) if row is not None else []
        return [str(name) for name in names if str(name).strip()]

    def update(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: LoopUpdate
    ) -> LoopEntry:
        actor.require("loops:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            existing = require_loop(repos, loop_id)
            ensure_writable(existing)
            _check_version(existing, payload.version)
            changes: LoopChanges = {}
            logged: dict[str, object] = {}
            if payload.name is not None and payload.name != existing.name:
                changes["name"] = payload.name
                logged["name"] = {"before": existing.name, "after": payload.name}
            if payload.goal is not None and payload.goal != existing.goal:
                changes["goal"] = payload.goal
                logged["goal"] = {"changed": True}
            if changes:
                changes["version"] = existing.version + 1
                changes["updated_at"] = self._now()
                repos.loops.update(loop_id, changes)
                self._log(repos, actor, "loop.updated", "loop", loop_id, logged)
                refresh_stage(repos, loop_id, now=self._now())
            return self.serialize(repos, board_id, require_loop(repos, loop_id))

    def cancel(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: LoopCancel
    ) -> LoopEntry:
        actor.require_human("Cancelling a Loop")
        actor.require("loops:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            existing = require_loop(repos, loop_id)
            ensure_writable(existing)
            _check_version(existing, payload.version)
            repos.loops.cancel(loop_id, now=self._now())
            self._log(repos, actor, "loop.cancelled", "loop", loop_id, {"reason": payload.reason})
            return self.serialize(repos, board_id, require_loop(repos, loop_id))

    def archive(self, actor: ActorContext, board_id: str, loop_id: str) -> LoopEntry:
        actor.require("loops:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            existing = require_loop(repos, loop_id)
            if existing.archived_at is None:
                repos.loops.archive(loop_id, now=self._now())
                self._log(repos, actor, "loop.archived", "loop", loop_id)
            return self.serialize(repos, board_id, require_loop(repos, loop_id))

    def confirm_human_ticket(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: HumanConfirmation,
    ) -> CardEntry:
        """A human confirms that a human-only Ticket was performed."""
        actor.require_human("Confirming a human-only Ticket")
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            card = repos.cards.get(card_id)
            if card is None or card.loop_id != loop_id:
                raise NotFound("Ticket not found")
            if card.version != payload.version:
                raise VersionConflict(
                    "Ticket was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": card.version,
                    },
                )
            if card.required_actor != "human":
                raise ValidationFailure(
                    "This Ticket does not require a human action",
                    details={"ticket_id": card_id},
                )
            ensure_execution_allowed(loop)
            item = readiness_item(self.plans.readiness(repos, loop), card_id)
            if item is not None and not item["ready"]:
                raise Conflict(
                    "This human action is not available yet",
                    code="ticket_blocked",
                    details={"blockers": item["blockers"]},
                )
            repos.cards.confirm_human(card_id, actor.actor_id, now=self._now())
            self._log(
                repos,
                actor,
                "card.human_confirmed",
                "card",
                card_id,
                {"note": payload.note, "ticket_key": card.ticket_key},
            )
            refresh_stage(repos, loop_id, now=self._now())
        return self.tickets.get(board_id, loop_id, card_id)

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        entity_type: str,
        entity_id: str,
        changes: Mapping[str, object] | None = None,
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=self._now(),
            )
        )


def _check_version(loop: LoopsRow, expected: int) -> None:
    if loop.version != expected:
        raise VersionConflict(
            "Loop was modified by another actor",
            details={"expected_version": expected, "current_version": loop.version},
        )


__all__ = [
    "ANALYSIS_KINDS",
    "DOCUMENT_KINDS",
    "EXECUTION_STAGES",
    "OPEN_STAGES",
    "QA_OPEN_STATUSES",
    "ROADMAP_KINDS",
    "Approvals",
    "DocumentEntry",
    "DocumentSlot",
    "DocumentSlots",
    "DocumentState",
    "LoopEntry",
    "LoopFacts",
    "LoopService",
    "LoopWarning",
    "PlanSummary",
    "Progress",
    "QaSummary",
    "StaleReasons",
    "TicketReader",
    "analysis_approved",
    "board_loop_facts",
    "compute_stage",
    "document_entry",
    "document_slots",
    "document_state",
    "ensure_execution_allowed",
    "ensure_ticket_writable",
    "ensure_writable",
    "latest_approvals",
    "loop_entry",
    "loop_facts",
    "loop_warnings",
    "plan_summary",
    "progress_entry",
    "qa_summary",
    "readiness_item",
    "refresh_stage",
    "require_loop",
    "roadmap_approved",
    "stale_reasons",
]
