"""Revisioned Loop documents and human approvals.

Five slots per Loop: ``info`` (human intent), ``analysis_ai``/``analysis`` and
``roadmap_ai``/``roadmap``. Revisions are immutable; current and approved pointers are separate.
Human-facing Markdown is rendered from the validated structure so the human and machine views
cannot drift apart.

``LoopDocumentService`` reaches the board database only through the board unit of work, the
registry only through ``BoardChecks`` and the plan through ``LoopPlanService`` inside the same
unit of work; it takes the clock and the id source as arguments, so every rule here runs in a unit
test without a database. Approvals bind to exact revision ids, a changed input invalidates them,
and approving, requesting changes and resetting are a person's decisions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import NotRequired, TypedDict
from uuid import uuid4

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, Forbidden, ValidationFailure, VersionConflict
from ..db.generated.board import LoopApprovalsRow, LoopDocumentsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.loops import LOOP_APPROVAL_COLUMNS, ApprovalColumn
from ..schemas.loops import (
    AnalysisPayload,
    ApprovalRequest,
    CandidateSubmission,
    InfoRevisionWrite,
    PlanPayload,
    QaInstructions,
    ScopeResetRequest,
)
from .activity import activity_entry
from .lists import BoardChecks
from .loop_plans import CanonicalPlan, LoopPlanService
from .loops import (
    DOCUMENT_KINDS,
    Approvals,
    DocumentSlots,
    StaleReasons,
    analysis_approved,
    document_slots,
    document_state,
    ensure_writable,
    latest_approvals,
    refresh_stage,
    require_loop,
    stale_reasons,
)

ANALYSIS_SCOPE_KINDS = ("info", "analysis_ai", "analysis")
ROADMAP_SCOPE_KINDS = ("info", "analysis_ai", "analysis", "roadmap_ai", "roadmap")
REVIEW_SCOPES = ("analysis", "roadmap")
MATERIAL_FINDING_CATEGORIES = {"risk", "blocker", "legal", "security", "question"}
MAX_DOCUMENT_PAYLOAD = 200_000

# A worker may seed or refine Info while the Loop is still speculative — the phase in which a person
# and their agent agree on what to build. Once planning has started, changing the input invalidates
# approvals, so the edit belongs to a signed-in person.
WORKER_INFO_STAGES = frozenset({"draft", "analysis_review"})

# What a changed document invalidates: the Loop's approvals from its scope on, and the approved
# revisions of the kinds written from it.
_CLEARED_APPROVALS: dict[str, tuple[ApprovalColumn, ...]] = {
    "info": LOOP_APPROVAL_COLUMNS,
    "analysis_ai": LOOP_APPROVAL_COLUMNS,
    "analysis": LOOP_APPROVAL_COLUMNS,
    "roadmap_ai": LOOP_APPROVAL_COLUMNS[1:],
    "roadmap": LOOP_APPROVAL_COLUMNS[1:],
}
_STALE_KINDS: dict[str, tuple[str, ...]] = {
    "info": ("analysis_ai", "analysis", "roadmap_ai", "roadmap"),
    "analysis_ai": ("roadmap_ai", "roadmap"),
    "analysis": ("roadmap_ai", "roadmap"),
}


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def render_analysis(payload: AnalysisPayload) -> str:
    """Plain-language decision support; technical detail stays in a separate traceability block."""
    lines: list[str] = ["# Analysis", "", "## What this Loop sets out to achieve", ""]
    lines.append(payload.outcome or "Not described.")
    if payload.scope:
        lines += ["", "**In scope**", ""] + [f"- {item}" for item in payload.scope]
    if payload.non_goals:
        lines += ["", "**Not in scope**", ""] + [f"- {item}" for item in payload.non_goals]
    lines += ["", "## What was found", ""]
    if not payload.findings:
        lines.append("No findings were recorded.")
    for finding in payload.findings:
        lines.append(f"- **{finding.title}** — {finding.plain_language}")
    if payload.assumptions:
        lines += ["", "## Assumptions", ""] + [f"- {item}" for item in payload.assumptions]
    if payload.open_questions:
        lines += ["", "## Open questions", ""] + [f"- {item}" for item in payload.open_questions]
    if payload.options:
        lines += ["", "## Options considered", ""] + [f"- {item}" for item in payload.options]
    if payload.recommendation:
        lines += ["", "## Recommended direction", "", payload.recommendation]
    if payload.verification:
        lines += ["", "## How success can be checked", ""] + [
            f"- {item}" for item in payload.verification
        ]
    lines += ["", "---", "", "## Traceability", ""]
    for finding in payload.findings:
        detail = finding.technical_detail.replace("\n", " ").strip()
        lines.append(f"- `{finding.id}` ({finding.category}) {finding.title}: {detail}")
    if payload.sources:
        lines += ["", "**Sources**", ""] + [f"- {item}" for item in payload.sources]
    if payload.repository_revision:
        lines += ["", f"Baseline revision: `{payload.repository_revision}`"]
    return "\n".join(lines).strip() + "\n"


def render_roadmap(payload: CanonicalPlan) -> str:
    """Render the validated plan; prose is additive and structure comes from the server."""
    lines: list[str] = ["# RoadMap", ""]
    if payload["summary"]:
        lines += [payload["summary"], ""]
    phases = payload["phases"]
    by_id = {phase["id"]: phase for phase in phases}
    tickets_by_id = {ticket["id"]: ticket for phase in phases for ticket in phase["tickets"]}
    for phase in phases:
        lines += [f"## Phase {phase['number']} — {phase['name']}", ""]
        if phase["objective"]:
            lines += [phase["objective"], ""]
        if phase["narrative"]:
            lines += [phase["narrative"], ""]
        prerequisites: list[str] = []
        for reference in phase["prerequisite_phase_ids"]:
            other_phase = by_id.get(reference)
            if other_phase:
                prerequisites.append(f"Phase {other_phase['number']} ({other_phase['name']})")
        for reference in phase["prerequisite_ticket_ids"]:
            other_ticket = tickets_by_id.get(reference)
            if other_ticket:
                prerequisites.append(f"Ticket {other_ticket['key']}")
        if prerequisites:
            lines += ["**Starts after:** " + ", ".join(prerequisites), ""]
        if phase["entry_conditions"]:
            lines += ["**Before it can start:**"] + [
                f"- {item}" for item in phase["entry_conditions"]
            ] + [""]
        if phase["exit_conditions"]:
            lines += ["**Done when:**"] + [f"- {item}" for item in phase["exit_conditions"]] + [""]
        tickets = phase["tickets"]
        if tickets:
            lines += ["**Tickets**", ""]
        for ticket in tickets:
            human = ticket["required_actor"] == "human"
            gate = ticket["execution_mode"] == "pre_phase_gate"
            suffix = " — **Human action required**" if human else ""
            lines.append(f"- `{ticket['key']}` {ticket['title']}{suffix}")
            if gate:
                lines.append("  - This is a gate: the Phase cannot start until it is confirmed.")
            if ticket["objective"]:
                lines.append(f"  - Why: {ticket['objective']}")
            if ticket["note"]:
                lines.append(f"  - {ticket['note']}")
            if human:
                lines.append(f"  - Why a human is needed: {ticket['human_action_reason']}")
                lines.append(f"  - What you must do: {ticket['human_instructions']}")
            blocking: list[str] = []
            for reference in ticket["prerequisite_ticket_ids"]:
                other_ticket = tickets_by_id.get(reference)
                if other_ticket:
                    blocking.append(f"Ticket {other_ticket['key']}")
            for reference in ticket["prerequisite_phase_ids"]:
                other_phase = by_id.get(reference)
                if other_phase:
                    blocking.append(f"Phase {other_phase['number']}")
            if blocking:
                lines.append("  - Can be done after: " + ", ".join(blocking))
            if ticket["acceptance_criteria"]:
                lines.append("  - Accepted when: " + "; ".join(ticket["acceptance_criteria"]))
        lines.append("")
    lines += ["---", "", "Generated from the validated structured plan; the plan is authoritative."]
    return "\n".join(lines).strip() + "\n"


def render_analysis_technical(payload: AnalysisPayload) -> str:
    return "```json\n" + json.dumps(payload.model_dump(), indent=2, ensure_ascii=False) + "\n```\n"


def render_roadmap_technical(payload: CanonicalPlan) -> str:
    return "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```\n"


# --- the JSON the document routes return ---------------------------------------------------------


class RevisionSummary(TypedDict):
    id: str
    revision_number: int
    status: str
    author_name: str
    author_actor_type: str
    created_at: str
    content_hash: str


class SourceRevisions(TypedDict, total=False):
    """The revisions the current one was written from; empty when there is no current one."""

    info: str | None
    analysis_ai: str | None
    analysis: str | None
    roadmap_ai: str | None


class DocumentView(TypedDict):
    loop_id: str
    kind: str
    state: str
    current_revision_id: str | None
    current_revision_number: int | None
    current_content: str | None
    current_payload: JsonValue
    current_created_at: str | None
    approved_revision_id: str | None
    approved_revision_number: int | None
    approved_content: str | None
    source_revisions: SourceRevisions
    stale: bool
    stale_reasons: list[str]
    revisions: list[RevisionSummary]


class ApprovalEntry(TypedDict):
    """A decision as the documents route returns it: every column of its row."""

    id: str
    loop_id: str
    scope: str
    decision: str
    reviewer_actor_id: str
    reviewer_name: str
    feedback: str
    revisions_json: str
    source_hashes_json: str
    loop_version: int
    superseded_at: str | None
    created_at: str


class DocumentsView(TypedDict):
    loop_id: str
    loop_version: int
    documents: dict[str, DocumentView]
    approvals: dict[str, ApprovalEntry]


class RevisionEntry(TypedDict):
    """A revision in the history: its columns with the payload parsed."""

    id: str
    loop_id: str
    kind: str
    revision_number: int
    content: str
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
    payload: JsonValue


class Review(TypedDict):
    """A decision as the review route returns it: its row with the revisions and hashes parsed."""

    id: str
    loop_id: str
    scope: str
    decision: str
    reviewer_actor_id: str
    reviewer_name: str
    feedback: str
    loop_version: int
    superseded_at: str | None
    created_at: str
    revisions: JsonValue
    source_hashes: JsonValue


class ResetResult(TypedDict):
    scope: str
    approval_id: str | None
    cleared: list[str]
    version: int


class ContextDocument(TypedDict):
    revision_id: str
    revision_number: int
    content: str
    payload: JsonValue


class ContextTicket(TypedDict):
    id: str
    key: str
    title: str
    completed_at: str | None
    ready: bool
    human_action_required: bool


class ContextPhase(TypedDict):
    id: str
    number: int
    name: str
    objective: str
    state: str
    tickets: list[ContextTicket]


class ContextPlan(TypedDict):
    plan_id: str | None
    revision_number: int | None
    phases: list[ContextPhase]


class LoopContext(TypedDict):
    """Bounded, versioned context for a generation run or an external agent."""

    loop_id: str
    loop_key: str
    loop_name: str
    goal: str
    stage: str
    documents: dict[str, ContextDocument | None]
    plan: ContextPlan
    schemas: NotRequired[dict[str, JsonValue]]


class GeneratedAnalysis(TypedDict):
    analysis_ai: str
    analysis: str


class GeneratedRoadmap(TypedDict):
    plan_id: str
    roadmap_ai: str
    roadmap: str


def document_payload(row: LoopDocumentsRow | None) -> JsonValue:
    """The revision's structured payload; none, or text that is not JSON, reads as None."""
    if row is None or not row.payload_json:
        return None
    try:
        value: JsonValue = json.loads(row.payload_json)
    except (TypeError, ValueError):
        return None
    return value


