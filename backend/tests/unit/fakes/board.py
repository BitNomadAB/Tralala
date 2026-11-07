"""One board database in memory: the board repositories and their unit of work."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Collection, Generator, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.core.errors import BoardUnreadable, Conflict, NotFound, ServiceUnavailable
from app.db.generated.board import (
    ActivityLogRow,
    AttachmentsRow,
    BoardLoopDefaultsRow,
    BoardMetadataRow,
    CardEventsRow,
    CardLabelsRow,
    CardsRow,
    ChecklistItemsRow,
    ChecklistsRow,
    CommentMentionJobsRow,
    CommentsRow,
    DiscussionEventsRow,
    DiscussionMessagesRow,
    DiscussionOutcomesRow,
    DiscussionParticipantsRow,
    DiscussionRoundsRow,
    DiscussionRunsRow,
    DiscussionThreadsRow,
    DiscussionVotesRow,
    IdempotencyRecordsRow,
    LabelsRow,
    ListsRow,
    LoopAgentPreferencesRow,
    LoopApprovalsRow,
    LoopDependenciesRow,
    LoopDocumentsRow,
    LoopGenerationRunsRow,
    LoopHistoryArtifactsRow,
    LoopHistoryRow,
    LoopNotesRow,
    LoopPhasesRow,
    LoopPlanItemsRow,
    LoopPlansRow,
    LoopQaCyclesRow,
    LoopQaResultsRow,
    LoopsRow,
)
from app.repositories.activity import ActivityQuery, ActivityRepository
from app.repositories.attachments import AttachmentRepository
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
from app.repositories.checklists import (
    ChecklistItemChanges,
    ChecklistItemRepository,
    ChecklistRepository,
)
from app.repositories.comments import CommentRepository
from app.repositories.counters import BoardCounts, CounterRepository
from app.repositories.discussions import (
    DiscussionMessageRepository,
    DiscussionOutcomeRepository,
    DiscussionParticipantRepository,
    DiscussionRoundRepository,
    DiscussionRunRepository,
    DiscussionThreadRepository,
    DiscussionVoteRepository,
)
from app.repositories.events import EventRepository, NewEvent
from app.repositories.generation_runs import GenerationRunRepository
from app.repositories.idempotency import BoardIdempotencyRepository
from app.repositories.labels import LabelChanges, LabelRepository
from app.repositories.lists import ListRepository
from app.repositories.loop_agents import LoopAgentRepository
from app.repositories.loop_documents import LoopApprovalRepository, LoopDocumentRepository
from app.repositories.loop_history import LoopArchiveRepository, LoopHistoryRepository
from app.repositories.loop_notes import LoopNoteRepository
from app.repositories.loop_plans import (
    LoopDependencyRepository,
    LoopPhaseRepository,
    LoopPlanItemRepository,
    LoopPlanRepository,
    PlannedItem,
    PlanTotals,
)
from app.repositories.loop_qa import LoopQaRepository
from app.repositories.loops import ApprovalColumn, LoopChanges, LoopRepository
from app.repositories.mention_jobs import MentionJobRepository
from app.repositories.search import CardSearch, CardSearchRepository
from tests.unit.fakes.discussions import (
    FakeDiscussionMessageRepository,
    FakeDiscussionOutcomeRepository,
    FakeDiscussionParticipantRepository,
    FakeDiscussionRoundRepository,
    FakeDiscussionRunRepository,
    FakeDiscussionThreadRepository,
    FakeDiscussionVoteRepository,
    FakeMentionJobRepository,
)
from tests.unit.fakes.generation import FakeGenerationRunRepository
from tests.unit.fakes.history import FakeLoopArchiveRepository, FakeLoopHistoryRepository
from tests.unit.fakes.loop_notes import FakeLoopNoteRepository
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
    dependencies: list[LoopDependenciesRow] = field(default_factory=list[LoopDependenciesRow])
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
    attachments: dict[str, AttachmentsRow] = field(default_factory=dict[str, AttachmentsRow])
    loop_agents: dict[tuple[str, str], LoopAgentPreferencesRow] = field(
        default_factory=dict[tuple[str, str], LoopAgentPreferencesRow]
    )
    discussions: dict[str, DiscussionThreadsRow] = field(
        default_factory=dict[str, DiscussionThreadsRow]
    )
    discussion_events: list[DiscussionEventsRow] = field(default_factory=list[DiscussionEventsRow])
    card_events: list[CardEventsRow] = field(default_factory=list[CardEventsRow])
    participants: list[DiscussionParticipantsRow] = field(
        default_factory=list[DiscussionParticipantsRow]
    )
    discussion_messages: list[DiscussionMessagesRow] = field(
        default_factory=list[DiscussionMessagesRow]
    )
    votes: list[DiscussionVotesRow] = field(default_factory=list[DiscussionVotesRow])
    runs: dict[str, DiscussionRunsRow] = field(default_factory=dict[str, DiscussionRunsRow])
    rounds: list[DiscussionRoundsRow] = field(default_factory=list[DiscussionRoundsRow])
    outcomes: list[DiscussionOutcomesRow] = field(default_factory=list[DiscussionOutcomesRow])
    mention_jobs: dict[str, CommentMentionJobsRow] = field(
        default_factory=dict[str, CommentMentionJobsRow]
    )
    qa_results: list[LoopQaResultsRow] = field(default_factory=list[LoopQaResultsRow])
    generation_runs: dict[str, LoopGenerationRunsRow] = field(
        default_factory=dict[str, LoopGenerationRunsRow]
    )
    history: dict[str, LoopHistoryRow] = field(default_factory=dict[str, LoopHistoryRow])
    artifacts: list[LoopHistoryArtifactsRow] = field(
        default_factory=list[LoopHistoryArtifactsRow]
    )
    notes: list[LoopNotesRow] = field(default_factory=list[LoopNotesRow])

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
            dependencies=list(self.dependencies),
            qa_cycles=dict(self.qa_cycles),
            card_labels=list(self.card_labels),
            checklists=dict(self.checklists),
            checklist_items=dict(self.checklist_items),
            comments=dict(self.comments),
            idempotency=dict(self.idempotency),
            attachments=dict(self.attachments),
            loop_agents=dict(self.loop_agents),
            discussions=dict(self.discussions),
            discussion_events=list(self.discussion_events),
            card_events=list(self.card_events),
            participants=list(self.participants),
            discussion_messages=list(self.discussion_messages),
            votes=list(self.votes),
            runs=dict(self.runs),
            rounds=list(self.rounds),
            outcomes=list(self.outcomes),
            mention_jobs=dict(self.mention_jobs),
            qa_results=list(self.qa_results),
            generation_runs=dict(self.generation_runs),
            history=dict(self.history),
            artifacts=list(self.artifacts),
            notes=list(self.notes),
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
        self.dependencies = snapshot.dependencies
        self.qa_cycles = snapshot.qa_cycles
        self.card_labels = snapshot.card_labels
        self.checklists = snapshot.checklists
        self.checklist_items = snapshot.checklist_items
        self.comments = snapshot.comments
        self.idempotency = snapshot.idempotency
        self.attachments = snapshot.attachments
        self.loop_agents = snapshot.loop_agents
        self.discussions = snapshot.discussions
        self.discussion_events = snapshot.discussion_events
        self.card_events = snapshot.card_events
        self.participants = snapshot.participants
        self.discussion_messages = snapshot.discussion_messages
        self.votes = snapshot.votes
        self.runs = snapshot.runs
        self.rounds = snapshot.rounds
        self.outcomes = snapshot.outcomes
        self.mention_jobs = snapshot.mention_jobs
        self.qa_results = snapshot.qa_results
        self.generation_runs = snapshot.generation_runs
        self.history = snapshot.history
        self.artifacts = snapshot.artifacts
        self.notes = snapshot.notes


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
        summary="",
        summary_source="",
        summary_basis_sha256="",
        workplace="unknown",
        waiting_for="nothing",
        waiting_reason="",
        waiting_set_at=None,
        waiting_set_by=None,
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


def discussion_row(
    discussion_id: str,
    *,
    card_id: str | None = None,
    status: str = "open",
    run_state: str = "idle",
) -> DiscussionThreadsRow:
    return DiscussionThreadsRow(
        id=discussion_id,
        card_id=card_id,
        title=f"Discussion {discussion_id}",
        goal="",
        mode="discussion",
        status=status,
        created_by_actor_id="actor-1",
        created_by_type="user",
        created_by_name="Ada",
        max_rounds=3,
        origin_comment_id=None,
        escalation_depth=0,
        created_at=CREATED,
        updated_at=CREATED,
        last_activity_at=CREATED,
        round_count=0,
        run_state=run_state,
        tokens_used=0,
        elapsed_ms=0,
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
        summary="",
        workplace="unknown",
        waiting_for="nothing",
        waiting_reason="",
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

    def complete(self, loop_id: str, *, history_id: str, now: str) -> None:
        self._change(
            loop_id,
            lambda loop: loop.__replace__(
                stage="completed",
                completed_at=now,
                history_id=history_id,
                version=loop.version + 1,
                updated_at=now,
            ),
        )

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

    def set_current_plan(self, loop_id: str, plan_id: str, *, now: str) -> None:
        self._change(
            loop_id, lambda loop: loop.__replace__(current_plan_id=plan_id, updated_at=now)
        )

    def clear_delivery_approvals(self, loop_id: str, *, now: str) -> None:
        self._change(
            loop_id,
            lambda loop: loop.__replace__(
                implementation_approval_id=None, qa_approval_id=None, updated_at=now
            ),
        )

    @staticmethod
    def _with_approval(loop: LoopsRow, column: ApprovalColumn, value: str | None) -> LoopsRow:
        match column:
            case "analysis_approval_id":
                return loop.__replace__(analysis_approval_id=value)
            case "roadmap_approval_id":
                return loop.__replace__(roadmap_approval_id=value)
            case "implementation_approval_id":
                return loop.__replace__(implementation_approval_id=value)
            case "qa_approval_id":
                return loop.__replace__(qa_approval_id=value)

    def clear_approvals(
        self, loop_id: str, columns: Sequence[ApprovalColumn], *, now: str
    ) -> None:
        if not columns:
            raise ConstraintError("an update without a column is not SQL")
        loop = self._state.loops.get(loop_id)
        if loop is None:
            return
        for column in columns:
            loop = self._with_approval(loop, column, None)
        self._state.loops[loop_id] = loop.__replace__(updated_at=now)

    def set_approval(
        self, loop_id: str, column: ApprovalColumn, approval_id: str, *, now: str
    ) -> None:
        self._change(
            loop_id,
            lambda loop: self._with_approval(loop, column, approval_id).__replace__(
                version=loop.version + 1, updated_at=now
            ),
        )

    def accept_delivery(
        self, loop_id: str, *, implementation_approval_id: str, qa_approval_id: str, now: str
    ) -> None:
        self._change(
            loop_id,
            lambda loop: loop.__replace__(
                implementation_approval_id=implementation_approval_id,
                qa_approval_id=qa_approval_id,
                version=loop.version + 1,
                updated_at=now,
            ),
        )

    def start_qa(
        self, loop_id: str, *, implementation_approval_id: str, cycle_id: str, now: str
    ) -> None:
        self._change(
            loop_id,
            lambda loop: loop.__replace__(
                implementation_approval_id=implementation_approval_id,
                active_qa_cycle_id=cycle_id,
                version=loop.version + 1,
                updated_at=now,
            ),
        )

    def set_active_qa_cycle(self, loop_id: str, cycle_id: str, *, now: str) -> None:
        self._change(
            loop_id, lambda loop: loop.__replace__(active_qa_cycle_id=cycle_id, updated_at=now)
        )

    def bump_version(self, loop_id: str, *, now: str) -> None:
        self._change(
            loop_id, lambda loop: loop.__replace__(version=loop.version + 1, updated_at=now)
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

    def _of(self, loop_id: str, kind: str) -> list[LoopDocumentsRow]:
        return [row for row in self._state.documents if (row.loop_id, row.kind) == (loop_id, kind)]

    def current(self, loop_id: str, kind: str) -> LoopDocumentsRow | None:
        return next((row for row in self._of(loop_id, kind) if row.is_current == 1), None)

    def count(self, loop_id: str, kind: str) -> int:
        return len(self._of(loop_id, kind))

    def page(self, loop_id: str, kind: str, *, limit: int, offset: int) -> list[LoopDocumentsRow]:
        found = sorted(self._of(loop_id, kind), key=lambda row: row.revision_number, reverse=True)
        return found[offset : offset + limit]

    def next_revision(self, loop_id: str, kind: str) -> int:
        return max((row.revision_number for row in self._of(loop_id, kind)), default=0) + 1

    def _change(
        self,
        matches: Callable[[LoopDocumentsRow], bool],
        change: Callable[[LoopDocumentsRow], LoopDocumentsRow],
    ) -> None:
        self._state.documents = [
            change(row) if matches(row) else row for row in self._state.documents
        ]

    def clear_current(self, loop_id: str, kind: str) -> None:
        self._change(
            lambda row: (row.loop_id, row.kind) == (loop_id, kind),
            lambda row: row.__replace__(is_current=0),
        )

    def withdraw_approval(self, loop_id: str, kind: str) -> None:
        self._change(
            lambda row: (row.loop_id, row.kind) == (loop_id, kind),
            lambda row: row.__replace__(is_approved=0),
        )

    def add(self, row: LoopDocumentsRow) -> None:
        for known in self._state.documents:
            if known.id == row.id or (known.loop_id, known.kind, known.revision_number) == (
                row.loop_id,
                row.kind,
                row.revision_number,
            ):
                raise ConstraintError(f"loop_documents {row.id} breaks the primary or a unique key")
        if row.loop_id not in self._state.loops:
            raise ConstraintError(f"loop_documents {row.id} names a Loop that does not exist")
        same_kind = self._of(row.loop_id, row.kind)
        if (row.is_current and any(known.is_current for known in same_kind)) or (
            row.is_approved and any(known.is_approved for known in same_kind)
        ):
            raise ConstraintError(f"loop_documents {row.id} is a second current or approved one")
        self._state.documents.append(row)

    def approve(self, document_id: str) -> None:
        row = next((known for known in self._state.documents if known.id == document_id), None)
        if row is not None and any(
            known.is_approved and known.id != document_id
            for known in self._of(row.loop_id, row.kind)
        ):
            raise ConstraintError(f"loop_documents {document_id} would be a second approved one")
        self._change(
            lambda row: row.id == document_id,
            lambda row: row.__replace__(is_approved=1, status="approved"),
        )

    def request_changes(self, document_id: str) -> None:
        self._change(
            lambda row: row.id == document_id,
            lambda row: row.__replace__(is_approved=0, status="changes_requested"),
        )


class FakeLoopApprovalRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def newest_first(self, loop_id: str | None) -> list[LoopApprovalsRow]:
        loops = _loops_of(self._state, loop_id)
        # ORDER BY created_at DESC, rowid DESC: newest insertion first, then a stable sort.
        found = [row for row in reversed(self._state.approvals) if row.loop_id in loops]
        return sorted(found, key=lambda row: row.created_at, reverse=True)

    def get(self, approval_id: str) -> LoopApprovalsRow | None:
        return next((row for row in self._state.approvals if row.id == approval_id), None)

    def add(self, row: LoopApprovalsRow) -> None:
        if self.get(row.id) is not None:
            raise ConstraintError(f"loop_approvals.id {row.id} exists")
        if row.loop_id not in self._state.loops:
            raise ConstraintError(f"loop_approvals {row.id} names a Loop that does not exist")
        self._state.approvals.append(row)

    def supersede_others(self, loop_id: str, scope: str, *, keep: str, now: str) -> None:
        self._state.approvals = [
            row.__replace__(superseded_at=now)
            if row.loop_id == loop_id
            and row.scope == scope
            and row.id != keep
            and row.superseded_at is None
            else row
            for row in self._state.approvals
        ]

    def supersede(self, approval_id: str, *, now: str) -> None:
        self._state.approvals = [
            row.__replace__(superseded_at=now) if row.id == approval_id else row
            for row in self._state.approvals
        ]


class FakeLoopPlanRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, plan_id: str) -> LoopPlansRow | None:
        return self._state.plans.get(plan_id)

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

    def next_revision(self, loop_id: str) -> int:
        revisions = [
            plan.revision_number for plan in self._state.plans.values() if plan.loop_id == loop_id
        ]
        return max(revisions, default=0) + 1

    def add(self, row: LoopPlansRow) -> None:
        for plan in self._state.plans.values():
            if plan.id == row.id or (
                plan.loop_id == row.loop_id and plan.revision_number == row.revision_number
            ):
                raise ConstraintError(f"loop_plans {row.id} breaks the primary or a unique key")
        if row.loop_id not in self._state.loops:
            raise ConstraintError(f"loop_plans {row.id} names a Loop that does not exist")
        self._state.plans[row.id] = row

    def attach_revisions(
        self, plan_id: str, *, roadmap_ai_revision_id: str, roadmap_revision_id: str
    ) -> None:
        plan = self._state.plans.get(plan_id)
        if plan is not None:
            self._state.plans[plan_id] = plan.__replace__(
                roadmap_ai_revision_id=roadmap_ai_revision_id,
                roadmap_revision_id=roadmap_revision_id,
            )

    def activate(self, loop_id: str, plan_id: str, *, approval_id: str | None, now: str) -> None:
        for plan in list(self._state.plans.values()):
            if plan.loop_id == loop_id and plan.status == "active" and plan.id != plan_id:
                self._state.plans[plan.id] = plan.__replace__(
                    status="superseded", superseded_at=now
                )
        plan = self._state.plans.get(plan_id)
        if plan is None:
            return
        if plan.status != "active" and self.active(plan.loop_id) is not None:
            # ux_loop_plans_active: one active plan per Loop.
            raise ConstraintError(f"loop_plans {plan_id} would be a second active plan")
        self._state.plans[plan_id] = plan.__replace__(
            status="active",
            approval_id=approval_id,
            activated_at=plan.activated_at if plan.activated_at is not None else now,
        )


class FakeLoopPhaseRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, loop_id: str, phase_id: str) -> LoopPhasesRow | None:
        phase = self._state.phases.get(phase_id)
        return phase if phase is not None and phase.loop_id == loop_id else None

    def for_loop(self, loop_id: str) -> list[LoopPhasesRow]:
        # ORDER BY number over the (loop_id, number) index: ties keep insertion (rowid) order.
        found = [phase for phase in self._state.phases.values() if phase.loop_id == loop_id]
        return sorted(found, key=lambda phase: phase.number)

    def _check_number(self, row: LoopPhasesRow) -> None:
        for phase in self._state.phases.values():
            if phase.id != row.id and (phase.plan_id, phase.number) == (row.plan_id, row.number):
                raise ConstraintError(f"loop_phases {row.id} repeats a number of its plan")

    def add(self, row: LoopPhasesRow) -> None:
        if row.id in self._state.phases:
            raise ConstraintError(f"loop_phases.id {row.id} exists")
        if row.loop_id not in self._state.loops:
            raise ConstraintError(f"loop_phases {row.id} names a Loop that does not exist")
        self._check_number(row)
        self._state.phases[row.id] = row

    def update(self, row: LoopPhasesRow) -> None:
        phase = self._state.phases.get(row.id)
        if phase is None:
            return
        self._check_number(row)
        self._state.phases[row.id] = phase.__replace__(
            plan_id=row.plan_id,
            number=row.number,
            name=row.name,
            objective=row.objective,
            entry_conditions_json=row.entry_conditions_json,
            exit_conditions_json=row.exit_conditions_json,
        )


class FakeLoopPlanItemRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, loop_id: str, item_id: str) -> LoopPlanItemsRow | None:
        item = self._state.plan_items.get(item_id)
        return item if item is not None and item.loop_id == loop_id else None

    def next_sequence(self, loop_id: str, phase_number: int) -> int:
        sequences = [
            item.ticket_sequence
            for item in self._state.plan_items.values()
            if item.loop_id == loop_id and item.phase_number == phase_number
        ]
        return max(sequences, default=0) + 1

    def _check_unique(self, row: LoopPlanItemsRow) -> None:
        for item in self._state.plan_items.values():
            if item.id == row.id:
                continue
            if item.key == row.key or (item.phase_id, item.ticket_sequence) == (
                row.phase_id,
                row.ticket_sequence,
            ):
                raise ConstraintError(f"loop_plan_items {row.id} repeats a key or a sequence")

    def add(self, row: LoopPlanItemsRow) -> None:
        if row.id in self._state.plan_items:
            raise ConstraintError(f"loop_plan_items.id {row.id} exists")
        if row.loop_id not in self._state.loops:
            raise ConstraintError(f"loop_plan_items {row.id} names a Loop that does not exist")
        self._check_unique(row)
        self._state.plan_items[row.id] = row

    def update(self, row: LoopPlanItemsRow) -> None:
        item = self._state.plan_items.get(row.id)
        if item is None:
            return
        changed = item.__replace__(
            plan_id=row.plan_id,
            phase_id=row.phase_id,
            phase_number=row.phase_number,
            title=row.title,
            objective=row.objective,
            instructions=row.instructions,
            required_actor=row.required_actor,
            execution_mode=row.execution_mode,
            priority=row.priority,
            acceptance_criteria_json=row.acceptance_criteria_json,
            expected_evidence_json=row.expected_evidence_json,
            human_action_reason=row.human_action_reason,
            human_instructions=row.human_instructions,
        )
        self._check_unique(changed)
        self._state.plan_items[row.id] = changed

    def with_cards(self, loop_id: str) -> list[PlannedItem]:
        items = sorted(
            (item for item in self._state.plan_items.values() if item.loop_id == loop_id),
            key=lambda item: (item.phase_number, item.ticket_sequence, item.key),
        )
        found: list[PlannedItem] = []
        for item in items:
            # LEFT JOIN cards: one row per card published from the item, or one without a card.
            cards = [card for card in self._state.cards.values() if card.plan_item_id == item.id]
            found += [
                PlannedItem(
                    item=item,
                    card_id=card.id,
                    completed_at=card.completed_at,
                    waiting_for=card.waiting_for,
                    workplace=card.workplace,
                )
                for card in cards
            ] or [PlannedItem(item=item, card_id=None, completed_at=None)]
        return found


class FakeLoopDependencyRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def for_loop(self, loop_id: str) -> list[LoopDependenciesRow]:
        return [edge for edge in self._state.dependencies if edge.loop_id == loop_id]

    def clear(self, loop_id: str) -> None:
        self._state.dependencies = [
            edge for edge in self._state.dependencies if edge.loop_id != loop_id
        ]

    def add(self, row: LoopDependenciesRow) -> None:
        def edge(row: LoopDependenciesRow) -> tuple[str, str, str, str, str]:
            return row.plan_id, row.source_type, row.source_id, row.target_type, row.target_id

        # INSERT OR IGNORE: an edge the plan already has (or a repeated id) is not added again.
        for known in self._state.dependencies:
            if known.id == row.id or edge(known) == edge(row):
                return
        self._state.dependencies.append(row)


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

    def add(self, row: LoopQaCyclesRow) -> None:
        if row.id in self._state.qa_cycles:
            raise ConstraintError(f"loop_qa_cycles.id {row.id} exists")
        self._state.qa_cycles[row.id] = row

    def set_instructions(
        self,
        cycle_id: str,
        *,
        ai_json: str,
        human_json: str,
        revision: int,
        run_id: str,
        baseline: str,
        now: str,
    ) -> None:
        cycle = self._state.qa_cycles.get(cycle_id)
        if cycle is not None:
            self._state.qa_cycles[cycle_id] = cycle.__replace__(
                status="instructions_ready",
                ai_instructions_json=ai_json,
                human_instructions_json=human_json,
                instruction_revision=revision,
                generation_run_id=run_id,
                delivery_baseline=baseline,
                updated_at=now,
            )

    def mark_in_progress(self, cycle_id: str, *, now: str) -> None:
        cycle = self._state.qa_cycles.get(cycle_id)
        if cycle is not None:
            self._state.qa_cycles[cycle_id] = cycle.__replace__(
                status="in_progress", updated_at=now
            )

    def decide(self, cycle_id: str, *, status: str, actor_id: str, note: str, now: str) -> None:
        cycle = self._state.qa_cycles.get(cycle_id)
        if cycle is not None:
            self._state.qa_cycles[cycle_id] = cycle.__replace__(
                status=status,
                decided_at=now,
                decided_by_actor_id=actor_id,
                decision_note=note,
                updated_at=now,
            )

    def results(self, cycle_id: str) -> list[LoopQaResultsRow]:
        found = [row for row in self._state.qa_results if row.cycle_id == cycle_id]
        return sorted(found, key=lambda row: row.created_at)

    def add_result(self, row: LoopQaResultsRow) -> None:
        if row.cycle_id not in self._state.qa_cycles:
            raise ConstraintError("FOREIGN KEY constraint failed")
        self._state.qa_results.append(row)

    def approve_not_applicable(
        self, cycle_id: str, scenario_id: str, *, actor_id: str, note: str
    ) -> None:
        self._state.qa_results = [
            row.__replace__(disposition_approved_by_actor_id=actor_id, disposition_note=note)
            if row.cycle_id == cycle_id
            and row.scenario_id == scenario_id
            and row.status == "not_applicable"
            else row
            for row in self._state.qa_results
        ]


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

    def highest_position(self, list_id: str) -> int:
        cards = self._state.cards.values()
        return max((card.position for card in cards if card.list_id == list_id), default=0)

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

    def sync_plan_item(self, item: LoopPlanItemsRow, *, now: str, summary_basis: str) -> None:
        card = self._state.cards.get(item.id)
        if card is None or card.plan_item_id != item.id:
            return
        if item.summary:  # an empty plan summary keeps the card's, as the SQL CASE does
            card = card.__replace__(
                summary=item.summary, summary_source="plan", summary_basis_sha256=summary_basis
            )
        self._state.cards[item.id] = card.__replace__(
            title=item.title,
            description=item.instructions,
            required_actor=item.required_actor,
            execution_mode=item.execution_mode,
            human_action_reason=item.human_action_reason,
            human_instructions=item.human_instructions,
            phase_id=item.phase_id,
            updated_at=now,
        )

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

    def manual(self, loop_id: str) -> list[CardsRow]:
        return sorted(
            (
                card
                for card in self._state.cards.values()
                if card.loop_id == loop_id and card.kind == "manual"
            ),
            key=lambda card: (card.created_at, card.id),
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

    def get(self, label_id: str) -> LabelsRow | None:
        return self._state.labels.get(label_id)

    def find(self, reference: str) -> LabelsRow | None:
        return next(
            (row for row in self._state.labels.values() if reference in {row.id, row.name}), None
        )

    def by_name(self, name: str) -> LabelsRow | None:
        return next((row for row in self._state.labels.values() if row.name == name), None)

    def _name_taken(self, name: str, *, other_than: str) -> bool:
        return any(
            label.name == name and label.id != other_than for label in self._state.labels.values()
        )

    def add(self, row: LabelsRow) -> None:
        if row.id in self._state.labels:
            raise ConstraintError(f"labels.id {row.id} exists")
        if self._name_taken(row.name, other_than=row.id):
            raise ConstraintError(f"labels.name {row.name} exists")
        self._state.labels[row.id] = row

    def update(self, label_id: str, changes: LabelChanges) -> None:
        if not changes:
            raise ConstraintError("an update without a column is not SQL")
        row = self._state.labels.get(label_id)
        if row is None:
            return
        if "name" in changes and self._name_taken(changes["name"], other_than=label_id):
            raise ConstraintError(f"labels.name {changes['name']} exists")
        self._state.labels[label_id] = row.__replace__(**changes)

    def delete(self, label_id: str) -> None:
        self._state.labels.pop(label_id, None)
        # ON DELETE CASCADE: the cards that carried the label lose it.
        self._state.card_labels = [
            link for link in self._state.card_labels if link.label_id != label_id
        ]


def _by_position(rows: Iterable[ChecklistsRow]) -> list[ChecklistsRow]:
    return sorted(rows, key=lambda row: (row.position, row.id))


def _items_by_position(rows: Iterable[ChecklistItemsRow]) -> list[ChecklistItemsRow]:
    return sorted(rows, key=lambda row: (row.position, row.id))


class FakeChecklistRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, checklist_id: str) -> ChecklistsRow | None:
        return self._state.checklists.get(checklist_id)

    def for_card(self, card_id: str) -> list[ChecklistsRow]:
        return _by_position(
            row for row in self._state.checklists.values() if row.card_id == card_id
        )

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for checklist_id, position in positions:
            row = self._state.checklists.get(checklist_id)
            if row is not None:
                self._state.checklists[checklist_id] = row.__replace__(position=position)

    def add(self, row: ChecklistsRow) -> None:
        if row.id in self._state.checklists:
            raise ConstraintError(f"checklists.id {row.id} exists")
        if row.card_id not in self._state.cards:
            raise ConstraintError(f"checklists.card_id {row.card_id} does not exist")
        self._state.checklists[row.id] = row

    def rename(self, checklist_id: str, title: str) -> None:
        row = self._state.checklists.get(checklist_id)
        if row is not None:
            self._state.checklists[checklist_id] = row.__replace__(title=title)

    def delete(self, checklist_id: str) -> None:
        self._state.checklists.pop(checklist_id, None)
        # ON DELETE CASCADE: the items go with their checklist.
        self._state.checklist_items = {
            item_id: item
            for item_id, item in self._state.checklist_items.items()
            if item.checklist_id != checklist_id
        }


class FakeChecklistItemRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, item_id: str) -> ChecklistItemsRow | None:
        return self._state.checklist_items.get(item_id)

    def for_card(self, card_id: str) -> list[ChecklistItemsRow]:
        # The JOIN: items whose checklist belongs to the card.
        checklists = {
            row.id for row in self._state.checklists.values() if row.card_id == card_id
        }
        return _items_by_position(
            item
            for item in self._state.checklist_items.values()
            if item.checklist_id in checklists
        )

    def for_checklist(self, checklist_id: str) -> list[ChecklistItemsRow]:
        return _items_by_position(
            item
            for item in self._state.checklist_items.values()
            if item.checklist_id == checklist_id
        )

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for item_id, position in positions:
            row = self._state.checklist_items.get(item_id)
            if row is not None:
                self._state.checklist_items[item_id] = row.__replace__(position=position)

    def add(self, row: ChecklistItemsRow) -> None:
        if row.id in self._state.checklist_items:
            raise ConstraintError(f"checklist_items.id {row.id} exists")
        if row.checklist_id not in self._state.checklists:
            raise ConstraintError(
                f"checklist_items.checklist_id {row.checklist_id} does not exist"
            )
        self._state.checklist_items[row.id] = row

    def update(self, item_id: str, changes: ChecklistItemChanges) -> None:
        if not changes:
            raise ConstraintError("an update without a column is not SQL")
        row = self._state.checklist_items.get(item_id)
        if row is not None:
            self._state.checklist_items[item_id] = row.__replace__(**changes)

    def delete(self, item_id: str) -> None:
        self._state.checklist_items.pop(item_id, None)


class FakeCommentRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, comment_id: str) -> CommentsRow | None:
        return self._state.comments.get(comment_id)

    def for_card(self, card_id: str) -> list[CommentsRow]:
        # ORDER BY created_at, rowid: a stable sort over the insertion (rowid) order.
        return sorted(
            (row for row in self._state.comments.values() if row.card_id == card_id),
            key=lambda row: row.created_at,
        )

    def add(self, row: CommentsRow) -> None:
        if row.id in self._state.comments:
            raise ConstraintError(f"comments.id {row.id} exists")
        if row.card_id not in self._state.cards:
            raise ConstraintError(f"comments.card_id {row.card_id} does not exist")
        self._state.comments[row.id] = row

    def edit(self, comment_id: str, content: str, *, now: str) -> None:
        row = self._state.comments.get(comment_id)
        if row is not None:
            self._state.comments[comment_id] = row.__replace__(content=content, updated_at=now)

    def delete(self, comment_id: str) -> None:
        self._state.comments.pop(comment_id, None)


class FakeAttachmentRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def live(self, *, card_id: str | None) -> list[AttachmentsRow]:
        # ORDER BY created_at; equal times keep the insertion (rowid) order.
        return sorted(
            (
                row
                for row in self._state.attachments.values()
                if row.deleted_at is None and (card_id is None or row.card_id == card_id)
            ),
            key=lambda row: row.created_at,
        )

    def get_live(self, attachment_id: str) -> AttachmentsRow | None:
        row = self._state.attachments.get(attachment_id)
        return row if row is not None and row.deleted_at is None else None

    def live_size(self) -> int:
        return sum(
            row.size_bytes for row in self._state.attachments.values() if row.deleted_at is None
        )

    def add(self, row: AttachmentsRow) -> None:
        if row.id in self._state.attachments:
            raise ConstraintError(f"attachments.id {row.id} exists")
        if any(
            other.stored_filename == row.stored_filename
            for other in self._state.attachments.values()
        ):
            raise ConstraintError(f"attachments.stored_filename {row.stored_filename} exists")
        if row.card_id is not None and row.card_id not in self._state.cards:
            raise ConstraintError(f"attachments.card_id {row.card_id} does not exist")
        self._state.attachments[row.id] = row

    def mark_deleted(self, attachment_id: str, *, now: str) -> None:
        row = self._state.attachments.get(attachment_id)
        if row is not None:
            self._state.attachments[attachment_id] = row.__replace__(deleted_at=now)


_FTS_PHRASE = re.compile(r'"([^"]*)"\*')
_FTS_TOKEN = re.compile(r"[^\W_]+")


def _fts_tokens(text: str) -> list[str]:
    """FTS5's unicode61 tokenizer, closely enough: runs of letters and digits, case-folded."""
    return [token.casefold() for token in _FTS_TOKEN.findall(text)]


