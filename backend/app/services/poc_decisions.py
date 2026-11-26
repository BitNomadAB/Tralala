"""POC decisions and what is missing from a person: recorded while the work goes on, answered by
a person afterwards.

An obstacle in a Loop is one of three kinds. A POC decision is a choice that can be changed
afterwards: the one who works takes it, records it here and goes on. Something missing from a
person (an API key, an account) is recorded the same way, as kind ``missing``, and the work goes
around it. Neither ever blocks anything; only what the Loop's stop list names stops work
(``loop_stops``), and that is a wait on a Ticket.

The rights: anyone who may read the board lists a Loop's records (``cards:read``). Anyone with
``cards:write``, a key as much as a person, records one while the Loop takes writes (``409
loop_read_only`` once it is completed, cancelled or archived). Recording is never refused for a
Ticket's wait, state, blockers or completion, nor for the Loop's stage: it must always work while
the Loop is writable. A given Ticket must belong to the Loop (``409 loop_mismatch``). Each record
is numbered in its Loop and keyed ``<LoopKey>-POC-<nnn>``; recording the same open record again
(the same kind, title and choice) answers the first one with ``deduplicated: true``, because
agents retry. Answering is a signed-in person's act (``403 human_action_required`` for a key,
even one that may decide in the editor): ``ok`` turns an open record into ``ok``; ``feedback``
turns an open or OK one into ``feedback`` and creates a Ticket in the Loop's first column, through
``CardService``, in the same transaction, so a Loop that cannot take a new Ticket in its stage
refuses the answer with that Ticket's error and nothing is stored. A record answered with
feedback is ``409 poc_decision_answered``.

Every write adds an activity entry on the Loop. The rules (limits, order, due, counts, the
feedback Ticket's text) are pure, in ``poc_decision_rules``; this service reaches the board only
through the board unit of work, and the clock and the id source are arguments, so every rule runs
in a unit test on the fakes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, NotFound
from ..db.generated.board import CardsRow, LoopsRow, PocDecisionsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.poc_decisions import PocDecisionAnswer, PocDecisionMark
from ..schemas.cards import CardCreate
from ..schemas.poc_decisions import PocDecisionAnswerCreate, PocDecisionCreate
from .activity import activity_entry
from .cards import CardService
from .cards_writes import ticket_in_loop
from .lists import BoardChecks
from .loops_rules import ensure_writable, require_loop
from .plan_views import PlanViews, unplanned_tickets
from .poc_decision_rules import (
    POC_DECISION_ANSWERED,
    LoopProgress,
    PocCounts,
    check_record,
    duplicate_of,
    feedback_description,
    feedback_title,
    is_due,
    loop_progress,
    mark_of,
    next_sequence,
    poc_counts,
    poc_key,
    review_order,
)


class PocActor(TypedDict):
    name: str
    type: str


class PocTicketRef(TypedDict):
    id: str
    key: str | None


class PocDecisionEntry(TypedDict):
    """A record as the API answers it."""

    id: str
    key: str
    loop_id: str
    card_id: str | None
    ticket_key: str | None
    ticket_title: str | None
    phase_number: int | None
    phase_complete: bool | None
    kind: str
    title: str
    chosen: str
    reason: str
    alternative: str
    change_path: str
    missing: str
    builds_on: str
    built_on: bool
    details: str
    status: str
    feedback: str
    feedback_ticket: PocTicketRef | None
    due: bool
    created_at: str
    created_by: PocActor
    answered_at: str | None
    answered_by_name: str | None


class PocDecisionRecorded(PocDecisionEntry):
    """A record as ``record`` answers it: ``deduplicated`` when the same open one existed."""

    deduplicated: bool


class PocDecisionList(TypedDict):
    """A Loop's records in review order, and the counts over all of them."""

    items: list[PocDecisionEntry]
    counts: PocCounts