def revision_summary(row: LoopDocumentsRow) -> RevisionSummary:
    return {
        "id": row.id,
        "revision_number": row.revision_number,
        "status": row.status,
        "author_name": row.author_name,
        "author_actor_type": row.author_actor_type,
        "created_at": row.created_at,
        "content_hash": row.content_hash,
    }


def revision_entry(row: LoopDocumentsRow) -> RevisionEntry:
    return {
        "id": row.id,
        "loop_id": row.loop_id,
        "kind": row.kind,
        "revision_number": row.revision_number,
        "content": row.content,
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
        "payload": document_payload(row),
    }


def approval_entry(row: LoopApprovalsRow) -> ApprovalEntry:
    return {
        "id": row.id,
        "loop_id": row.loop_id,
        "scope": row.scope,
        "decision": row.decision,
        "reviewer_actor_id": row.reviewer_actor_id,
        "reviewer_name": row.reviewer_name,
        "feedback": row.feedback,
        "revisions_json": row.revisions_json,
        "source_hashes_json": row.source_hashes_json,
        "loop_version": row.loop_version,
        "superseded_at": row.superseded_at,
        "created_at": row.created_at,
    }


def _parsed(raw: str) -> JsonValue:
    """A stored JSON column; an empty one reads as an empty object."""
    value: JsonValue = json.loads(raw or "{}")
    return value


