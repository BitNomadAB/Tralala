"""The JSON the Loop document routes return, built from the stored rows."""

from __future__ import annotations

import json
from typing import NotRequired, TypedDict

from pydantic import JsonValue

from ..db.generated.board import LoopApprovalsRow, LoopDocumentsRow
from .loops import Approvals, DocumentSlots, StaleReasons, document_state


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


__all__ = [
    "ApprovalEntry",
    "ContextDocument",
    "ContextPhase",
    "ContextPlan",
    "ContextTicket",
    "DocumentView",
    "DocumentsView",
    "GeneratedAnalysis",
    "GeneratedRoadmap",
    "LoopContext",
    "ResetResult",
    "Review",
    "RevisionEntry",
    "RevisionSummary",
    "SourceRevisions",
    "approval_entry",
    "document_payload",
    "document_view",
    "review_entry",
    "revision_entry",
    "revision_summary",
]
