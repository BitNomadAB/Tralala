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
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict
from uuid import uuid4

from pydantic import JsonValue

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, NotFound, ValidationFailure, VersionConflict
from ..db.generated.board import (
    ListsRow,
    LoopApprovalsRow,
    LoopDocumentsRow,
    LoopPlansRow,
    LoopQaCyclesRow,
    LoopsRow,
)
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.cards import TicketProgress
from ..repositories.loop_plans import PlanTotals
from ..repositories.loops import LoopChanges
from ..schemas.loops import (
    DOCUMENT_KINDS,
    LOOP_STAGES,
    HumanConfirmation,
    LoopCancel,
    LoopCreate,
    LoopUpdate,
)
from . import idempotency
from .activity import activity_entry
from .common import request_fingerprint
from .lists import BoardChecks
from .loop_identifiers import format_loop_key, loop_prefix
from .plan_views import PlanView, PlanViews, Readiness, ReadinessItem

if TYPE_CHECKING:
    from .cards import CardEntry

OPEN_STAGES = tuple(stage for stage in LOOP_STAGES if stage not in {"completed", "cancelled"})
EXECUTION_STAGES = ("ready", "in_progress", "awaiting_qa")
QA_OPEN_STATUSES = ("pending", "instructions_ready", "in_progress")
ANALYSIS_KINDS = ("info", "analysis_ai", "analysis")
ROADMAP_KINDS = ("info", "analysis_ai", "analysis", "roadmap_ai", "roadmap")


# --- the documents, approvals and stage of a Loop ------------------------------------------------


@dataclass(slots=True)
class DocumentSlot:
    """A document kind's current revision and its approved one (often the same row)."""

    current: LoopDocumentsRow | None = None
    approved: LoopDocumentsRow | None = None


type DocumentSlots = dict[str, DocumentSlot]
"""Every document kind's slot; all of ``DOCUMENT_KINDS`` are keys."""

type Approvals = dict[str, LoopApprovalsRow]
"""The newest decision of each review scope that nobody has superseded."""

type StaleReasons = dict[str, list[str]]
"""Why each document kind no longer matches its inputs; an empty list means it does."""


def document_slots(records: Iterable[LoopDocumentsRow]) -> DocumentSlots:
    """The slots, from current and approved revisions in revision order (a later one wins)."""
    slots: DocumentSlots = {kind: DocumentSlot() for kind in DOCUMENT_KINDS}
    for record in records:
        slot = slots.setdefault(record.kind, DocumentSlot())
        if record.is_current:
            slot.current = record
        if record.is_approved:
            slot.approved = record
    return slots


def latest_approvals(newest_first: Iterable[LoopApprovalsRow]) -> Approvals:
    latest: Approvals = {}
    for record in newest_first:
        # A superseded row is history: either a newer decision replaced it, or the person
        # withdrew the approval. Neither counts as the Loop's current approval.
        if record.superseded_at:
            continue
        latest.setdefault(record.scope, record)
    return latest


def _reviewed(approval: LoopApprovalsRow) -> dict[str, JsonValue]:
    """The revision each document kind had when the decision was taken.

    Unreadable JSON or ``null`` reviewed nothing; any other non-object raises the
    ``AttributeError`` that reading a kind from it always raised.
    """
    try:
        value: JsonValue = json.loads(approval.revisions_json)
    except ValueError:
        return {}
    if value is None:
        return {}
    if not isinstance(value, dict):
        # The AttributeError that reading a kind from it (``.get``) always raised.
        raise AttributeError(f"the reviewed revisions are a {type(value).__name__}")  # noqa: TRY004
    return value


def _revision_id(row: LoopDocumentsRow | None) -> str | None:
    return None if row is None else row.id