def decision_entry(
    row: PocDecisionsRow, cards: Mapping[str, CardsRow], progress: LoopProgress
) -> PocDecisionEntry:
    """The record with its Ticket (key, title, Phase) and its feedback Ticket as ``cards`` holds
    them, and whether it is due by ``progress``."""
    card = cards.get(row.card_id) if row.card_id is not None else None
    phase = progress.phases.get(row.card_id) if row.card_id is not None else None
    feedback = cards.get(row.feedback_card_id) if row.feedback_card_id is not None else None
    feedback_ticket: PocTicketRef | None = None
    if row.feedback_card_id is not None:
        key = feedback.ticket_key if feedback is not None else None
        feedback_ticket = {"id": row.feedback_card_id, "key": key}
    mark = mark_of(row)
    return {
        "id": row.id,
        "key": row.key,
        "loop_id": row.loop_id,
        "card_id": row.card_id,
        "ticket_key": card.ticket_key if card is not None else None,
        "ticket_title": card.title if card is not None else None,
        "phase_number": phase.number if phase is not None else None,
        "phase_complete": phase.complete if phase is not None else None,
        "kind": row.kind,
        "title": row.title,
        "chosen": row.chosen,
        "reason": row.reason,
        "alternative": row.alternative,
        "change_path": row.change_path,
        "missing": row.missing,
        "builds_on": row.builds_on,
        "built_on": mark.built_on,
        "details": row.details,
        "status": row.status,
        "feedback": row.feedback,
        "feedback_ticket": feedback_ticket,
        "due": is_due(mark, progress),
        "created_at": row.created_at,
        "created_by": {"name": row.created_by_name, "type": row.created_by_type},
        "answered_at": row.answered_at,
        "answered_by_name": row.answered_by_name,
    }


