"""The documents, approvals and stage of a Loop.

Pure functions over typed rows: which revision of each document kind is current and which is
approved, which decision of each review scope still counts, why a document no longer matches its
inputs, the stage that follows from them, and a document's state as the API returns it. ``loops``
re-exports every name here, so callers keep importing them from there.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypedDict

from pydantic import JsonValue

from ..db.generated.board import LoopApprovalsRow, LoopDocumentsRow, LoopsRow
from ..schemas.loops import DOCUMENT_KINDS, LOOP_STAGES

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


# --- a document's state --------------------------------------------------------------------------


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
    """The document's state for a person and an agent. A revision written after its scope was
    approved (``approval_superseded`` alone, such as a RoadMap written again) waits for a new
    review instead of counting as stale: it is reviewed as it is, while a changed input means
    writing it again. The reasons stay listed either way."""
    current = documents[kind].current
    approved = documents[kind].approved
    reasons = list(stale.get(kind, []))
    if current is None:
        state = "empty"
    elif any(reason != "approval_superseded" for reason in reasons):
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