def review_entry(row: LoopApprovalsRow) -> Review:
    return {
        "id": row.id,
        "loop_id": row.loop_id,
        "scope": row.scope,
        "decision": row.decision,
        "reviewer_actor_id": row.reviewer_actor_id,
        "reviewer_name": row.reviewer_name,
        "feedback": row.feedback,
        "loop_version": row.loop_version,
        "superseded_at": row.superseded_at,
        "created_at": row.created_at,
        "revisions": _parsed(row.revisions_json),
        "source_hashes": _parsed(row.source_hashes_json),
    }


def document_view(
    loop_id: str,
    kind: str,
    documents: DocumentSlots,
    approvals: Approvals,
    stale: StaleReasons,
    history: list[LoopDocumentsRow],
) -> DocumentView:
    """A document kind's state, its current and approved revision, and its latest revisions."""
    state = document_state(kind, documents, approvals, stale)
    current = documents[kind].current
    approved = documents[kind].approved
    sources: SourceRevisions = {}
    if current is not None:
        sources = {
            "info": current.source_info_revision_id,
            "analysis_ai": current.source_analysis_ai_revision_id,
            "analysis": current.source_analysis_revision_id,
            "roadmap_ai": current.source_roadmap_ai_revision_id,
        }
    return {
        "loop_id": loop_id,
        "kind": kind,
        "state": state["state"],
        "current_revision_id": current.id if current else None,
        "current_revision_number": current.revision_number if current else None,
        "current_content": current.content if current else None,
        "current_payload": document_payload(current),
        "current_created_at": current.created_at if current else None,
        "approved_revision_id": approved.id if approved else None,
        "approved_revision_number": approved.revision_number if approved else None,
        "approved_content": approved.content if approved else None,
        "source_revisions": sources,
        "stale": state["state"] == "stale",
        "stale_reasons": state["stale_reasons"],
        "revisions": [revision_summary(row) for row in history],
    }