def stale_reasons(documents: DocumentSlots, approvals: Approvals) -> StaleReasons:
    reasons: StaleReasons = {kind: [] for kind in DOCUMENT_KINDS}
    info = documents["info"].current
    analysis_ai = documents["analysis_ai"].current
    analysis = documents["analysis"].current
    roadmap_ai = documents["roadmap_ai"].current
    roadmap = documents["roadmap"].current

    if analysis_ai is not None:
        if info is None:
            reasons["analysis_ai"].append("info_missing")
        elif analysis_ai.source_info_revision_id != info.id:
            reasons["analysis_ai"].append("info_changed")
    if analysis is not None:
        if analysis_ai is None:
            reasons["analysis"].append("analysis_ai_missing")
        elif analysis.source_analysis_ai_revision_id != analysis_ai.id:
            reasons["analysis"].append("analysis_ai_changed")
        elif reasons["analysis_ai"]:
            reasons["analysis"].append("upstream_stale")
    if reasons["analysis_ai"] or reasons["analysis"]:
        reasons["roadmap_ai"].append("upstream_stale")
        reasons["roadmap"].append("upstream_stale")
    if roadmap_ai is not None:
        for kind, present in (
            ("info", info),
            ("analysis_ai", analysis_ai),
            ("analysis", analysis),
        ):
            if present is None:
                reasons["roadmap_ai"].append(f"{kind}_missing")
        if info is not None and roadmap_ai.source_info_revision_id != info.id:
            reasons["roadmap_ai"].append("info_changed")
        if analysis_ai is not None and roadmap_ai.source_analysis_ai_revision_id != analysis_ai.id:
            reasons["roadmap_ai"].append("analysis_ai_changed")
        if analysis is not None and roadmap_ai.source_analysis_revision_id != analysis.id:
            reasons["roadmap_ai"].append("analysis_changed")
    if roadmap is not None:
        if roadmap_ai is None:
            reasons["roadmap"].append("roadmap_ai_missing")
        elif roadmap.source_roadmap_ai_revision_id != roadmap_ai.id:
            reasons["roadmap"].append("roadmap_ai_changed")

    for scope in ("analysis", "roadmap"):
        approval = approvals.get(scope)
        if approval is None or approval.decision != "approved":
            continue
        reviewed = _reviewed(approval)
        expected = {
            "info": _revision_id(info),
            "analysis_ai": _revision_id(analysis_ai),
            "analysis": _revision_id(analysis),
        }
        if scope == "roadmap":
            expected["roadmap_ai"] = _revision_id(roadmap_ai)
            expected["roadmap"] = _revision_id(roadmap)
        for kind, revision_id in expected.items():
            if revision_id is None:
                continue
            if reviewed.get(kind) != revision_id:
                reasons.setdefault(kind, []).append("approval_superseded")
    return reasons


def analysis_approved(documents: DocumentSlots, approvals: Approvals, stale: StaleReasons) -> bool:
    approval = approvals.get("analysis")
    if approval is None or approval.decision != "approved":
        return False
    if any(stale.get(kind) for kind in ANALYSIS_KINDS):
        return False
    return all(documents[kind].current is not None for kind in ANALYSIS_KINDS)


def roadmap_approved(documents: DocumentSlots, approvals: Approvals, stale: StaleReasons) -> bool:
    approval = approvals.get("roadmap")
    if approval is None or approval.decision != "approved":
        return False
    if any(stale.get(kind) for kind in DOCUMENT_KINDS):
        return False
    return all(documents[kind].current is not None for kind in ROADMAP_KINDS)


def compute_stage(
    loop: LoopsRow,
    documents: DocumentSlots,
    approvals: Approvals,
    stale: StaleReasons,
    *,
    has_active_plan: bool,
    tickets_done: int,
) -> str:
    """The stage the Loop is in. Completion and cancellation are recorded, never computed."""
    if loop.completed_at is not None:
        return "completed"
    if loop.cancelled_at is not None:
        return "cancelled"
    any_stale = any(stale.get(kind) for kind in DOCUMENT_KINDS)
    if loop.implementation_approval_id and not loop.qa_approval_id:
        if any_stale or not analysis_approved(documents, approvals, stale):
            return "replanning"
        return "awaiting_qa"
    if has_active_plan:
        if any_stale or not roadmap_approved(documents, approvals, stale):
            return "replanning"
        return "in_progress" if tickets_done else "ready"
    if analysis_approved(documents, approvals, stale):
        return "planning"
    if documents["analysis"].current is not None:
        return "analysis_review"
    if documents["roadmap"].current is not None:
        return "roadmap_review"
    return "draft"


# --- the Loop's JSON -----------------------------------------------------------------------------


class DocumentEntry(TypedDict):
    """A document revision as the API returns it: every column of its row."""

    id: str
    loop_id: str
    kind: str
    revision_number: int
    content: str
    payload_json: str | None
    content_hash: str
    status: str
    source_info_revision_id: str | None
    source_analysis_ai_revision_id: str | None
    source_analysis_revision_id: str | None
    source_roadmap_ai_revision_id: str | None
    generation_run_id: str | None
    author_actor_id: str
    author_actor_type: str
    author_name: str
    provenance_json: str
    is_current: int
    is_approved: int
    created_at: str


