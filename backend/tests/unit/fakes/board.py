"""One board database in memory: the board repositories and their unit of work."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.core.errors import BoardUnreadable, Conflict, NotFound, ServiceUnavailable
from app.db.generated.board import (
    ActivityLogRow,
    BoardLoopDefaultsRow,
    BoardMetadataRow,
    CardLabelsRow,
    CardsRow,
    ChecklistItemsRow,
    ChecklistsRow,
    CommentsRow,
    IdempotencyRecordsRow,
    LabelsRow,
    ListsRow,
    LoopApprovalsRow,
    LoopDocumentsRow,
    LoopPhasesRow,
    LoopPlanItemsRow,
    LoopPlansRow,
    LoopQaCyclesRow,
    LoopsRow,
)
from app.repositories.activity import ActivityQuery, ActivityRepository
from app.repositories.board import BoardUnitOfWork
from app.repositories.board_metadata import BoardMetadataRepository, LoopDefaultsRepository
from app.repositories.cards import (
    BoardTicket,
    CardChanges,
    CardCounts,
    CardQuery,
    CardRepository,
    CardSort,
    TicketProgress,
)
from app.repositories.counters import BoardCounts, CounterRepository
from app.repositories.idempotency import BoardIdempotencyRepository
from app.repositories.labels import LabelRepository
from app.repositories.lists import ListRepository
from app.repositories.loop_documents import LoopApprovalRepository, LoopDocumentRepository
from app.repositories.loop_plans import LoopPlanRepository, PlanTotals
from app.repositories.loop_qa import LoopQaRepository
from app.repositories.loops import LoopChanges, LoopRepository
from tests.unit.fakes.registry import ConstraintError, like

BOARD_ID = "0b6f3c1e-7a52-4d8e-9c41-2f5a6b7c8d9e"
CREATED = "2026-11-01T09:00:00Z"


@dataclass(slots=True)
class BoardState:
    """The rows of one board database, as a test sets them up and the services change them."""

    lists: dict[str, ListsRow] = field(default_factory=dict[str, ListsRow])
    loops: dict[str, LoopsRow] = field(default_factory=dict[str, LoopsRow])
    cards: dict[str, CardsRow] = field(default_factory=dict[str, CardsRow])
    activity: list[ActivityLogRow] = field(default_factory=list[ActivityLogRow])
    labels: dict[str, LabelsRow] = field(default_factory=dict[str, LabelsRow])
    metadata: BoardMetadataRow | None = None
    loop_defaults: BoardLoopDefaultsRow | None = None
    # Lists keep insertion order, which is SQLite's rowid order.
    documents: list[LoopDocumentsRow] = field(default_factory=list[LoopDocumentsRow])
    approvals: list[LoopApprovalsRow] = field(default_factory=list[LoopApprovalsRow])
    plans: dict[str, LoopPlansRow] = field(default_factory=dict[str, LoopPlansRow])
    phases: dict[str, LoopPhasesRow] = field(default_factory=dict[str, LoopPhasesRow])
    plan_items: dict[str, LoopPlanItemsRow] = field(default_factory=dict[str, LoopPlanItemsRow])
    qa_cycles: dict[str, LoopQaCyclesRow] = field(default_factory=dict[str, LoopQaCyclesRow])
    card_labels: list[CardLabelsRow] = field(default_factory=list[CardLabelsRow])
    checklists: dict[str, ChecklistsRow] = field(default_factory=dict[str, ChecklistsRow])
    checklist_items: dict[str, ChecklistItemsRow] = field(
        default_factory=dict[str, ChecklistItemsRow]
    )
    comments: dict[str, CommentsRow] = field(default_factory=dict[str, CommentsRow])
    idempotency: dict[tuple[str, str], IdempotencyRecordsRow] = field(
        default_factory=dict[tuple[str, str], IdempotencyRecordsRow]
    )

    def snapshot(self) -> BoardState:
        return BoardState(
            lists=dict(self.lists),
            loops=dict(self.loops),
            cards=dict(self.cards),
            activity=list(self.activity),
            labels=dict(self.labels),
            metadata=self.metadata,
            loop_defaults=self.loop_defaults,
            documents=list(self.documents),
            approvals=list(self.approvals),
            plans=dict(self.plans),
            phases=dict(self.phases),
            plan_items=dict(self.plan_items),
            qa_cycles=dict(self.qa_cycles),
            card_labels=list(self.card_labels),
            checklists=dict(self.checklists),
            checklist_items=dict(self.checklist_items),
            comments=dict(self.comments),
            idempotency=dict(self.idempotency),
        )

    def restore(self, snapshot: BoardState) -> None:
        self.lists = snapshot.lists
        self.loops = snapshot.loops
        self.cards = snapshot.cards
        self.activity = snapshot.activity
        self.labels = snapshot.labels
        self.metadata = snapshot.metadata
        self.loop_defaults = snapshot.loop_defaults
        self.documents = snapshot.documents
        self.approvals = snapshot.approvals
        self.plans = snapshot.plans
        self.phases = snapshot.phases
        self.plan_items = snapshot.plan_items
        self.qa_cycles = snapshot.qa_cycles
        self.card_labels = snapshot.card_labels
        self.checklists = snapshot.checklists
        self.checklist_items = snapshot.checklist_items
        self.comments = snapshot.comments
        self.idempotency = snapshot.idempotency


# --- rows for a test to start from ---------------------------------------------------------------


def loop_row(
    loop_id: str,
    *,
    stage: str = "implementation",
    completed_at: str | None = None,
    archived_at: str | None = None,
    cancelled_at: str | None = None,
) -> LoopsRow:
    return LoopsRow(
        id=loop_id,
        name=f"Loop {loop_id}",
        goal="",
        sequence=1,
        key_prefix="L",
        key="L-1",
        stage=stage,
        version=1,
        current_plan_id=None,
        analysis_approval_id=None,
        roadmap_approval_id=None,
        implementation_approval_id=None,
        qa_approval_id=None,
        active_qa_cycle_id=None,
        history_id=None,
        created_by_actor_id="actor-0",
        created_by_actor_type="user",
        created_by_name="Grace",
        created_at=CREATED,
        updated_at=CREATED,
        archived_at=archived_at,
        cancelled_at=cancelled_at,
        completed_at=completed_at,
    )


def list_row(
    list_id: str, loop_id: str, position: int, *, name: str = "", archived_at: str | None = None
) -> ListsRow:
    return ListsRow(
        id=list_id,
        name=name or f"List {list_id}",
        position=position,
        created_at=CREATED,
        updated_at=CREATED,
        archived_at=archived_at,
        loop_id=loop_id,
    )


def card_row(
    card_id: str,
    list_id: str,
    loop_id: str,
    *,
    archived_at: str | None = None,
    plan_item_id: str | None = None,
) -> CardsRow:
    return CardsRow(
        id=card_id,
        list_id=list_id,
        title=f"Card {card_id}",
        description="",
        position=1024,
        priority="medium",
        due_at=None,
        completed_at=None,
        created_at=CREATED,
        updated_at=CREATED,
        archived_at=archived_at,
        version=1,
        assignee_actor_id=None,
        assignee_type=None,
        assignee_name=None,
        assigned_at=None,
        assigned_by_actor_id=None,
        loop_id=loop_id,
        phase_id=None,
        plan_item_id=plan_item_id,
        ticket_key=None,
        kind="task",
        required_actor="any",
        execution_mode="manual",
        human_action_reason="",
        human_instructions="",
        human_confirmed_at=None,
        human_confirmed_by_actor_id=None,
        plan_revision_id=None,
    )


def document_row(
    document_id: str,
    loop_id: str,
    kind: str,
    *,
    revision: int = 1,
    current: bool = True,
    approved: bool = False,
    status: str = "draft",
    content: str = "text",
    info: str | None = None,
    analysis_ai: str | None = None,
    analysis: str | None = None,
    roadmap_ai: str | None = None,
) -> LoopDocumentsRow:
    """A document revision; ``info`` and the like name the revisions it was written from."""
    return LoopDocumentsRow(
        id=document_id,
        loop_id=loop_id,
        kind=kind,
        revision_number=revision,
        content=content,
        payload_json=None,
        content_hash="hash",
        status=status,
        source_info_revision_id=info,
        source_analysis_ai_revision_id=analysis_ai,
        source_analysis_revision_id=analysis,
        source_roadmap_ai_revision_id=roadmap_ai,
        generation_run_id=None,
        author_actor_id="actor-0",
        author_actor_type="user",
        author_name="Grace",
        provenance_json="{}",
        is_current=int(current),
        is_approved=int(approved),
        created_at=CREATED,
    )


def approval_row(
    approval_id: str,
    loop_id: str,
    scope: str,
    *,
    decision: str = "approved",
    revisions_json: str = "{}",
    superseded_at: str | None = None,
    created_at: str = CREATED,
) -> LoopApprovalsRow:
    return LoopApprovalsRow(
        id=approval_id,
        loop_id=loop_id,
        scope=scope,
        decision=decision,
        reviewer_actor_id="actor-0",
        reviewer_name="Grace",
        feedback="",
        revisions_json=revisions_json,
        source_hashes_json="{}",
        loop_version=1,
        superseded_at=superseded_at,
        created_at=created_at,
    )


def plan_row(
    plan_id: str, loop_id: str, *, status: str = "active", revision: int = 1
) -> LoopPlansRow:
    return LoopPlansRow(
        id=plan_id,
        loop_id=loop_id,
        revision_number=revision,
        roadmap_ai_revision_id="roadmap-ai",
        roadmap_revision_id="roadmap",
        approval_id=None,
        payload_json="{}",
        content_hash="hash",
        status=status,
        created_at=CREATED,
        activated_at=CREATED if status == "active" else None,
        superseded_at=None,
    )


def phase_row(phase_id: str, loop_id: str, plan_id: str, number: int) -> LoopPhasesRow:
    return LoopPhasesRow(
        id=phase_id,
        loop_id=loop_id,
        plan_id=plan_id,
        number=number,
        name=f"Phase {number}",
        objective="",
        entry_conditions_json="[]",
        exit_conditions_json="[]",
        is_qa_phase=0,
        created_at=CREATED,
    )


def plan_item_row(item_id: str, loop_id: str, plan_id: str, phase_id: str) -> LoopPlanItemsRow:
    return LoopPlanItemsRow(
        id=item_id,
        loop_id=loop_id,
        plan_id=plan_id,
        phase_id=phase_id,
        phase_number=1,
        key=f"K-{item_id}",
        ticket_sequence=1,
        title=f"Item {item_id}",
        objective="",
        instructions="",
        required_actor="any",
        execution_mode="normal",
        priority="none",
        acceptance_criteria_json="[]",
        expected_evidence_json="[]",
        human_action_reason="",
        human_instructions="",
        created_at=CREATED,
    )


def qa_cycle_row(
    cycle_id: str, loop_id: str, number: int, *, status: str = "pending", card_id: str | None = None
) -> LoopQaCyclesRow:
    return LoopQaCyclesRow(
        id=cycle_id,
        loop_id=loop_id,
        cycle_number=number,
        status=status,
        card_id=card_id,
        ai_instructions_json="{}",
        human_instructions_json="{}",
        instruction_revision=0,
        delivery_baseline="",
        generation_run_id=None,
        attestation_json="{}",
        created_at=CREATED,
        updated_at=CREATED,
        decided_at=None,
        decided_by_actor_id=None,
        decision_note="",
    )


# --- repositories --------------------------------------------------------------------------------


def _display_order(row: ListsRow) -> tuple[int, str]:
    return row.position, row.id


class FakeListRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, list_id: str) -> ListsRow | None:
        return self._state.lists.get(list_id)

    def for_loop(self, loop_id: str, *, include_archived: bool) -> list[ListsRow]:
        rows = [
            row
            for row in self._state.lists.values()
            if row.loop_id == loop_id and (include_archived or row.archived_at is None)
        ]
        return sorted(rows, key=_display_order)

    def active_names(self, loop_id: str) -> list[str]:
        rows = [
            row
            for row in self._state.lists.values()
            if row.loop_id == loop_id and row.archived_at is None
        ]
        return [row.name for row in sorted(rows, key=lambda row: (row.position, row.created_at))]

    def positions(self, loop_id: str, *, exclude: str | None = None) -> list[tuple[str, int]]:
        return [
            (row.id, row.position)
            for row in self.for_loop(loop_id, include_archived=False)
            if row.id != exclude
        ]

    def add(self, row: ListsRow) -> None:
        if row.id in self._state.lists:
            raise Conflict(f"lists.id {row.id} exists")  # the primary key
        self._state.lists[row.id] = row

    def _change(self, row: ListsRow) -> None:
        self._state.lists[row.id] = row

    def rename(self, list_id: str, name: str, *, now: str) -> None:
        self._change(self._state.lists[list_id].__replace__(name=name, updated_at=now))

    def move(self, list_id: str, position: int, *, now: str) -> None:
        self._change(self._state.lists[list_id].__replace__(position=position, updated_at=now))

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for list_id, position in positions:
            self._change(self._state.lists[list_id].__replace__(position=position))

    def archive(self, list_id: str, *, now: str) -> None:
        self._change(self._state.lists[list_id].__replace__(archived_at=now, updated_at=now))

    def restore(self, list_id: str, position: int, *, now: str) -> None:
        row = self._state.lists[list_id]
        self._change(row.__replace__(archived_at=None, position=position, updated_at=now))

    def delete(self, list_id: str) -> None:
        del self._state.lists[list_id]

    def active_card_counts(self, loop_id: str) -> dict[str, int]:
        return dict(
            Counter(
                card.list_id
                for card in self._state.cards.values()
                if card.loop_id == loop_id and card.archived_at is None
            )
        )

    def active_card_count(self, list_id: str) -> int:
        return sum(
            1
            for card in self._state.cards.values()
            if card.list_id == list_id and card.archived_at is None
        )

    def planned_card_count(self, list_id: str) -> int:
        return sum(
            1
            for card in self._state.cards.values()
            if card.list_id == list_id and card.plan_item_id is not None
        )


class FakeLoopRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, loop_id: str) -> LoopsRow | None:
        return self._state.loops.get(loop_id)

    def listing(
        self, *, include_archived: bool, include_completed: bool, stage: str | None
    ) -> list[LoopsRow]:
        found = [
            loop
            for loop in self._state.loops.values()
            if (include_archived or loop.archived_at is None)
            and (include_completed or loop.completed_at is None)
            and (not stage or loop.stage == stage)
        ]
        return sorted(
            found, key=lambda loop: (loop.completed_at is not None, loop.sequence, loop.id)
        )

    def next_sequence(self) -> int:
        return max((loop.sequence for loop in self._state.loops.values()), default=0) + 1

    def add(self, row: LoopsRow) -> None:
        for loop in self._state.loops.values():
            if row.id == loop.id or row.sequence == loop.sequence or row.key == loop.key:
                raise ConstraintError(f"loops {row.id} breaks the primary or a unique key")
        self._state.loops[row.id] = row

    def _change(self, loop_id: str, change: Callable[[LoopsRow], LoopsRow]) -> None:
        loop = self._state.loops.get(loop_id)
        if loop is not None:
            self._state.loops[loop_id] = change(loop)

    def update(self, loop_id: str, changes: LoopChanges) -> None:
        if not changes:
            raise ConstraintError("an update without a column is not SQL")
        self._change(loop_id, lambda loop: loop.__replace__(**changes))

    def cancel(self, loop_id: str, *, now: str) -> None:
        self._change(
            loop_id,
            lambda loop: loop.__replace__(
                stage="cancelled", cancelled_at=now, version=loop.version + 1, updated_at=now
            ),
        )

    def archive(self, loop_id: str, *, now: str) -> None:
        self._change(
            loop_id,
            lambda loop: loop.__replace__(
                archived_at=now, version=loop.version + 1, updated_at=now
            ),
        )

    def set_stage(self, loop_id: str, stage: str, *, now: str) -> None:
        self._change(loop_id, lambda loop: loop.__replace__(stage=stage, updated_at=now))

    def clear_delivery_approvals(self, loop_id: str, *, now: str) -> None:
        self._change(
            loop_id,
            lambda loop: loop.__replace__(
                implementation_approval_id=None, qa_approval_id=None, updated_at=now
            ),
        )


def _loops_of(state: BoardState, loop_id: str | None) -> set[str]:
    """The Loops a query covers: one, or every Loop of the board (``IN (SELECT id FROM loops)``)."""
    return set(state.loops) if loop_id is None else {loop_id}


class FakeLoopDocumentRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def current_or_approved(self, loop_id: str | None) -> list[LoopDocumentsRow]:
        loops = _loops_of(self._state, loop_id)
        found = [
            row
            for row in self._state.documents
            if row.loop_id in loops and (row.is_current == 1 or row.is_approved == 1)
        ]
        return sorted(found, key=lambda row: (row.kind, row.revision_number))


class FakeLoopApprovalRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def newest_first(self, loop_id: str | None) -> list[LoopApprovalsRow]:
        loops = _loops_of(self._state, loop_id)
        # ORDER BY created_at DESC, rowid DESC: newest insertion first, then a stable sort.
        found = [row for row in reversed(self._state.approvals) if row.loop_id in loops]
        return sorted(found, key=lambda row: row.created_at, reverse=True)


class FakeLoopPlanRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def active(self, loop_id: str) -> LoopPlansRow | None:
        return next(
            (
                plan
                for plan in self._state.plans.values()
                if plan.loop_id == loop_id and plan.status == "active"
            ),
            None,
        )

    def active_by_loop(self) -> dict[str, LoopPlansRow]:
        return {
            plan.loop_id: plan
            for plan in self._state.plans.values()
            if plan.status == "active" and plan.loop_id in self._state.loops
        }

    def phase_counts(self, loop_id: str | None) -> dict[str, int]:
        loops = _loops_of(self._state, loop_id)
        phases = self._state.phases.values()
        return dict(Counter(phase.loop_id for phase in phases if phase.loop_id in loops))

    def ticket_totals(self, loop_id: str | None) -> dict[str, PlanTotals]:
        loops = _loops_of(self._state, loop_id)
        totals: dict[str, PlanTotals] = {}
        for item in self._state.plan_items.values():
            if item.loop_id not in loops:
                continue
            # LEFT JOIN cards: one row per card behind the item, or one row without a card.
            cards = [card for card in self._state.cards.values() if card.plan_item_id == item.id]
            done = sum(1 for card in cards if card.completed_at is not None)
            before = totals.get(item.loop_id, PlanTotals(total=0, completed=0))
            totals[item.loop_id] = PlanTotals(
                total=before.total + max(len(cards), 1), completed=before.completed + done
            )
        return totals


QA_OPEN = ("pending", "instructions_ready", "in_progress")


class FakeLoopQaRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def cycles(self, loop_id: str | None) -> list[LoopQaCyclesRow]:
        loops = _loops_of(self._state, loop_id)
        found = [cycle for cycle in self._state.qa_cycles.values() if cycle.loop_id in loops]
        return sorted(found, key=lambda cycle: cycle.cycle_number)

    def supersede_open(self, loop_id: str, *, now: str) -> None:
        for cycle in list(self._state.qa_cycles.values()):
            if cycle.loop_id == loop_id and cycle.status in QA_OPEN:
                self._state.qa_cycles[cycle.id] = cycle.__replace__(
                    status="superseded", updated_at=now
                )


def _sort_value(card: CardsRow, sort: CardSort) -> tuple[int, int | str]:
    """SQLite's order of a column: NULL first, then numbers or text (BINARY, code point order)."""
    match sort:
        case "position":
            return 1, card.position
        case "created_at":
            return 1, card.created_at
        case "updated_at":
            return 1, card.updated_at
        case "title":
            return 1, card.title
        case "due_at":
            return (0, "") if card.due_at is None else (1, card.due_at)


class FakeCardRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, card_id: str) -> CardsRow | None:
        return self._state.cards.get(card_id)

    def _label_matches(self, card_id: str, label: str) -> bool:
        for link in self._state.card_labels:
            row = self._state.labels.get(link.label_id)
            if link.card_id == card_id and row is not None and label in {row.id, row.name}:
                return True
        return False

    def _matches(self, card: CardsRow, query: CardQuery) -> bool:
        pattern = f"%{query.contains}%"
        checks = (
            card.loop_id == query.loop_id,
            query.include_archived or card.archived_at is None,
            not query.list_id or card.list_id == query.list_id,
            not query.contains
            or like(card.title, pattern)
            or like(card.description, pattern),
            not query.label or self._label_matches(card.id, query.label),
            not query.priority or card.priority == query.priority,
            not query.due_before
            or (card.due_at is not None and card.due_at <= query.due_before),
            not query.overdue_at
            or (
                card.due_at is not None
                and card.due_at < query.overdue_at
                and card.completed_at is None
            ),
            query.completed is None or (card.completed_at is not None) == query.completed,
            not query.unassigned or card.assignee_actor_id is None,
            query.unassigned
            or not query.assignee
            or card.assignee_actor_id == query.assignee,
        )
        return all(checks)

    def count(self, query: CardQuery) -> int:
        return sum(1 for card in self._state.cards.values() if self._matches(card, query))

    def page(
        self, query: CardQuery, *, sort: CardSort, descending: bool, limit: int, offset: int
    ) -> list[CardsRow]:
        found = sorted(
            (card for card in self._state.cards.values() if self._matches(card, query)),
            key=lambda card: card.id,
        )
        found.sort(key=lambda card: _sort_value(card, sort), reverse=descending)
        return found[offset : offset + limit]

    def board_tickets(self, *, contains: str | None, limit: int) -> list[BoardTicket]:
        pattern = f"%{contains}%"
        found: list[BoardTicket] = []
        for card in self._state.cards.values():
            loop = self._state.loops.get(card.loop_id)
            if loop is None or card.archived_at is not None:
                continue
            if loop.completed_at is not None or loop.archived_at is not None:
                continue
            if contains and not (
                like(card.title, pattern)
                or (card.ticket_key is not None and like(card.ticket_key, pattern))
            ):
                continue
            found.append(
                BoardTicket(
                    card=card, loop_key=loop.key, loop_name=loop.name, loop_stage=loop.stage
                )
            )
        found.sort(
            key=lambda ticket: (
                self._state.loops[ticket.card.loop_id].sequence,
                ticket.card.position,
                ticket.card.id,
            )
        )
        return found[:limit]

    def positions(self, list_id: str, *, exclude: str | None = None) -> list[tuple[str, int]]:
        found = [
            card
            for card in self._state.cards.values()
            if card.list_id == list_id and card.archived_at is None and card.id != exclude
        ]
        found.sort(key=lambda card: (card.position, card.id))
        return [(card.id, card.position) for card in found]

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for card_id, position in positions:
            self._state.cards[card_id] = self._state.cards[card_id].__replace__(position=position)

    def add(self, row: CardsRow) -> None:
        if row.id in self._state.cards:
            raise ConstraintError(f"cards.id {row.id} exists")
        if row.list_id not in self._state.lists or row.loop_id not in self._state.loops:
            raise ConstraintError(f"cards {row.id} names a list or Loop that does not exist")
        self._state.cards[row.id] = row

    def _change(self, card_id: str, change: Callable[[CardsRow], CardsRow]) -> None:
        card = self._state.cards.get(card_id)
        if card is not None:
            self._state.cards[card_id] = change(card)

    def update(self, card_id: str, changes: CardChanges) -> None:
        if not changes:
            raise ConstraintError("an update without a column is not SQL")
        self._change(card_id, lambda card: card.__replace__(**changes))

    def move(self, card_id: str, list_id: str, position: int, *, now: str) -> None:
        self._change(
            card_id,
            lambda card: card.__replace__(
                list_id=list_id, position=position, version=card.version + 1, updated_at=now
            ),
        )

    def archive(self, card_id: str, *, now: str) -> None:
        self._change(
            card_id,
            lambda card: card.__replace__(
                archived_at=now, updated_at=now, version=card.version + 1
            ),
        )

    def restore(self, card_id: str, position: int, *, now: str) -> None:
        self._change(
            card_id,
            lambda card: card.__replace__(
                archived_at=None, position=position, updated_at=now, version=card.version + 1
            ),
        )

    def confirm_human(self, card_id: str, actor_id: str, *, now: str) -> None:
        self._change(
            card_id,
            lambda card: card.__replace__(
                completed_at=now,
                human_confirmed_at=now,
                human_confirmed_by_actor_id=actor_id,
                updated_at=now,
                version=card.version + 1,
            ),
        )

    def completed_tickets(self, loop_id: str) -> int:
        return sum(
            1
            for card in self._state.cards.values()
            if card.loop_id == loop_id
            and card.kind in {"ticket", "qa"}
            and card.completed_at is not None
        )

    def progress(self, loop_id: str | None) -> dict[str, TicketProgress]:
        loops = _loops_of(self._state, loop_id)
        found: dict[str, TicketProgress] = {}
        for card in self._state.cards.values():
            if card.loop_id not in loops or card.kind not in {"ticket", "qa"}:
                continue
            before = found.get(
                card.loop_id, TicketProgress(total=0, completed=0, archived_incomplete=0)
            )
            found[card.loop_id] = TicketProgress(
                total=before.total + 1,
                completed=before.completed + (card.completed_at is not None),
                archived_incomplete=before.archived_incomplete
                + (card.archived_at is not None and card.completed_at is None),
            )
        return found

    def labels(self, card_ids: Sequence[str]) -> dict[str, list[LabelsRow]]:
        found: dict[str, list[LabelsRow]] = {card_id: [] for card_id in card_ids}
        for link in self._state.card_labels:
            label = self._state.labels.get(link.label_id)
            if link.card_id in found and label is not None:
                found[link.card_id].append(label)
        return {card_id: sorted(rows, key=lambda row: row.name) for card_id, rows in found.items()}

    def set_labels(self, card_id: str, label_ids: Sequence[str]) -> None:
        kept = [link for link in self._state.card_labels if link.card_id != card_id]
        for label_id in label_ids:
            if label_id not in self._state.labels:
                raise ConstraintError(f"card_labels.label_id {label_id} does not exist")
            link = CardLabelsRow(card_id=card_id, label_id=label_id)
            if link not in kept:  # INSERT OR IGNORE
                kept.append(link)
        self._state.card_labels = kept

    def counts(self, card_ids: Sequence[str]) -> dict[str, CardCounts]:
        found: dict[str, CardCounts] = {}
        for card_id in card_ids:
            checklists = {
                row.id for row in self._state.checklists.values() if row.card_id == card_id
            }
            items = [
                item
                for item in self._state.checklist_items.values()
                if item.checklist_id in checklists
            ]
            found[card_id] = CardCounts(
                checklist_total=len(items),
                checklist_completed=sum(item.completed for item in items),
                comment_count=sum(
                    1 for comment in self._state.comments.values() if comment.card_id == card_id
                ),
            )
        return found


class FakeBoardIdempotencyRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, actor_id: str, key: str) -> IdempotencyRecordsRow | None:
        return self._state.idempotency.get((actor_id, key))

    def delete(self, actor_id: str, key: str) -> None:
        self._state.idempotency.pop((actor_id, key), None)

    def put(self, row: IdempotencyRecordsRow) -> None:
        # INSERT OR REPLACE: the record held for the same actor and key is replaced.
        self._state.idempotency[(row.actor_id, row.idempotency_key)] = row


def _matches(entry: ActivityLogRow, query: ActivityQuery) -> bool:
    return (
        query.get("entity_type", entry.entity_type) == entry.entity_type
        and query.get("entity_id", entry.entity_id) == entry.entity_id
        and query.get("actor_type", entry.actor_type) == entry.actor_type
        and query.get("action", entry.action) == entry.action
    )


class FakeActivityRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def add(self, entry: ActivityLogRow) -> None:
        if any(row.id == entry.id for row in self._state.activity):
            raise ConstraintError(f"activity_log.id {entry.id} exists")
        self._state.activity.append(entry)

    def count(self, query: ActivityQuery) -> int:
        return sum(1 for entry in self._state.activity if _matches(entry, query))

    def page(self, query: ActivityQuery, *, limit: int, offset: int) -> list[ActivityLogRow]:
        found = [entry for entry in self._state.activity if _matches(entry, query)]
        # ORDER BY timestamp DESC, id: the tie-break first, then the stable descending sort.
        found.sort(key=lambda entry: entry.id)
        found.sort(key=lambda entry: entry.timestamp, reverse=True)
        return found[offset : offset + limit]


class FakeLabelRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def all(self) -> list[LabelsRow]:
        return sorted(self._state.labels.values(), key=lambda row: row.name)

    def find(self, reference: str) -> LabelsRow | None:
        return next(
            (row for row in self._state.labels.values() if reference in {row.id, row.name}), None
        )

    def add(self, row: LabelsRow) -> None:
        if row.id in self._state.labels:
            raise ConstraintError(f"labels.id {row.id} exists")
        if any(label.name == row.name for label in self._state.labels.values()):
            raise ConstraintError(f"labels.name {row.name} exists")
        self._state.labels[row.id] = row


class FakeBoardMetadataRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def claim(self, board_id: str, *, now: str) -> None:
        if self._state.metadata is not None:
            self._state.metadata = self._state.metadata.__replace__(id=board_id, updated_at=now)


class FakeLoopDefaultsRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self) -> BoardLoopDefaultsRow | None:
        return self._state.loop_defaults

    def add(self, row: BoardLoopDefaultsRow) -> None:
        if row.id != 1:
            raise ConstraintError("board_loop_defaults holds one row, id 1")
        if self._state.loop_defaults is not None:
            raise ConstraintError("board_loop_defaults.id 1 exists")
        self._state.loop_defaults = row


class FakeCounterRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def counts(self) -> BoardCounts:
        return BoardCounts(
            loops=sum(
                1
                for loop in self._state.loops.values()
                if loop.archived_at is None and loop.completed_at is None
            ),
            lists=sum(1 for row in self._state.lists.values() if row.archived_at is None),
            cards=sum(1 for card in self._state.cards.values() if card.archived_at is None),
        )


