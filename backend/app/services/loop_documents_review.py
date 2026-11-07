"""A person's decision on a scope: approving it, requesting changes, or resetting it.

A decision binds to the exact revisions of its scope and their hashes. Approving a RoadMap publishes
the plan its revision registered; a reset supersedes the approval and replaces both documents of the
scope with an empty draft. Authorization stays with ``LoopDocumentService``: these functions run
inside its unit of work, with its clock and id source.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import Conflict, ValidationFailure, VersionConflict
from ..db.generated.board import LoopApprovalsRow, LoopDocumentsRow, LoopsRow
from ..repositories.board import BoardRepositories
from ..repositories.loops import ApprovalColumn
from ..schemas.loops import ApprovalRequest, ScopeResetRequest
from .loop_documents_revisions import (
    current_id,
    invalidate_downstream,
    log_loop_activity,
    write_revision,
)
from .loop_documents_views import ResetResult, Review, review_entry
from .loop_plans import LoopPlanService
from .loops import (
    DocumentSlots,
    document_slots,
    ensure_writable,
    latest_approvals,
    refresh_stage,
    require_loop,
)

ANALYSIS_SCOPE_KINDS = ("info", "analysis_ai", "analysis")
ROADMAP_SCOPE_KINDS = ("info", "analysis_ai", "analysis", "roadmap_ai", "roadmap")
REVIEW_SCOPES = ("analysis", "roadmap")


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


def record_review(
    repos: BoardRepositories,
    actor: ActorContext,
    loop_id: str,
    scope: str,
    payload: ApprovalRequest,
    *,
    plans: LoopPlanService,
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> Review:
    loop = require_loop(repos, loop_id)
    ensure_writable(loop)
    _check_version(loop, payload.version)
    purpose = f"{scope}_human"
    writing = repos.generation_runs.active(loop_id, purpose)
    if writing is not None:
        # The text a person would approve is about to be replaced by the brief written for them.
        what = "analysis" if scope == "analysis" else "RoadMap"
        raise Conflict(
            f"A board agent is writing the {what} for people; approve it when the run has ended",
            code="generation_in_progress",
            details={"purpose": purpose, "run_id": writing.id},
        )
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
    approval_id = record_approval(
        repos,
        clock=clock,
        new_id=new_id,
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
        repos.loops.set_approval(loop_id, column, approval_id, now=clock())
        roadmap_ai = documents["roadmap_ai"].current
        if scope == "roadmap" and roadmap_ai is not None:
            plan_id = registered_plan(roadmap_ai)
            plans.publish(repos, loop, plan_id, actor, approval_id=approval_id)
    else:
        for kind in reviewed:
            repos.documents.request_changes(expected[kind])
    log_loop_activity(
        repos,
        actor,
        f"loop.{scope}_reviewed",
        loop_id,
        {"decision": payload.decision, "approval_id": approval_id},
        clock=clock,
        new_id=new_id,
    )
    refresh_stage(repos, loop_id, now=clock())
    approval = repos.approvals.get(approval_id)
    if approval is None:  # pragma: no cover - written above, in this transaction
        raise RuntimeError("the approval just recorded is missing")
    return review_entry(approval)


def reset_scope(
    repos: BoardRepositories,
    actor: ActorContext,
    loop_id: str,
    scope: str,
    payload: ScopeResetRequest,
    *,
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> ResetResult:
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
    now = clock()
    if approval_id:
        repos.approvals.supersede(approval_id, now=now)
    provenance = {"reset_by": actor.actor_id, "reset_approval_id": approval_id}
    # The cleared revisions chain to their inputs, so the scope reads as an ordinary draft
    # rather than as stale text that was left behind.
    if scope == "analysis":
        inputs = {"info": current_id(documents, "info")}
    else:
        inputs = {
            "info": current_id(documents, "info"),
            "analysis_ai": current_id(documents, "analysis_ai"),
            "analysis": current_id(documents, "analysis"),
        }
    technical = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop_id,
        kind=technical_kind,
        content="",
        payload=None,
        actor=actor,
        status="draft",
        sources=inputs,
        provenance=provenance,
    )
    write_revision(
        repos,
        clock=clock,
        new_id=new_id,
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
    invalidate_downstream(
        repos, loop_id, "analysis" if scope == "analysis" else "roadmap_ai", clock=clock
    )
    repos.loops.bump_version(loop_id, now=now)
    log_loop_activity(
        repos,
        actor,
        f"loop.{scope}_reset",
        loop_id,
        {"approval_id": approval_id, "cleared": cleared},
        clock=clock,
        new_id=new_id,
    )
    refresh_stage(repos, loop_id, now=clock())
    return {
        "scope": scope,
        "approval_id": approval_id,
        "cleared": cleared,
        "version": require_loop(repos, loop_id).version,
    }


def record_approval(
    repos: BoardRepositories,
    *,
    clock: Callable[[], str],
    new_id: Callable[[], str],
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
    approval_id = new_id()
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
            created_at=clock(),
        )
    )
    repos.approvals.supersede_others(loop_id, scope, keep=approval_id, now=clock())
    return approval_id


__all__ = [
    "ANALYSIS_SCOPE_KINDS",
    "REVIEW_SCOPES",
    "ROADMAP_SCOPE_KINDS",
    "expected_revisions",
    "record_approval",
    "record_review",
    "registered_plan",
    "reset_scope",
]