class DocumentState(TypedDict):
    kind: str
    state: str
    current: DocumentEntry | None
    approved: DocumentEntry | None
    stale_reasons: list[str]


class PlanSummary(TypedDict):
    plan_id: str
    revision_number: int
    activated_at: str | None
    phase_count: int
    ticket_total: int
    ticket_completed: int


class QaSummary(TypedDict):
    cycle_id: str
    cycle_number: int
    status: str
    card_id: str | None
    open: bool


class Progress(TypedDict):
    ticket_total: int
    ticket_completed: int
    ticket_archived_incomplete: int


class LoopWarning(TypedDict):
    code: str
    kind: NotRequired[str]
    reasons: NotRequired[list[str]]
    message: str


class LoopEntry(TypedDict):
    """A Loop as the API returns it: its row, its board, and its documents, plan, QA and
    progress with the warnings they raise."""

    id: str
    name: str
    goal: str
    sequence: int
    key_prefix: str
    key: str
    stage: str
    version: int
    current_plan_id: str | None
    analysis_approval_id: str | None
    roadmap_approval_id: str | None
    implementation_approval_id: str | None
    qa_approval_id: str | None
    active_qa_cycle_id: str | None
    history_id: str | None
    created_by_actor_id: str
    created_by_actor_type: str
    created_by_name: str
    created_at: str
    updated_at: str
    archived_at: str | None
    cancelled_at: str | None
    completed_at: str | None
    board_id: str
    documents: dict[str, DocumentState]
    plan: PlanSummary | None
    qa: QaSummary | None
    progress: Progress
    warnings: list[LoopWarning]


def document_entry(row: LoopDocumentsRow | None) -> DocumentEntry | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "loop_id": row.loop_id,
        "kind": row.kind,
        "revision_number": row.revision_number,
        "content": row.content,
        "payload_json": row.payload_json,
        "content_hash": row.content_hash,
        "status": row.status,
        "source_info_revision_id": row.source_info_revision_id,
        "source_analysis_ai_revision_id": row.source_analysis_ai_revision_id,
        "source_analysis_revision_id": row.source_analysis_revision_id,
        "source_roadmap_ai_revision_id": row.source_roadmap_ai_revision_id,
        "generation_run_id": row.generation_run_id,
        "author_actor_id": row.author_actor_id,
        "author_actor_type": row.author_actor_type,
        "author_name": row.author_name,
        "provenance_json": row.provenance_json,
        "is_current": row.is_current,
        "is_approved": row.is_approved,
        "created_at": row.created_at,
    }


def document_state(
    kind: str, documents: DocumentSlots, approvals: Approvals, stale: StaleReasons
) -> DocumentState:
    current = documents[kind].current
    approved = documents[kind].approved
    reasons = list(stale.get(kind, []))
    if current is None:
        state = "empty"
    elif reasons:
        state = "stale"
    elif approved is not None and approved.id == current.id:
        state = "approved"
    elif current.status == "ready_for_review":
        state = "ready_for_review"
    else:
        state = current.status if current.status != "approved" else "draft"
        scope = "analysis" if kind in {"analysis_ai", "analysis"} else "roadmap"
        latest = approvals.get(scope)
        if (
            latest is not None
            and latest.decision == "changes_requested"
            and _reviewed(latest).get(kind) == current.id
        ):
            state = "changes_requested"
    return {
        "kind": kind,
        "state": state,
        "current": document_entry(current),
        "approved": document_entry(approved),
        "stale_reasons": reasons,
    }


def plan_summary(
    plan: LoopPlansRow | None, phases: int, totals: PlanTotals | None
) -> PlanSummary | None:
    if plan is None:
        return None
    counts = totals or PlanTotals(total=0, completed=0)
    return {
        "plan_id": plan.id,
        "revision_number": plan.revision_number,
        "activated_at": plan.activated_at,
        "phase_count": phases,
        "ticket_total": counts.total,
        "ticket_completed": counts.completed,
    }


def qa_summary(cycles: list[LoopQaCyclesRow]) -> QaSummary | None:
    """The open cycle, or else the latest one; cycles come by cycle number."""
    if not cycles:
        return None
    opened = [cycle for cycle in cycles if cycle.status in QA_OPEN_STATUSES]
    latest = opened[0] if opened else max(cycles, key=lambda cycle: cycle.cycle_number)
    return {
        "cycle_id": latest.id,
        "cycle_number": latest.cycle_number,
        "status": latest.status,
        "card_id": latest.card_id,
        "open": bool(opened),
    }


