"""The rules every Loop service shares.

A Loop that exists, one that may still change, a Ticket whose Loop may still change, a stage that
lets delivery work start, the stage kept in step with the Loop's documents, approvals, plan and
Tickets, and the planned Ticket behind a card. ``loops`` re-exports every name here, so
``CardService`` and the Loop workflow services keep importing them from there.
"""

from __future__ import annotations

from ..core.errors import Conflict, NotFound
from ..db.generated.board import LoopsRow
from ..repositories.board import BoardRepositories
from .loops_stage import (
    EXECUTION_STAGES,
    compute_stage,
    document_slots,
    latest_approvals,
    stale_reasons,
)
from .plan_views import Readiness, ReadinessItem

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


def ensure_ticket_writable(repos: BoardRepositories, card_id: str) -> None:
    """A Ticket's comments, checklists and attachments follow its Loop: a completed, archived or
    cancelled Loop refuses them (``409 loop_read_only``). A Ticket or Loop that does not exist
    passes; the caller answers its own 404."""
    card = repos.cards.get(card_id)
    loop = None if card is None else repos.loops.get(card.loop_id)
    if loop is None:
        return
    if (
        loop.completed_at is not None
        or loop.stage == "completed"
        or loop.archived_at is not None
        or loop.cancelled_at is not None
    ):
        raise Conflict(
            "This Loop is read-only", code="loop_read_only", details={"card_id": card_id}
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


def readiness_item(readiness: Readiness, card_id: str) -> ReadinessItem | None:
    """The planned Ticket behind ``card_id``, or None for a card outside the plan."""
    for item in readiness["items"]:
        if item["card_id"] == card_id:
            return item
    return None