def _texts(payload: PocDecisionCreate) -> dict[str, str]:
    return {
        "title": payload.title,
        "chosen": payload.chosen,
        "reason": payload.reason,
        "alternative": payload.alternative,
        "change_path": payload.change_path,
        "missing": payload.missing,
        "builds_on": payload.builds_on,
        "details": payload.details,
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class PocDecisionService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        tickets: CardService,
        *,
        plans: PlanViews,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self.tickets = tickets
        self.plans = plans
        self._clock = clock
        self._new_id = new_id

    # --- reading -----------------------------------------------------------------------------

    def _context(
        self, repos: BoardRepositories, loop: LoopsRow
    ) -> tuple[dict[str, CardsRow], LoopProgress]:
        """The Loop's cards by id (archived ones included) and its progress, from its
        readiness."""
        progress = loop_progress(self.plans.readiness(repos, loop), unplanned_tickets(repos, loop))
        cards = {card.id: card for card in repos.archive.tickets(loop.id)}
        return cards, progress

    def list(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        *,
        card_id: str | None = None,
        status: str | None = None,
    ) -> PocDecisionList:
        """The Loop's records in review order, narrowed to a Ticket or a status; the counts are
        over every record of the Loop."""
        actor.require("cards:read")
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            loop = require_loop(repos, loop_id)
            rows = repos.poc_decisions.for_loop(loop_id)
            cards, progress = self._context(repos, loop)
        shown = [
            row
            for row in review_order(rows)
            if (card_id is None or row.card_id == card_id)
            and (status is None or row.status == status)
        ]
        return {
            "items": [decision_entry(row, cards, progress) for row in shown],
            "counts": poc_counts((mark_of(row) for row in rows), progress),
        }

    def board_marks(self, actor: ActorContext, board_id: str) -> dict[str, list[PocDecisionMark]]:
        """Every record on the board by Loop id, in one read, for the Loop summaries."""
        actor.require("loops:read")
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            marks = repos.poc_decisions.marks()
        grouped: dict[str, list[PocDecisionMark]] = {}
        for mark in marks:
            grouped.setdefault(mark.loop_id, []).append(mark)
        return grouped

    # --- writing -----------------------------------------------------------------------------

    def record(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: PocDecisionCreate
    ) -> PocDecisionRecorded:
        """Record a POC decision or something missing, and go on."""
        actor.require("cards:write")
        check_record(payload.kind, _texts(payload))
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            if payload.card_id is not None:
                ticket_in_loop(repos, loop_id, payload.card_id)
            rows = repos.poc_decisions.for_loop(loop_id)
            same = duplicate_of(
                rows, kind=payload.kind, title=payload.title, chosen=payload.chosen
            )
            if same is not None:
                cards, progress = self._context(repos, loop)
                return {**decision_entry(same, cards, progress), "deduplicated": True}
            now = iso_utc(self._clock())
            sequence = next_sequence(rows)
            row = PocDecisionsRow(
                id=self._new_id(),
                loop_id=loop_id,
                card_id=payload.card_id,
                sequence=sequence,
                key=poc_key(loop.key, sequence),
                kind=payload.kind,
                title=payload.title,
                chosen=payload.chosen,
                reason=payload.reason,
                alternative=payload.alternative,
                change_path=payload.change_path,
                missing=payload.missing,
                builds_on=payload.builds_on,
                details=payload.details,
                status="open",
                feedback="",
                feedback_card_id=None,
                created_by_actor_id=actor.actor_id,
                created_by_type=actor.actor_type,
                created_by_name=actor.actor_name or actor.actor_id,
                created_at=now,
                answered_by_actor_id=None,
                answered_by_name=None,
                answered_at=None,
            )
            repos.poc_decisions.add(row)
            self._log(
                repos,
                actor,
                "loop.poc_decision_recorded",
                row,
                {"kind": row.kind, "card_id": row.card_id, "built_on": row.builds_on != ""},
                now,
            )
            cards, progress = self._context(repos, loop)
            return {**decision_entry(row, cards, progress), "deduplicated": False}

    def answer(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        decision_id: str,
        payload: PocDecisionAnswerCreate,
    ) -> PocDecisionEntry:
        """A person's OK, or their feedback, which becomes a Ticket in the Loop's first
        column."""
        actor.require_human("Answering a POC decision")
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            row = repos.poc_decisions.get(decision_id)
            if row is None or row.loop_id != loop_id:
                raise NotFound("POC decision not found", code="poc_decision_not_found")
            if row.status == "feedback":
                raise Conflict(
                    "This POC decision was answered with feedback",
                    code=POC_DECISION_ANSWERED,
                    details={"decision_id": row.id, "key": row.key},
                )
            if payload.answer == "ok" and row.status == "ok":
                cards, progress = self._context(repos, loop)
                return decision_entry(row, cards, progress)
            now = iso_utc(self._clock())
            feedback_card_id = None
            if payload.answer == "feedback":
                feedback_card_id = self._feedback_ticket(repos, actor, row, payload.feedback).id
            answer = PocDecisionAnswer(
                status=payload.answer,
                feedback=payload.feedback,
                feedback_card_id=feedback_card_id,
                answered_by_actor_id=actor.actor_id,
                answered_by_name=actor.actor_name or actor.actor_id,
                answered_at=now,
            )
            repos.poc_decisions.answer(row.id, answer)
            changes: dict[str, object] = {"answer": payload.answer, "before": row.status}
            if feedback_card_id is not None:
                changes["feedback_card_id"] = feedback_card_id
            self._log(repos, actor, "loop.poc_decision_answered", row, changes, now)
            answered = repos.poc_decisions.get(row.id) or row
            cards, progress = self._context(repos, loop)
            return decision_entry(answered, cards, progress)

    def _feedback_ticket(
        self, repos: BoardRepositories, actor: ActorContext, row: PocDecisionsRow, feedback: str
    ) -> CardsRow:
        """The Ticket the feedback becomes, in the Loop's first column, created as any new
        Ticket is (``CardService.add_in_writer``): a stage that takes no new Ticket refuses it."""
        columns = repos.lists.for_loop(row.loop_id, include_archived=False)
        if not columns:
            raise Conflict(
                "The Loop has no column to put the feedback Ticket in",
                code="loop_has_no_column",
                details={"loop_id": row.loop_id},
            )
        taken_on = repos.cards.get(row.card_id) if row.card_id is not None else None
        ticket = (taken_on.ticket_key, taken_on.title) if taken_on is not None else None
        payload = CardCreate(
            list_id=columns[0].id,
            title=feedback_title(row),
            description=feedback_description(row, feedback, ticket),
        )
        return self.tickets.add_in_writer(repos, actor, row.loop_id, payload)

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        row: PocDecisionsRow,
        changes: Mapping[str, object],
        now: str,
    ) -> None:
        """The activity entry on the Loop: the record's id and key and what changed, in the
        write's transaction."""
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="loop",
                entity_id=row.loop_id,
                changes={"decision_id": row.id, "key": row.key, **changes},
                entry_id=self._new_id(),
                timestamp=now,
            )
        )


__all__ = [
    "PocActor",
    "PocDecisionEntry",
    "PocDecisionList",
    "PocDecisionRecorded",
    "PocDecisionService",
    "PocTicketRef",
    "decision_entry",
]