def fts_matches(expression: str, card: CardsRow) -> bool:
    """FTS5 ``MATCH`` for the expressions ``search.fts_query`` writes: prefix phrases joined by
    AND. A phrase matches consecutive tokens of the title or of the description, the last one by
    prefix; a phrase without a token matches nothing, and an expression without a phrase is a
    syntax error, as SQLite answers."""
    phrases = _FTS_PHRASE.findall(expression)
    if not phrases:
        raise ValueError('fts5: syntax error near ""')
    columns = [_fts_tokens(card.title), _fts_tokens(card.description)]
    return all(_phrase_in(_fts_tokens(phrase), columns) for phrase in phrases)


def _phrase_in(phrase: list[str], columns: list[list[str]]) -> bool:
    if not phrase:
        return False
    *exact, prefix = phrase
    for tokens in columns:
        for start in range(len(tokens) - len(phrase) + 1):
            window = tokens[start : start + len(phrase)]
            if window[:-1] == exact and window[-1].startswith(prefix):
                return True
    return False


class FakeCardSearchRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def _label_matches(self, card_id: str, label: str) -> bool:
        for link in self._state.card_labels:
            row = self._state.labels.get(link.label_id)
            if link.card_id == card_id and row is not None and label in {row.id, row.name}:
                return True
        return False

    def _matches(self, card: CardsRow, search: CardSearch) -> bool:
        if search.match is not None:
            text_matches = fts_matches(search.match, card)
        elif search.contains is not None:
            pattern = f"%{search.contains}%"
            text_matches = like(card.title, pattern) or like(card.description, pattern)
        else:
            text_matches = True
        checks = (
            card.loop_id == search.loop_id,
            text_matches,
            search.include_archived or card.archived_at is None,
            search.priority is None or card.priority == search.priority,
            search.label is None or self._label_matches(card.id, search.label),
            search.completed is None or (card.completed_at is not None) == search.completed,
            search.overdue_at is None
            or (
                card.due_at is not None
                and card.due_at < search.overdue_at
                and card.completed_at is None
            ),
            search.list_id is None or card.list_id == search.list_id,
        )
        return all(checks)

    def count(self, search: CardSearch) -> int:
        return sum(1 for card in self._state.cards.values() if self._matches(card, search))

    def page(self, search: CardSearch, *, limit: int, offset: int) -> list[CardsRow]:
        found = [card for card in self._state.cards.values() if self._matches(card, search)]
        # ORDER BY updated_at DESC, id: the tie-break first, then the stable descending sort.
        found.sort(key=lambda card: card.id)
        found.sort(key=lambda card: card.updated_at, reverse=True)
        return found[offset : offset + limit]


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


class FakeLoopAgentRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def for_loop(self, loop_id: str) -> dict[str, str]:
        return {
            row.purpose: row.agent_id
            for (owner, _), row in self._state.loop_agents.items()
            if owner == loop_id
        }

    def agent_for(self, loop_id: str, purpose: str) -> str | None:
        row = self._state.loop_agents.get((loop_id, purpose))
        return None if row is None else row.agent_id

    def replace(self, loop_id: str, purpose: str, agent_id: str | None, *, now: str) -> None:
        if loop_id not in self._state.loops:
            # The table's foreign key: a preference names a Loop of this board.
            raise ConstraintError("FOREIGN KEY constraint failed")
        self._state.loop_agents.pop((loop_id, purpose), None)
        if agent_id:
            self._state.loop_agents[(loop_id, purpose)] = LoopAgentPreferencesRow(
                loop_id=loop_id, purpose=purpose, agent_id=agent_id, updated_at=now
            )


def _next_seq(rows: Iterable[CardEventsRow] | Iterable[DiscussionEventsRow]) -> int:
    return max((row.seq for row in rows), default=0) + 1


class FakeEventRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def add_discussion_event(self, discussion_id: str, event: NewEvent) -> int:
        if discussion_id not in self._state.discussions:
            raise ConstraintError("FOREIGN KEY constraint failed")
        seq = _next_seq(self._state.discussion_events)
        self._state.discussion_events.append(
            DiscussionEventsRow(seq=seq, discussion_id=discussion_id, **event)
        )
        return seq

    def add_card_event(self, card_id: str, event: NewEvent) -> int:
        if card_id not in self._state.cards:
            raise ConstraintError("FOREIGN KEY constraint failed")
        seq = _next_seq(self._state.card_events)
        self._state.card_events.append(CardEventsRow(seq=seq, card_id=card_id, **event))
        return seq

    def discussion_events(
        self, discussion_id: str, *, after: int, limit: int
    ) -> list[DiscussionEventsRow]:
        found = [
            row
            for row in self._state.discussion_events
            if row.discussion_id == discussion_id and row.seq > after
        ]
        return sorted(found, key=lambda row: row.seq)[:limit]

    def card_events(self, card_id: str, *, after: int, limit: int) -> list[CardEventsRow]:
        found = [
            row
            for row in self._state.card_events
            if row.card_id == card_id and row.seq > after
        ]
        return sorted(found, key=lambda row: row.seq)[:limit]

    def discussion_exists(self, discussion_id: str) -> bool:
        return discussion_id in self._state.discussions


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
        self.phases: LoopPhaseRepository = FakeLoopPhaseRepository(state)
        self.plan_items: LoopPlanItemRepository = FakeLoopPlanItemRepository(state)
        self.dependencies: LoopDependencyRepository = FakeLoopDependencyRepository(state)
        self.qa: LoopQaRepository = FakeLoopQaRepository(state)
        self.idempotency: BoardIdempotencyRepository = FakeBoardIdempotencyRepository(state)
        self.checklists: ChecklistRepository = FakeChecklistRepository(state)
        self.checklist_items: ChecklistItemRepository = FakeChecklistItemRepository(state)
        self.comments: CommentRepository = FakeCommentRepository(state)
        self.notes: LoopNoteRepository = FakeLoopNoteRepository(state.notes)
        self.attachments: AttachmentRepository = FakeAttachmentRepository(state)
        self.search: CardSearchRepository = FakeCardSearchRepository(state)
        self.loop_agents: LoopAgentRepository = FakeLoopAgentRepository(state)
        self.events: EventRepository = FakeEventRepository(state)
        self.threads: DiscussionThreadRepository = FakeDiscussionThreadRepository(state)
        self.messages: DiscussionMessageRepository = FakeDiscussionMessageRepository(state)
        self.participants: DiscussionParticipantRepository = (
            FakeDiscussionParticipantRepository(state)
        )
        self.votes: DiscussionVoteRepository = FakeDiscussionVoteRepository(state)
        self.runs: DiscussionRunRepository = FakeDiscussionRunRepository(state)
        self.rounds: DiscussionRoundRepository = FakeDiscussionRoundRepository(state)
        self.outcomes: DiscussionOutcomeRepository = FakeDiscussionOutcomeRepository(state)
        self.mention_jobs: MentionJobRepository = FakeMentionJobRepository(state)
        self.generation_runs: GenerationRunRepository = FakeGenerationRunRepository(state)
        self.archive: LoopArchiveRepository = FakeLoopArchiveRepository(state)
        self.history: LoopHistoryRepository = FakeLoopHistoryRepository(state)
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