def progress_entry(progress: TicketProgress | None) -> Progress:
    counts = progress or TicketProgress(total=0, completed=0, archived_incomplete=0)
    return {
        "ticket_total": counts.total,
        "ticket_completed": counts.completed,
        "ticket_archived_incomplete": counts.archived_incomplete,
    }


def loop_warnings(
    stage: str, documents: DocumentSlots, approvals: Approvals, stale: StaleReasons
) -> list[LoopWarning]:
    warnings: list[LoopWarning] = []
    for kind in DOCUMENT_KINDS:
        reasons = stale.get(kind) or []
        if reasons and documents[kind].current is not None:
            warnings.append(
                {
                    "code": "document_stale",
                    "kind": kind,
                    "reasons": reasons,
                    "message": f"{kind.replace('_', ' ').title()} needs regeneration",
                }
            )
    if stage == "replanning":
        warnings.append(
            {
                "code": "plan_change_required",
                "message": "Execution is blocked until a replacement plan is approved",
            }
        )
    if stage == "awaiting_qa":
        warnings.append(
            {
                "code": "qa_incomplete",
                "message": "QA is outstanding; the Loop cannot be completed yet",
            }
        )
    if "analysis" not in approvals:
        warnings.append({"code": "approval_required", "message": "Analysis has not been approved"})
    return warnings


@dataclass(slots=True, kw_only=True)
class LoopFacts:
    """What a Loop's JSON shows besides its row."""

    documents: DocumentSlots = field(default_factory=dict[str, DocumentSlot])
    approvals: Approvals = field(default_factory=dict[str, LoopApprovalsRow])
    plan: PlanSummary | None = None
    qa: QaSummary | None = None
    progress: Progress = field(default_factory=lambda: progress_entry(None))


def loop_entry(board_id: str, loop: LoopsRow, facts: LoopFacts) -> LoopEntry:
    documents = facts.documents or document_slots(())
    stale = stale_reasons(documents, facts.approvals)
    return {
        "id": loop.id,
        "name": loop.name,
        "goal": loop.goal,
        "sequence": loop.sequence,
        "key_prefix": loop.key_prefix,
        "key": loop.key,
        "stage": loop.stage,
        "version": loop.version,
        "current_plan_id": loop.current_plan_id,
        "analysis_approval_id": loop.analysis_approval_id,
        "roadmap_approval_id": loop.roadmap_approval_id,
        "implementation_approval_id": loop.implementation_approval_id,
        "qa_approval_id": loop.qa_approval_id,
        "active_qa_cycle_id": loop.active_qa_cycle_id,
        "history_id": loop.history_id,
        "created_by_actor_id": loop.created_by_actor_id,
        "created_by_actor_type": loop.created_by_actor_type,
        "created_by_name": loop.created_by_name,
        "created_at": loop.created_at,
        "updated_at": loop.updated_at,
        "archived_at": loop.archived_at,
        "cancelled_at": loop.cancelled_at,
        "completed_at": loop.completed_at,
        "board_id": board_id,
        "documents": {
            kind: document_state(kind, documents, facts.approvals, stale)
            for kind in DOCUMENT_KINDS
        },
        "plan": facts.plan,
        "qa": facts.qa,
        "progress": facts.progress,
        "warnings": loop_warnings(loop.stage, documents, facts.approvals, stale),
    }


# --- the rules every Loop service shares ---------------------------------------------------------


def require_loop(repos: BoardRepositories, loop_id: str) -> LoopsRow:
    """The Loop, archived, cancelled and completed ones included, or ``404 loop_not_found``."""
    loop = repos.loops.get(loop_id)
    if loop is None:
        raise NotFound("Loop not found", code="loop_not_found")
    return loop


def ensure_writable(loop: LoopsRow) -> None:
    """Completed, cancelled and archived Loops are read-only (``409 loop_read_only``)."""
    if loop.completed_at is not None or loop.stage == "completed":
        raise Conflict(
            "This Loop is completed and read-only",
            code="loop_read_only",
            details={"loop_id": loop.id},
        )
    if loop.cancelled_at is not None or loop.stage == "cancelled":
        raise Conflict(
            "This Loop was cancelled",
            code="loop_read_only",
            details={"loop_id": loop.id},
        )
    if loop.archived_at is not None:
        raise Conflict(
            "This Loop is archived",
            code="loop_read_only",
            details={"loop_id": loop.id},
        )