class FakeBoardRepositories:
    def __init__(self, state: BoardState) -> None:
        self._state = state
        # Typed as the Protocols: pyright proves each fake implements its repository here.
        self.lists: ListRepository = FakeListRepository(state)
        self.loops: LoopRepository = FakeLoopRepository(state)
        self.activity: ActivityRepository = FakeActivityRepository(state)
        self.labels: LabelRepository = FakeLabelRepository(state)
        self.counters: CounterRepository = FakeCounterRepository(state)
        self.metadata: BoardMetadataRepository = FakeBoardMetadataRepository(state)
        self.loop_defaults: LoopDefaultsRepository = FakeLoopDefaultsRepository(state)
        self.cards: CardRepository = FakeCardRepository(state)
        self.documents: LoopDocumentRepository = FakeLoopDocumentRepository(state)
        self.approvals: LoopApprovalRepository = FakeLoopApprovalRepository(state)
        self.plans: LoopPlanRepository = FakeLoopPlanRepository(state)
        self.qa: LoopQaRepository = FakeLoopQaRepository(state)
        self.idempotency: BoardIdempotencyRepository = FakeBoardIdempotencyRepository(state)
        self.savepoints = 0

    @contextmanager
    def savepoint(self) -> Generator[None]:
        """A savepoint keeps its writes when the block ends normally; when it raises, only its own
        writes are undone and the exception goes on."""
        snapshot = self._state.snapshot()
        self.savepoints += 1
        try:
            yield
        except BaseException:
            self._state.restore(snapshot)
            raise