def validate_analysis(payload: AnalysisPayload) -> None:
    missing = [
        finding.id
        for finding in payload.findings
        if finding.category in MATERIAL_FINDING_CATEGORIES and not finding.plain_language.strip()
    ]
    if missing:
        raise ValidationFailure(
            "Material findings need a plain-language explanation",
            code="validation_failed",
            details={"finding_ids": missing},
        )


def expected_revisions(documents: DocumentSlots, scope: str) -> dict[str, str]:
    """The current revision of every kind the scope's decision binds to."""
    kinds = ANALYSIS_SCOPE_KINDS if scope == "analysis" else ROADMAP_SCOPE_KINDS
    expected: dict[str, str] = {}
    for kind in kinds:
        current = documents[kind].current
        if current is None:
            raise Conflict(
                f"{kind.replace('_', ' ').title()} is missing",
                code="document_stale",
                details={"missing": kind},
            )
        expected[kind] = current.id
    return expected


def registered_plan(roadmap_ai: LoopDocumentsRow) -> str:
    """The plan a RoadMap revision registered (its provenance names it), or ``409
    plan_change_required``. Provenance that is not a JSON object raises the ``AttributeError``
    reading a key from it always raised; a plan id that is not text names no plan."""
    provenance: JsonValue = json.loads(roadmap_ai.provenance_json or "{}")
    if not isinstance(provenance, dict):
        raise AttributeError(f"the provenance is a {type(provenance).__name__}")  # noqa: TRY004
    plan_id = provenance.get("plan_id")
    if not plan_id or not isinstance(plan_id, str):
        raise Conflict("The RoadMap revision has no registered plan", code="plan_change_required")
    return plan_id


def _current_id(documents: DocumentSlots, kind: str) -> str | None:
    current = documents[kind].current
    return current.id if current else None


def _has_text(row: LoopDocumentsRow | None) -> bool:
    return row is not None and bool(row.content.strip())


def _content_hash(row: LoopDocumentsRow | None) -> str | None:
    return row.content_hash if row else None


