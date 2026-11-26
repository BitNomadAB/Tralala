"""Tickets: Loop-scoped cards with version checks, readiness and human gates.

A Ticket is the existing card resource, extended with Loop ownership, a stable key, its Phase and
its approved work definition. Completion stays explicit through ``completed_at``; a column name
never marks work done, and every completion transition runs through the same readiness rules an
agent's start request would face.

The service reaches the board database only through the board unit of work, the registry (to
check an assignee) only through the registry unit of work, the board's registry row through
``BoardChecks`` and the plan through ``PlanViews``; the clock and the id source are passed in, so
every rule here runs in a unit test without a database.

A key (an issued API token, which is an actor of its own) reports before it takes another Ticket:
``move`` refuses it a Ticket while another Ticket it took has no comment, wait or completion from it
since (``409 report_required``, naming them). Moving that same Ticket, or putting a Ticket back in
the Loop's first column, is never refused, and neither is a person or an internal role agent, which
has no credential. ``unreported`` is the same read for the worker tools. Every Ticket the service
answers carries ``unreported_since``, read for all of them at once, so the board marks a Ticket a
key took and has not reported on, the last one of a working session included.

The JSON shapes live in ``cards_views`` and the inserting and editing writes in ``cards_writes``;
this module keeps the service, its checks and guards, and re-exports what callers import from it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc, parse_due_filter
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..db.generated.board import CardsRow, ListsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.cards import CardQuery
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.cards import BulkCardCreate, CardCreate, CardMove, CardUpdate
from . import idempotency
from .cards_views import (
    BoardTicketEntry,
    BulkFailure,
    BulkResult,
    CardEntry,
    CardRecord,
    UnreportedEntry,
    card_entry,
    card_record,
    card_sort,
    unreported_entry,
)
from .cards_writes import (
    NEW_LABEL_COLOR,
    apply_update,
    card_position,
    check_version,
    insert_card,
    log_card,
    require_writable,
    ticket_in_loop,
)
from .lists import BoardChecks
from .loops import (
    EXECUTION_STAGES,
    ensure_execution_allowed,
    readiness_item,
    refresh_stage,
    require_loop,
)
from .plan_views import PlanViews, ReadinessItem
from .subresources import label_entries
from .ticket_state import ensure_not_waiting, loop_closed

__all__ = [
    "NEW_LABEL_COLOR",
    "PLAN_CHANGE_CODE",
    "REPORT_MEANS",
    "REPORT_REQUIRED_CODE",
    "BoardTicketEntry",
    "BulkFailure",
    "BulkResult",
    "CardEntry",
    "CardRecord",
    "CardService",
    "UnreportedEntry",
    "card_entry",
    "card_record",
    "card_sort",
]

logger = logging.getLogger("tralala.cards")

PLAN_CHANGE_CODE = "plan_change_required"
REPORT_REQUIRED_CODE = "report_required"
# What counts as a report, in the words the refusal gives a key.
REPORT_MEANS = "A comment, a wait or a completion on the Ticket since you took it"


def _owes_reports(actor: ActorContext) -> bool:
    """An issued key: not a person, and authenticated by a credential. An internal role agent is
    an agent too, but has none."""
    return not actor.is_user and actor.credential_id is not None


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
        return ticket_in_loop(repos, loop_id, card_id)

    @staticmethod
    def _require_writable(loop: LoopsRow) -> None:
        require_writable(loop)

    @staticmethod
    def _check_version(card: CardsRow, expected: int) -> None:
        check_version(card, expected)

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
        # One read for every listed card: when a key took each one and has not reported since.
        unreported = repos.cards.unreported_since(ids)
        readiness: dict[str, ReadinessItem] = {}
        if loop.current_plan_id:
            for item in self.plans.readiness(repos, loop)["items"]:
                if item["card_id"]:
                    readiness[item["card_id"]] = item
        closed = loop_closed(loop)
        return [
            card_entry(
                board_id,
                row,
                labels[row.id],
                counts[row.id],
                readiness.get(row.id),
                loop_closed=closed,
                unreported_since=unreported[row.id],
            )
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
        return card_position(repos, list_id, index, exclude=exclude)

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        card_id: str,
        changes: Mapping[str, object] | None = None,
    ) -> None:
        log_card(repos, actor, action, card_id, changes, new_id=self._new_id, now=self._now)

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

    def unreported(self, board_id: str, actor: ActorContext) -> list[UnreportedEntry]:
        """The Tickets on the board the key took and has not reported on since, oldest first.

        Empty for a person and for an actor without a credential, whom the rule never refuses.
        """
        self.boards.require_row(board_id)
        if not _owes_reports(actor):
            return []
        with self.store.reader(board_id) as repos:
            tickets = repos.cards.unreported_by(actor.actor_id)
        return [unreported_entry(ticket) for ticket in tickets]

    # --- writes ----------------------------------------------------------------------------------

    def _insert_card(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        loop: LoopsRow,
        payload: CardCreate,
        *,
        known_labels_only: bool = False,
    ) -> CardsRow:
        return insert_card(
            repos,
            actor,
            loop,
            payload,
            new_id=self._new_id,
            now=self._now,
            known_labels_only=known_labels_only,
        )

    def _loop_taking_new_work(self, repos: BoardRepositories, loop_id: str) -> LoopsRow:
        loop = require_loop(repos, loop_id)
        self._require_writable(loop)
        # A Loop with a plan takes work outside it only while it executes; that work is keyed
        # <LoopKey>-UNP-<nnn> and never blocks readiness or completion.
        if loop.current_plan_id and loop.stage not in EXECUTION_STAGES:
            raise Conflict(
                "This Loop's plan is not executing; amend the plan or wait for it to run",
                code=PLAN_CHANGE_CODE,
                details={"loop_id": loop_id, "stage": loop.stage},
            )
        return loop

    def _refresh_without_plan(self, repos: BoardRepositories, loop: LoopsRow) -> None:
        """A Loop without a plan is under way while it holds Tickets (``compute_stage``), so adding,
        archiving or restoring one keeps its stage in step; a planned Loop's stage follows its
        plan and does not change here."""
        if loop.current_plan_id is None:
            refresh_stage(repos, loop.id, now=self._now())

    def create(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: CardCreate,
        *,
        idempotency_key: str | None = None,
        known_labels_only: bool = False,
    ) -> tuple[CardEntry | idempotency.JsonObject, bool]:
        """The new Ticket and False, or the answer stored for a replayed key and True. With
        ``known_labels_only`` a label the board does not have is refused, not created."""
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
            row = self._insert_card(
                repos, actor, loop, payload, known_labels_only=known_labels_only
            )
            self._refresh_without_plan(repos, loop)
            entry = self._decorate(repos, board_id, loop, [row])[0]
            if idempotency_key:
                self._remember(repos, actor, idempotency_key, fingerprint, entry)
        return entry, False

    def add_in_writer(
        self, repos: BoardRepositories, actor: ActorContext, loop_id: str, payload: CardCreate
    ) -> CardsRow:
        """A new Ticket inside the caller's writer, through the checks and writes ``create`` makes
        (a Loop that takes new work in its stage, the column, the key, the activity entry, the
        stage of a Loop without a plan), so a caller that stores something with the Ticket keeps
        both or neither. The caller checks ``cards:write`` and that the board takes writes."""
        loop = self._loop_taking_new_work(repos, loop_id)
        row = self._insert_card(repos, actor, loop, payload)
        self._refresh_without_plan(repos, loop)
        return row

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
            if result["created"]:
                self._refresh_without_plan(repos, loop)
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
            apply_update(
                repos,
                actor,
                loop,
                existing,
                payload,
                accounts=self.accounts,
                new_id=self._new_id,
                now=self._now,
            )
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
        ensure_not_waiting(existing)
        item = self._readiness_for(repos, loop, existing.id)
        if item is not None and not item["ready"]:
            raise Conflict(
                "This Ticket is blocked by unresolved prerequisites",
                code="ticket_blocked",
                details={"blockers": item["blockers"], "ticket_key": existing.ticket_key},
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
            self._require_reports(repos, actor, card_id, target)
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

    @staticmethod
    def _require_reports(
        repos: BoardRepositories, actor: ActorContext, card_id: str, target: ListsRow
    ) -> None:
        """A key that took another Ticket and has not reported on it since is refused the move,
        ``409 report_required`` naming those Tickets.

        It runs in the move's own transaction, after its other checks and before anything is
        written, so the check and the move see the same board. The Ticket being moved is left out,
        so a key moves its own Ticket onward; a move to the Loop's first column puts work back and
        is never refused.
        """
        if not _owes_reports(actor):
            return
        columns = repos.lists.for_loop(target.loop_id, include_archived=False)
        if columns and columns[0].id == target.id:
            return
        taken = repos.cards.unreported_by(actor.actor_id)
        owed = [ticket for ticket in taken if ticket.card.id != card_id]
        if owed:
            raise Conflict(
                "Report on the Tickets you took before you take another one",
                code=REPORT_REQUIRED_CODE,
                details={
                    "tickets": [unreported_entry(ticket) for ticket in owed],
                    "report": REPORT_MEANS,
                },
            )

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
                self._refresh_without_plan(repos, loop)
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
                self._refresh_without_plan(repos, loop)
            row = self._card(repos, loop_id, card_id)
            return self._decorate(repos, board_id, loop, [row])[0]