class FakeBoardUnitOfWork:
    """Commits a writer that ends normally, rolls back one that raises; a reader never commits."""

    def __init__(
        self,
        state: BoardState,
        *,
        databases: Collection[str] = (BOARD_ID,),
        unavailable: Collection[str] = (),
        unreadable: Collection[str] = (),
    ) -> None:
        self.state = state
        self.databases = set(databases)
        # Boards whose schema is being repaired: opening one answers 503, as the manager does.
        self.unavailable = set(unavailable)
        # Boards whose file SQLite refuses (not a database, or damaged): 503, not retryable.
        self.unreadable = set(unreadable)
        self.commits = 0
        self.rollbacks = 0

    def exists(self, board_id: str) -> bool:
        return board_id in self.databases

    def _open(self, board_id: str) -> BoardState:
        if board_id not in self.databases:
            raise NotFound("Board database not found")
        if board_id in self.unavailable:
            raise ServiceUnavailable(
                "Board schema is not at the current revision", code="board_schema_outdated"
            )
        if board_id in self.unreadable:
            raise BoardUnreadable("Board database cannot be read")
        return self.state.snapshot()

    @contextmanager
    def reader(self, board_id: str) -> Generator[FakeBoardRepositories]:
        snapshot = self._open(board_id)
        try:
            yield FakeBoardRepositories(self.state)
        finally:
            self.state.restore(snapshot)

    @contextmanager
    def writer(self, board_id: str) -> Generator[FakeBoardRepositories]:
        snapshot = self._open(board_id)
        try:
            yield FakeBoardRepositories(self.state)
        except BaseException:
            self.state.restore(snapshot)
            self.rollbacks += 1
            raise
        self.commits += 1


def board_unit_of_work(state: BoardState) -> BoardUnitOfWork:
    """The fake as the Protocol a service takes; pyright proves the contract."""
    return FakeBoardUnitOfWork(state)


@dataclass(slots=True)
class FakeBoardChecks:
    """The registry side of a board as BoardService answers it: registered, and taking writes."""

    unregistered: frozenset[str] = frozenset()
    archived: frozenset[str] = frozenset()
    calls: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def require_row(self, board_id: str) -> object:
        self.calls.append(("require_row", board_id))
        if board_id in self.unregistered:
            raise NotFound("Board not found")
        return board_id

    def ensure_active(self, board_id: str) -> object:
        self.calls.append(("ensure_active", board_id))
        if board_id in self.unregistered:
            raise NotFound("Board not found")
        if board_id in self.archived:
            raise Conflict("Board is archived", code="board_archived")
        return board_id