def ensure_execution_allowed(loop: LoopsRow) -> None:
    """Delivery work starts and completes only while the Loop executes an approved plan."""
    stage = loop.stage
    if stage in EXECUTION_STAGES:
        return
    code = (
        "plan_change_required" if stage in {"replanning", "roadmap_review"} else "approval_required"
    )
    raise Conflict(
        "Delivery work cannot start or complete in this Loop stage",
        code=code,
        details={"stage": stage, "loop_id": loop.id},
    )


def refresh_stage(repos: BoardRepositories, loop_id: str, *, now: str) -> str:
    """Compute the Loop's stage from its documents, approvals, plan and Tickets, and store it when
    it changed; returns the stage."""
    loop = require_loop(repos, loop_id)
    documents = document_slots(repos.documents.current_or_approved(loop_id))
    approvals = latest_approvals(repos.approvals.newest_first(loop_id))
    stale = stale_reasons(documents, approvals)
    has_active_plan = repos.plans.active(loop_id) is not None
    tickets_done = repos.cards.completed_tickets(loop_id)
    stage = compute_stage(
        loop,
        documents,
        approvals,
        stale,
        has_active_plan=has_active_plan,
        tickets_done=tickets_done,
    )
    if stage != loop.stage:
        repos.loops.set_stage(loop_id, stage, now=now)
    return stage


def loop_facts(repos: BoardRepositories, loop_id: str) -> LoopFacts:
    """One Loop's documents, approvals, plan, QA and progress."""
    plan = repos.plans.active(loop_id)
    summary = None
    if plan is not None:
        summary = plan_summary(
            plan,
            repos.plans.phase_counts(loop_id).get(loop_id, 0),
            repos.plans.ticket_totals(loop_id).get(loop_id),
        )
    return LoopFacts(
        documents=document_slots(repos.documents.current_or_approved(loop_id)),
        approvals=latest_approvals(repos.approvals.newest_first(loop_id)),
        plan=summary,
        qa=qa_summary(repos.qa.cycles(loop_id)),
        progress=progress_entry(repos.cards.progress(loop_id).get(loop_id)),
    )


def board_loop_facts(repos: BoardRepositories) -> dict[str, LoopFacts]:
    """Every Loop's facts with a constant number of statements.

    The overview renders every Loop of a board, so loading documents, approvals, plans, QA and
    progress per Loop made the response cost grow with the number of Loops. A Loop without any
    of them is absent; ``LoopFacts()`` is its empty value.
    """
    facts: dict[str, LoopFacts] = {}

    def of(loop_id: str) -> LoopFacts:
        return facts.setdefault(loop_id, LoopFacts())

    documents: dict[str, list[LoopDocumentsRow]] = {}
    for record in repos.documents.current_or_approved(None):
        documents.setdefault(record.loop_id, []).append(record)
    for loop_id, records in documents.items():
        of(loop_id).documents = document_slots(records)
    approvals: dict[str, list[LoopApprovalsRow]] = {}
    for record in repos.approvals.newest_first(None):
        approvals.setdefault(record.loop_id, []).append(record)
    for loop_id, records in approvals.items():
        of(loop_id).approvals = latest_approvals(records)
    phases = repos.plans.phase_counts(None)
    totals = repos.plans.ticket_totals(None)
    for loop_id, plan in repos.plans.active_by_loop().items():
        of(loop_id).plan = plan_summary(plan, phases.get(loop_id, 0), totals.get(loop_id))
    cycles: dict[str, list[LoopQaCyclesRow]] = {}
    for cycle in repos.qa.cycles(None):
        cycles.setdefault(cycle.loop_id, []).append(cycle)
    for loop_id, loop_cycles in cycles.items():
        of(loop_id).qa = qa_summary(loop_cycles)
    for loop_id, progress in repos.cards.progress(None).items():
        of(loop_id).progress = progress_entry(progress)
    return facts


def readiness_item(readiness: Readiness, card_id: str) -> ReadinessItem | None:
    """The planned Ticket behind ``card_id``, or None for a card outside the plan."""
    for item in readiness["items"]:
        if item["card_id"] == card_id:
            return item
    return None


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
        fingerprint = request_fingerprint(
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
    "DOCUMENT_KINDS",
    "EXECUTION_STAGES",
    "OPEN_STAGES",
    "LoopService",
]
