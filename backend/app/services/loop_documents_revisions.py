"""Writing a Loop document revision, what a changed document invalidates, and the activity entry.

Revisions are immutable: a new one becomes the kind's current revision and no revision of the kind
stays approved. The functions take the board repositories of the caller's unit of work, the clock
and the id source, so the service that owns them decides the transaction.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..db.generated.board import LoopDocumentsRow
from ..repositories.board import BoardRepositories
from ..repositories.loops import LOOP_APPROVAL_COLUMNS, ApprovalColumn
from .activity import activity_entry
from .loop_documents_render import content_hash
from .loops import DocumentSlots

MAX_DOCUMENT_PAYLOAD = 200_000

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


def current_id(documents: DocumentSlots, kind: str) -> str | None:
    current = documents[kind].current
    return current.id if current else None


def write_revision(
    repos: BoardRepositories,
    *,
    clock: Callable[[], str],
    new_id: Callable[[], str],
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
    now = clock()
    revision = repos.documents.next_revision(loop_id, kind)
    document_id = new_id()
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


def invalidate_downstream(
    repos: BoardRepositories, loop_id: str, kind: str, *, clock: Callable[[], str]
) -> None:
    """A changed input invalidates the approvals that authorized execution."""
    cleared = _CLEARED_APPROVALS.get(kind)
    if cleared is None:
        return
    repos.loops.clear_approvals(loop_id, cleared, now=clock())
    for stale_kind in _STALE_KINDS.get(kind, ()):
        repos.documents.withdraw_approval(loop_id, stale_kind)
    repos.qa.supersede_open(loop_id, now=clock())


def log_loop_activity(
    repos: BoardRepositories,
    actor: ActorContext,
    action: str,
    loop_id: str,
    changes: Mapping[str, object],
    *,
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> None:
    repos.activity.add(
        activity_entry(
            actor,
            action=action,
            entity_type="loop",
            entity_id=loop_id,
            changes=changes,
            entry_id=new_id(),
            timestamp=clock(),
        )
    )


__all__ = [
    "MAX_DOCUMENT_PAYLOAD",
    "current_id",
    "invalidate_downstream",
    "log_loop_activity",
    "write_revision",
]