def _check_version(loop: LoopsRow, expected: int) -> None:
    if loop.version != expected:
        raise VersionConflict(
            "Loop was modified by another actor",
            details={"expected_version": expected, "current_version": loop.version},
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class LoopDocumentService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        plans: LoopPlanService,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self.plans = plans
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    # --- reads -----------------------------------------------------------------------------------

    def documents(self, board_id: str, loop_id: str) -> DocumentsView:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            loop = require_loop(repos, loop_id)
            documents = document_slots(repos.documents.current_or_approved(loop_id))
            approvals = latest_approvals(repos.approvals.newest_first(loop_id))
            stale = stale_reasons(documents, approvals)
            return {
                "loop_id": loop_id,
                "loop_version": loop.version,
                "documents": {
                    kind: document_view(
                        loop_id,
                        kind,
                        documents,
                        approvals,
                        stale,
                        repos.documents.page(loop_id, kind, limit=20, offset=0),
                    )
                    for kind in DOCUMENT_KINDS
                },
                "approvals": {
                    scope: approval_entry(approval) for scope, approval in approvals.items()
                },
            }

    def revision_history(
        self, board_id: str, loop_id: str, kind: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[RevisionEntry], int]:
        if kind not in DOCUMENT_KINDS:
            raise ValidationFailure(
                "Unknown document kind",
                details={"allowed": list(DOCUMENT_KINDS)},
            )
        with self.store.reader(board_id) as repos:
            require_loop(repos, loop_id)
            total = repos.documents.count(loop_id, kind)
            records = repos.documents.page(loop_id, kind, limit=limit, offset=offset)
        return [revision_entry(record) for record in records], total

    def context(self, board_id: str, loop_id: str) -> LoopContext:
        """Versioned context for external agents; never contains credentials or other Loops."""
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            context = self.collect_context(repos, require_loop(repos, loop_id))
        context["schemas"] = {
            "analysis": AnalysisPayload.model_json_schema(),
            "roadmap": PlanPayload.model_json_schema(),
            "qa": QaInstructions.model_json_schema(),
        }
        return context

    def collect_context(self, repos: BoardRepositories, loop: LoopsRow) -> LoopContext:
        """Bounded, versioned context for a generation run or an external agent."""
        documents = document_slots(repos.documents.current_or_approved(loop.id))
        context_documents: dict[str, ContextDocument | None] = {}
        for kind in DOCUMENT_KINDS:
            current = documents[kind].current
            context_documents[kind] = (
                {
                    "revision_id": current.id,
                    "revision_number": current.revision_number,
                    "content": current.content,
                    "payload": document_payload(current),
                }
                if current
                else None
            )
        plan = self.plans.plan_view(repos, loop)
        return {
            "loop_id": loop.id,
            "loop_key": loop.key,
            "loop_name": loop.name,
            "goal": loop.goal,
            "stage": loop.stage,
            "documents": context_documents,
            "plan": {
                "plan_id": plan["plan_id"],
                "revision_number": plan["revision_number"],
                "phases": [
                    {
                        "id": phase["id"],
                        "number": phase["number"],
                        "name": phase["name"],
                        "objective": phase["objective"],
                        "state": phase["state"],
                        "tickets": [
                            {
                                "id": ticket["id"],
                                "key": ticket["key"],
                                "title": ticket["title"],
                                "completed_at": ticket["completed_at"],
                                "ready": ticket["ready"],
                                "human_action_required": ticket["human_action_required"],
                            }
                            for ticket in phase["tickets"]
                        ],
                    }
                    for phase in plan["phases"]
                ],
            },
        }

    # --- writing revisions -----------------------------------------------------------------------

    def _write_revision(
        self,
        repos: BoardRepositories,
        *,
        loop_id: str,
        kind: str,
        content: str,
        payload: Mapping[str, object] | None,
        actor: ActorContext,
        status: str = "ready_for_review",
        sources: Mapping[str, str | None] | None = None,
        generation_run_id: str | None = None,
        provenance: Mapping[str, object] | None = None,
    ) -> LoopDocumentsRow:
        """The kind's new current revision; no revision of the kind is approved any more."""
        if payload is not None:
            encoded = json.dumps(payload)
            if len(encoded) > MAX_DOCUMENT_PAYLOAD:
                raise ValidationFailure(
                    "Generated document exceeds the configured size limit",
                    code="payload_too_large",
                    details={"limit": MAX_DOCUMENT_PAYLOAD},
                )
        now = self._now()
        revision = repos.documents.next_revision(loop_id, kind)
        document_id = self._new_id()
        repos.documents.clear_current(loop_id, kind)
        repos.documents.withdraw_approval(loop_id, kind)
        sources = sources or {}
        structured = json.dumps(payload, sort_keys=True) if payload else ""
        row = LoopDocumentsRow(
            id=document_id,
            loop_id=loop_id,
            kind=kind,
            revision_number=revision,
            content=content,
            payload_json=json.dumps(payload) if payload is not None else None,
            content_hash=content_hash(content + structured),
            status=status,
            source_info_revision_id=sources.get("info"),
            source_analysis_ai_revision_id=sources.get("analysis_ai"),
            source_analysis_revision_id=sources.get("analysis"),
            source_roadmap_ai_revision_id=sources.get("roadmap_ai"),
            generation_run_id=generation_run_id,
            author_actor_id=actor.actor_id,
            author_actor_type=actor.actor_type,
            author_name=actor.actor_name,
            provenance_json=json.dumps(provenance or {}),
            is_current=1,
            is_approved=0,
            created_at=now,
        )
        repos.documents.add(row)
        return row

    def _invalidate_downstream(self, repos: BoardRepositories, loop_id: str, kind: str) -> None:
        """A changed input invalidates the approvals that authorized execution."""
        cleared = _CLEARED_APPROVALS.get(kind)
        if cleared is None:
            return
        repos.loops.clear_approvals(loop_id, cleared, now=self._now())
        for stale_kind in _STALE_KINDS.get(kind, ()):
            repos.documents.withdraw_approval(loop_id, stale_kind)
        repos.qa.supersede_open(loop_id, now=self._now())

    def save_info(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: InfoRevisionWrite
    ) -> DocumentsView:
        actor.require("loops:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            if not actor.is_user and loop.stage not in WORKER_INFO_STAGES:
                raise Forbidden(
                    "Info is a person's decision once the Loop is being planned",
                    code="human_action_required",
                    details={"stage": loop.stage, "action": "Editing Loop Info"},
                )
            current = repos.documents.current(loop_id, "info")
            if payload.expected_revision_id is not None and (
                current is None or current.id != payload.expected_revision_id
            ):
                raise VersionConflict(
                    "Info changed since it was loaded",
                    code="document_stale",
                    details={
                        "expected_revision_id": payload.expected_revision_id,
                        "current_revision_id": current.id if current else None,
                    },
                )
            document = self._write_revision(
                repos,
                loop_id=loop_id,
                kind="info",
                content=payload.content,
                payload=None,
                actor=actor,
                status="ready_for_review",
                sources={},
                provenance={"note": payload.note},
            )
            self._invalidate_downstream(repos, loop_id, "info")
            self._log(
                repos, actor, "loop.info_revised", loop_id, {"revision": document.revision_number}
            )
            refresh_stage(repos, loop_id, now=self._now())
        return self.documents(board_id, loop_id)

    def submit_candidate(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: CandidateSubmission
    ) -> DocumentsView:
        actor.require("loops:generate")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            if payload.kind == "analysis":
                if payload.analysis is None:
                    raise ValidationFailure("An analysis candidate needs an analysis payload")
                self._store_analysis(repos, loop, payload.analysis, actor, payload)
            else:
                if payload.plan is None:
                    raise ValidationFailure("A RoadMap candidate needs a plan payload")
                self._store_roadmap(repos, loop, payload.plan, actor, payload)
            refresh_stage(repos, loop_id, now=self._now())
        return self.documents(board_id, loop_id)

    def _store_analysis(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: AnalysisPayload,
        actor: ActorContext,
        submission: CandidateSubmission,
    ) -> None:
        validate_analysis(payload)
        info = repos.documents.current(loop.id, "info")
        if info is None and not submission.source_info_revision_id:
            raise Conflict(
                "Analysis needs a current Info revision from a human",
                code="document_stale",
                details={"missing": "info"},
            )
        info_id = info.id if info else submission.source_info_revision_id
        technical = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="analysis_ai",
            content=render_analysis_technical(payload),
            payload=payload.model_dump(),
            actor=actor,
            sources={"info": info_id},
            provenance={"submitted": True, **submission.provenance},
        )
        human = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="analysis",
            content=render_analysis(payload),
            payload=None,
            actor=actor,
            sources={"analysis_ai": technical.id, "info": info_id},
            provenance={"submitted": True, **submission.provenance},
        )
        self._invalidate_downstream(repos, loop.id, "analysis_ai")
        self._log(
            repos,
            actor,
            "loop.analysis_candidate",
            loop.id,
            {
                "analysis_ai_revision": technical.revision_number,
                "analysis_revision": human.revision_number,
            },
        )

    def _store_roadmap(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: PlanPayload,
        actor: ActorContext,
        submission: CandidateSubmission,
    ) -> None:
        documents = document_slots(repos.documents.current_or_approved(loop.id))
        approvals = latest_approvals(repos.approvals.newest_first(loop.id))
        stale = stale_reasons(documents, approvals)
        if not analysis_approved(documents, approvals, stale):
            raise Conflict(
                "RoadMap generation requires a current approved analysis",
                code="approval_required",
                details={"scope": "analysis"},
            )
        draft = self.plans.register_draft(repos, loop, payload, actor)
        canonical = draft["payload"]
        technical = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="roadmap_ai",
            content=render_roadmap_technical(canonical),
            payload=canonical,
            actor=actor,
            sources={
                "info": _current_id(documents, "info"),
                "analysis_ai": _current_id(documents, "analysis_ai"),
                "analysis": _current_id(documents, "analysis"),
            },
            provenance={"plan_id": draft["plan_id"], **submission.provenance},
        )
        human = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="roadmap",
            content=render_roadmap(canonical),
            payload=None,
            actor=actor,
            sources={"roadmap_ai": technical.id},
            provenance={"plan_id": draft["plan_id"], **submission.provenance},
        )
        self.plans.attach_revisions(
            repos,
            draft["plan_id"],
            roadmap_ai_revision_id=technical.id,
            roadmap_revision_id=human.id,
        )
        self._invalidate_downstream(repos, loop.id, "roadmap_ai")
        self._log(
            repos,
            actor,
            "loop.roadmap_candidate",
            loop.id,
            {"plan_id": draft["plan_id"], "phases": len(canonical["phases"])},
        )

    # --- approvals -------------------------------------------------------------------------------

    def review(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        scope: str,
        payload: ApprovalRequest,
    ) -> Review:
        actor.require_human(
            "Approving an analysis" if scope == "analysis" else "Approving a RoadMap"
        )
        actor.require("loops:review")
        if scope not in {"analysis", "roadmap"}:
            raise ValidationFailure(
                "Unknown review scope", details={"allowed": ["analysis", "roadmap"]}
            )
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            _check_version(loop, payload.version)
            documents = document_slots(repos.documents.current_or_approved(loop_id))
            expected = expected_revisions(documents, scope)
            for kind in expected:
                current = documents[kind].current
                blank = current is not None and not (current.content or "").strip()
                if kind != "info" and blank:
                    # Text can be withdrawn or cleared; saying "approved" to nothing would let
                    # delivery start from an empty document.
                    raise Conflict(
                        "There is nothing to approve; generate the document first",
                        code="document_empty",
                        details={"kind": kind},
                    )
            if payload.revisions:
                for kind, revision_id in payload.revisions.items():
                    if kind not in expected:
                        raise ValidationFailure(
                            "Review references a document outside its scope",
                            details={"kind": kind},
                        )
                    if expected[kind] != revision_id:
                        raise Conflict(
                            "The document changed after you reviewed it",
                            code="document_stale",
                            details={"kind": kind, "expected": expected[kind]},
                        )
            approval_id = self._record_approval(
                repos,
                loop_id=loop_id,
                scope=scope,
                decision=payload.decision,
                actor=actor,
                revisions=expected,
                documents=documents,
                loop_version=loop.version,
                feedback=payload.feedback,
            )
            reviewed = [kind for kind in expected if kind != "info"]
            if payload.decision == "approved":
                for kind in reviewed:
                    repos.documents.approve(expected[kind])
                column: ApprovalColumn = (
                    "analysis_approval_id" if scope == "analysis" else "roadmap_approval_id"
                )
                repos.loops.set_approval(loop_id, column, approval_id, now=self._now())
                roadmap_ai = documents["roadmap_ai"].current
                if scope == "roadmap" and roadmap_ai is not None:
                    plan_id = registered_plan(roadmap_ai)
                    self.plans.publish(repos, loop, plan_id, actor, approval_id=approval_id)
            else:
                for kind in reviewed:
                    repos.documents.request_changes(expected[kind])
            self._log(
                repos,
                actor,
                f"loop.{scope}_reviewed",
                loop_id,
                {"decision": payload.decision, "approval_id": approval_id},
            )
            refresh_stage(repos, loop_id, now=self._now())
            approval = repos.approvals.get(approval_id)
            if approval is None:  # pragma: no cover - written above, in this transaction
                raise RuntimeError("the approval just recorded is missing")
            return review_entry(approval)

    def reset(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        scope: str,
        payload: ScopeResetRequest,
    ) -> ResetResult:
        """Clear a scope's documents and drop any approval that stood behind them.

        This is not a rejection: a rejection asks for changes and keeps the text. A reset is the
        person saying "start over", so it works on a draft that was never approved as well as on an
        approved one — the approval row stays as history but is superseded, and both documents of
        the scope are emptied so nothing downstream can execute against text nobody stands behind.
        A reset is a human decision and rejects agent tokens for the same reason an approval does.
        """
        actor.require_human(
            "Resetting the analysis" if scope == "analysis" else "Resetting the RoadMap"
        )
        actor.require("loops:review")
        if scope not in REVIEW_SCOPES:
            raise ValidationFailure(
                "Unknown review scope", details={"allowed": list(REVIEW_SCOPES)}
            )
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            _check_version(loop, payload.version)
            approval = latest_approvals(repos.approvals.newest_first(loop_id)).get(scope)
            approved = approval is not None and approval.decision == "approved"
            documents = document_slots(repos.documents.current_or_approved(loop_id))
            technical_kind, human_kind = (
                ("analysis_ai", "analysis") if scope == "analysis" else ("roadmap_ai", "roadmap")
            )
            has_text = _has_text(documents[technical_kind].current) or _has_text(
                documents[human_kind].current
            )
            if not has_text and not approved:
                raise Conflict(
                    "There is nothing to reset in this scope",
                    code="nothing_to_reset",
                    details={"scope": scope},
                )
            approval_id = approval.id if approved and approval else None
            now = self._now()
            if approval_id:
                repos.approvals.supersede(approval_id, now=now)
            provenance = {"reset_by": actor.actor_id, "reset_approval_id": approval_id}
            # The cleared revisions chain to their inputs, so the scope reads as an ordinary draft
            # rather than as stale text that was left behind.
            if scope == "analysis":
                inputs = {"info": _current_id(documents, "info")}
            else:
                inputs = {
                    "info": _current_id(documents, "info"),
                    "analysis_ai": _current_id(documents, "analysis_ai"),
                    "analysis": _current_id(documents, "analysis"),
                }
            technical = self._write_revision(
                repos,
                loop_id=loop_id,
                kind=technical_kind,
                content="",
                payload=None,
                actor=actor,
                status="draft",
                sources=inputs,
                provenance=provenance,
            )
            self._write_revision(
                repos,
                loop_id=loop_id,
                kind=human_kind,
                content="",
                payload=None,
                actor=actor,
                status="draft",
                sources={technical_kind: technical.id},
                provenance=provenance,
            )
            cleared = [technical_kind, human_kind]
            self._invalidate_downstream(
                repos, loop_id, "analysis" if scope == "analysis" else "roadmap_ai"
            )
            repos.loops.bump_version(loop_id, now=now)
            self._log(
                repos,
                actor,
                f"loop.{scope}_reset",
                loop_id,
                {"approval_id": approval_id, "cleared": cleared},
            )
            refresh_stage(repos, loop_id, now=self._now())
            return {
                "scope": scope,
                "approval_id": approval_id,
                "cleared": cleared,
                "version": require_loop(repos, loop_id).version,
            }

    def _record_approval(
        self,
        repos: BoardRepositories,
        *,
        loop_id: str,
        scope: str,
        decision: str,
        actor: ActorContext,
        revisions: dict[str, str],
        documents: DocumentSlots,
        loop_version: int,
        feedback: str,
    ) -> str:
        """The decision, bound to the exact revisions and their hashes; it supersedes the scope's
        earlier decisions."""
        approval_id = self._new_id()
        hashes = {kind: _content_hash(documents[kind].current) for kind in revisions}
        repos.approvals.add(
            LoopApprovalsRow(
                id=approval_id,
                loop_id=loop_id,
                scope=scope,
                decision=decision,
                reviewer_actor_id=actor.actor_id,
                reviewer_name=actor.actor_name,
                feedback=feedback,
                revisions_json=json.dumps(revisions),
                source_hashes_json=json.dumps(hashes),
                loop_version=loop_version,
                superseded_at=None,
                created_at=self._now(),
            )
        )
        repos.approvals.supersede_others(loop_id, scope, keep=approval_id, now=self._now())
        return approval_id

    # --- generation results ----------------------------------------------------------------------

    def store_generated_analysis(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: AnalysisPayload,
        actor: ActorContext,
        *,
        run_id: str,
        provenance: Mapping[str, object],
    ) -> GeneratedAnalysis:
        validate_analysis(payload)
        info = repos.documents.current(loop.id, "info")
        if info is None:
            raise Conflict("Analysis needs a current Info revision", code="document_stale")
        technical = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="analysis_ai",
            content=render_analysis_technical(payload),
            payload=payload.model_dump(),
            actor=actor,
            sources={"info": info.id},
            generation_run_id=run_id,
            provenance=provenance,
        )
        human = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="analysis",
            content=render_analysis(payload),
            payload=None,
            actor=actor,
            sources={"analysis_ai": technical.id, "info": info.id},
            generation_run_id=run_id,
            provenance=provenance,
        )
        self._invalidate_downstream(repos, loop.id, "analysis_ai")
        refresh_stage(repos, loop.id, now=self._now())
        return {"analysis_ai": technical.id, "analysis": human.id}

    def store_generated_roadmap(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: PlanPayload,
        actor: ActorContext,
        *,
        run_id: str,
        provenance: Mapping[str, object],
    ) -> GeneratedRoadmap:
        documents = document_slots(repos.documents.current_or_approved(loop.id))
        approvals = latest_approvals(repos.approvals.newest_first(loop.id))
        stale = stale_reasons(documents, approvals)
        if not analysis_approved(documents, approvals, stale):
            raise Conflict(
                "RoadMap generation requires a current approved analysis",
                code="approval_required",
            )
        draft = self.plans.register_draft(repos, loop, payload, actor)
        canonical = draft["payload"]
        technical = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="roadmap_ai",
            content=render_roadmap_technical(canonical),
            payload=canonical,
            actor=actor,
            sources={
                "info": _current_id(documents, "info"),
                "analysis_ai": _current_id(documents, "analysis_ai"),
                "analysis": _current_id(documents, "analysis"),
            },
            generation_run_id=run_id,
            provenance={"plan_id": draft["plan_id"], **provenance},
        )
        human = self._write_revision(
            repos,
            loop_id=loop.id,
            kind="roadmap",
            content=render_roadmap(canonical),
            payload=None,
            actor=actor,
            sources={"roadmap_ai": technical.id},
            generation_run_id=run_id,
            provenance={"plan_id": draft["plan_id"], **provenance},
        )
        self.plans.attach_revisions(
            repos,
            draft["plan_id"],
            roadmap_ai_revision_id=technical.id,
            roadmap_revision_id=human.id,
        )
        self._invalidate_downstream(repos, loop.id, "roadmap_ai")
        refresh_stage(repos, loop.id, now=self._now())
        return {"plan_id": draft["plan_id"], "roadmap_ai": technical.id, "roadmap": human.id}

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        loop_id: str,
        changes: Mapping[str, object],
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="loop",
                entity_id=loop_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=self._now(),
            )
        )


__all__ = [
    "LoopDocumentService",
    "content_hash",
    "render_analysis",
    "render_analysis_technical",
    "render_roadmap",
]
