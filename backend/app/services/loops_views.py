"""The Loop's JSON: its row, its board, and its documents, plan, QA and progress with the
warnings they raise, and the facts behind them read through the board repositories (one Loop's,
or every Loop's of a board with a constant number of statements). ``loops`` re-exports every name
here, so callers keep importing them from there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NotRequired, TypedDict

from ..db.generated.board import (
    LoopApprovalsRow,
    LoopDocumentsRow,
    LoopPlansRow,
    LoopQaCyclesRow,
    LoopsRow,
)
from ..repositories.board import BoardRepositories
from ..repositories.cards import TicketProgress
from ..repositories.loop_plans import PlanTotals
from ..schemas.loops import DOCUMENT_KINDS
from .loops_stage import (
    QA_OPEN_STATUSES,
    Approvals,
    DocumentSlot,
    DocumentSlots,
    DocumentState,
    StaleReasons,
    document_slots,
    document_state,
    latest_approvals,
    stale_reasons,
)

# --- the Loop's JSON -----------------------------------------------------------------------------


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


# --- a Loop's facts ------------------------------------------------------------------------------


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
