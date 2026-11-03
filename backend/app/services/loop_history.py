"""Immutable Board-local Loop history and the future legacy-import envelope.

Completing a Loop stores a self-contained, hashed snapshot in the owning Board database. Nothing
here writes Markdown into the project repository, and nothing converts imported legacy material
into active Loops.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from typing import Protocol, TypeGuard
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound
from ..db.generated.board import (
    IdempotencyRecordsRow,
    LoopGenerationRunsRow,
    LoopHistoryArtifactsRow,
    LoopHistoryRow,
    LoopsRow,
)
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.board_files import AttachmentFiles
from ..repositories.loop_history import HistoryQuery
from ..repositories.search import FullTextIndex
from ..schemas.loops import LegacyImportRequest
from .activity import activity_entry
from .attachments import attachment_path

HISTORY_SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_TOTAL = 20 * 1024 * 1024
LEGACY_LABEL = "Imported legacy reference - may not follow the current standard"
MAX_SEARCH_TEXT = 200_000

Envelope = dict[str, object]
"""A history snapshot as JSON."""

HistoryEntry = dict[str, object]
"""A stored snapshot as the API answers it."""


class BoardChecks(Protocol):
    def require_row(self, board_id: str) -> object: ...

    def ensure_active(self, board_id: str) -> object: ...


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _prompt_digest(role_snapshot_json: str | None) -> str | None:
    try:
        snapshot: object = json.loads(role_snapshot_json or "{}")
    except ValueError:
        return None
    prompt = snapshot.get("system_prompt") if _is_object(snapshot) else None
    if not isinstance(prompt, str) or not prompt:
        return None
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def generation_provenance(runs: Sequence[LoopGenerationRunsRow]) -> list[dict[str, object]]:
    """Prove which agent and instructions produced a document without handing over the prompt."""
    return [
        {
            "run_id": run.id,
            "purpose": run.purpose,
            "status": run.status,
            "agent_id": run.agent_id,
            "agent_name": run.agent_name,
            "model": run.model,
            "system_prompt_sha256": _prompt_digest(run.role_snapshot_json),
            "usage": json.loads(run.usage_json or "{}"),
            "created_at": run.created_at,
            "finished_at": run.finished_at,
            "error_code": run.error_code,
        }
        for run in runs
    ]


def canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fts_query(value: str) -> str:
    tokens = [token.replace('"', " ") for token in value.split() if token.strip()]
    return " AND ".join(f'"{token}"*' for token in tokens)


def snapshot(
    repos: BoardRepositories, loop: LoopsRow, *, board_id: str | None, completed_at: str
) -> tuple[Envelope, str, list[dict[str, object]]]:
    """A completed Loop as its history records it, the text its search reads, and the asset
    manifest inside it (finalization marks which files it embedded)."""
    loop_id = loop.id
    archive = repos.archive
    documents = archive.documents(loop_id)
    approvals = archive.approvals(loop_id)
    plans = archive.plans(loop_id)
    phases = archive.phases(loop_id)
    items = archive.plan_items(loop_id)
    dependencies = archive.dependencies(loop_id)
    cards = archive.tickets(loop_id)
    comments = archive.comments(loop_id)
    checklists = archive.checklist_lines(loop_id)
    qa_cycles = archive.qa_cycles(loop_id)
    qa_results = archive.qa_results(loop_id)
    runs = archive.generation_runs(loop_id)
    activity = archive.activity(loop_id)
    attachments = archive.attachments(loop_id)
    labels = repos.cards.labels([card.id for card in cards]) if cards else {}

    document_entries: list[dict[str, object]] = [
        {
            "kind": record.kind,
            "revision_id": record.id,
            "revision_number": record.revision_number,
            "content": record.content,
            "payload": json.loads(record.payload_json) if record.payload_json else None,
            "content_hash": record.content_hash,
            "is_approved": bool(record.is_approved),
            "author_name": record.author_name,
            "author_actor_type": record.author_actor_type,
            "created_at": record.created_at,
        }
        for record in documents
    ]
    decisions: list[dict[str, object]] = [
        {
            "id": approval.id,
            "scope": approval.scope,
            "decision": approval.decision,
            "reviewer_actor_id": approval.reviewer_actor_id,
            "reviewer_name": approval.reviewer_name,
            "feedback": approval.feedback,
            "revisions": json.loads(approval.revisions_json or "{}"),
            "source_hashes": json.loads(approval.source_hashes_json or "{}"),
            "created_at": approval.created_at,
        }
        for approval in approvals
    ]
    cycles: list[dict[str, object]] = [
        {
            "id": cycle.id,
            "cycle_number": cycle.cycle_number,
            "status": cycle.status,
            "instruction_revision": cycle.instruction_revision,
            "ai_instructions": json.loads(cycle.ai_instructions_json or "{}"),
            "human_instructions": json.loads(cycle.human_instructions_json or "{}"),
            "attestation": json.loads(cycle.attestation_json or "{}"),
            "decided_at": cycle.decided_at,
            "decided_by_actor_id": cycle.decided_by_actor_id,
            "decision_note": cycle.decision_note,
        }
        for cycle in qa_cycles
    ]
    manifest: list[dict[str, object]] = [
        {
            "filename": attachment.original_filename,
            "media_type": attachment.content_type,
            "content_hash": attachment.sha256,
            "size_bytes": attachment.size_bytes,
            "attachment_id": attachment.id,
        }
        for attachment in attachments
    ]
    envelope: Envelope = {
        "history_schema_version": HISTORY_SCHEMA_VERSION,
        "source_kind": "native",
        "conformance": "native",
        "board_id": board_id,
        "loop": {
            "id": loop.id,
            "key": loop.key,
            "name": loop.name,
            "goal": loop.goal,
            "stage": loop.stage,
            "sequence": loop.sequence,
            "created_at": loop.created_at,
            "completed_at": completed_at,
            "created_by_actor_id": loop.created_by_actor_id,
            "created_by_name": loop.created_by_name,
        },
        "documents": document_entries,
        "plan": {
            "revisions": [
                {
                    "plan_id": plan.id,
                    "revision_number": plan.revision_number,
                    "status": plan.status,
                    "approval_id": plan.approval_id,
                    "payload": json.loads(plan.payload_json),
                    "content_hash": plan.content_hash,
                    "created_at": plan.created_at,
                    "activated_at": plan.activated_at,
                }
                for plan in plans
            ],
            "phases": [
                {
                    "id": phase.id,
                    "number": phase.number,
                    "name": phase.name,
                    "objective": phase.objective,
                    "entry_conditions": json.loads(phase.entry_conditions_json or "[]"),
                    "exit_conditions": json.loads(phase.exit_conditions_json or "[]"),
                    "is_qa_phase": bool(phase.is_qa_phase),
                }
                for phase in phases
            ],
            "tickets": [
                {
                    "id": item.id,
                    "key": item.key,
                    "title": item.title,
                    "phase_number": item.phase_number,
                    "objective": item.objective,
                    "instructions": item.instructions,
                    "required_actor": item.required_actor,
                    "execution_mode": item.execution_mode,
                    "acceptance_criteria": json.loads(item.acceptance_criteria_json or "[]"),
                    "expected_evidence": json.loads(item.expected_evidence_json or "[]"),
                    "human_action_reason": item.human_action_reason,
                    "human_instructions": item.human_instructions,
                }
                for item in items
            ],
            "dependencies": [
                {
                    "source_type": edge.source_type,
                    "source_id": edge.source_id,
                    "target_type": edge.target_type,
                    "target_id": edge.target_id,
                }
                for edge in dependencies
            ],
        },
        "delivery": {
            "tickets": [
                {
                    "id": card.id,
                    "key": card.ticket_key,
                    "title": card.title,
                    "kind": card.kind,
                    "list_id": card.list_id,
                    "completed_at": card.completed_at,
                    "disposition": "completed"
                    if card.completed_at
                    else ("archived" if card.archived_at else "open"),
                    "human_confirmed_at": card.human_confirmed_at,
                    "human_confirmed_by_actor_id": card.human_confirmed_by_actor_id,
                    "assignee_name": card.assignee_name,
                    "labels": [label.name for label in labels.get(card.id, [])],
                }
                for card in cards
            ],
            "comments": [
                {
                    "card_id": comment.card_id,
                    "actor_id": comment.actor_id,
                    "content": comment.content,
                    "created_at": comment.created_at,
                }
                for comment in comments
            ],
            "checklists": [dict(line) for line in checklists],
        },
        "human_decisions": decisions,
        "qa": {
            "cycles": cycles,
            "results": [
                {
                    "scenario_id": result.scenario_id,
                    "status": result.status,
                    "reason": result.reason,
                    "evidence": result.evidence,
                    "actor_id": result.actor_id,
                    "actor_type": result.actor_type,
                    "actor_name": result.actor_name,
                    "tested_baseline": result.tested_baseline,
                    "instruction_revision": result.instruction_revision,
                    "source": "reported" if result.actor_type == "agent" else "human_attestation",
                    "created_at": result.created_at,
                }
                for result in qa_results
            ],
        },
        "generation_provenance": generation_provenance(runs),
        "activity": [
            {
                "actor_id": entry.actor_id,
                "actor_type": entry.actor_type,
                "action": entry.action,
                "timestamp": entry.timestamp,
                "changes": json.loads(entry.changes_json or "{}"),
            }
            for entry in activity
        ],
        "assets": {"manifest": manifest},
    }

    # The search reads the same text the snapshot holds.
    parts: list[str | None] = [loop.name, loop.goal, loop.key]
    for record in documents:
        parts.append(record.content)
        if record.payload_json:
            payload: object = json.loads(record.payload_json)
            if payload:
                parts.append(canonical(payload))
    for approval in approvals:
        parts.append(approval.feedback)
        parts.append(canonical(json.loads(approval.revisions_json or "{}")))
    for item in items:
        parts.extend(
            [item.key, item.title, item.objective, item.instructions, item.human_instructions]
        )
    parts.extend(card.title for card in cards)
    parts.extend(comment.content for comment in comments)
    parts.extend(canonical(json.loads(cycle.ai_instructions_json or "{}")) for cycle in qa_cycles)
    for result in qa_results:
        parts.append(result.evidence)
        parts.append(result.reason)
    search_text = "\n".join(part for part in parts if part)[:MAX_SEARCH_TEXT]
    return envelope, search_text, manifest


def serialize(record: LoopHistoryRow, *, with_envelope: bool) -> HistoryEntry:
    entry: HistoryEntry = dict(asdict(record))
    entry.pop("validation_warnings_json", None)
    entry["warnings"] = json.loads(record.validation_warnings_json or "[]")
    entry["label"] = LEGACY_LABEL if record.source_kind == "imported_legacy" else ""
    entry.pop("envelope_json", None)
    if with_envelope:
        entry["envelope"] = json.loads(record.envelope_json or "{}")
    entry.pop("search_text", None)
    return entry


def _new_id() -> str:
    return str(uuid4())


class LoopHistoryService:
    def __init__(
        self,
        board_service: BoardChecks,
        store: BoardUnitOfWork,
        files: AttachmentFiles,
        index: FullTextIndex,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.board_service = board_service
        self.store = store
        self.files = files
        self.index = index
        self._clock = clock
        self._new_id = new_id

    # --- snapshot --------------------------------------------------------------

    def finalize(
        self,
        repos: BoardRepositories,
        loop_id: str,
        *,
        actor: ActorContext,
        qa_approval_id: str | None,
        attestation: Mapping[str, object],
        board_id: str,
    ) -> HistoryEntry:
        """Atomically capture history and mark the Loop completed. Idempotent."""
        loop = repos.loops.get(loop_id)
        if loop is None:
            raise NotFound("Loop not found", code="loop_not_found")
        existing = repos.history.native_for(board_id, loop_id)
        if existing is not None:
            return serialize(existing, with_envelope=True)
        if loop.qa_approval_id is None and qa_approval_id is None:
            raise Conflict(
                "QA must be accepted before the Loop can be completed", code="qa_incomplete"
            )
        now = self._clock()
        envelope, search_text, manifest = snapshot(
            repos, loop, board_id=board_id, completed_at=now
        )
        envelope["qa_attestation"] = dict(attestation) if attestation else {}
        blob = canonical(envelope)
        history_id = self._new_id()
        repos.history.add_native(
            {
                "id": history_id,
                "history_schema_version": HISTORY_SCHEMA_VERSION,
                "board_id": board_id,
                "loop_id": loop_id,
                "loop_key": loop.key,
                "loop_name": loop.name,
                "qa_status": "accepted",
                "envelope_json": blob,
                "search_text": search_text,
                "content_hash": _digest(blob),
                "now": now,
            }
        )
        self._store_artifacts(repos, history_id, board_id, loop_id, envelope, manifest)
        repos.loops.complete(loop_id, history_id=history_id, now=now)
        repos.activity.add(
            activity_entry(
                actor,
                action="loop.completed",
                entity_type="loop",
                entity_id=loop_id,
                changes={"history_id": history_id},
                entry_id=self._new_id(),
                timestamp=now,
            )
        )
        record = repos.history.get(history_id)
        if record is None:
            raise NotFound("History record not found")
        return serialize(record, with_envelope=True)

    def _store_artifacts(
        self,
        repos: BoardRepositories,
        history_id: str,
        board_id: str,
        loop_id: str,
        envelope: Envelope,
        manifest: list[dict[str, object]],
    ) -> None:
        """Bounded, self-contained evidence bytes; anything not embedded is disclosed."""
        attachments = repos.archive.attachments(loop_id)
        if not attachments:
            return
        total = 0
        for attachment in attachments:
            included = False
            data: bytes | None = None
            if attachment.size_bytes <= MAX_ARTIFACT_BYTES and total < MAX_ARTIFACT_TOTAL:
                try:
                    path = attachment_path(self.files, board_id, attachment.stored_filename)
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != attachment.sha256:
                        data = None
                    else:
                        included = True
                        total += len(data)
                except OSError:
                    data = None
            repos.history.add_artifact(
                LoopHistoryArtifactsRow(
                    id=self._new_id(),
                    history_id=history_id,
                    filename=attachment.original_filename,
                    media_type=attachment.content_type,
                    content_hash=attachment.sha256,
                    size_bytes=attachment.size_bytes,
                    inclusion="included" if included else "excluded",
                    data=data,
                )
            )
            for entry in manifest:
                if entry.get("attachment_id") == attachment.id:
                    entry["inclusion"] = "included" if included else "excluded"
        sealed = canonical(envelope)
        repos.history.seal(history_id, envelope_json=sealed, content_hash=_digest(sealed))

    # --- reads -----------------------------------------------------------------

    def existing(self, board_id: str, loop_id: str) -> HistoryEntry:
        """Return the committed snapshot for a Loop; repeated finalization reuses it."""
        with self.store.reader(board_id) as repos:
            record = repos.history.native_for(board_id, loop_id)
        if record is None:
            raise NotFound("This Loop has no completed history record", code="qa_incomplete")
        return serialize(record, with_envelope=True)

    def detail(self, board_id: str, history_id: str) -> HistoryEntry:
        with self.store.reader(board_id) as repos:
            record = repos.history.get(history_id)
            if record is None:
                raise NotFound("History record not found")
            artifacts = repos.history.artifacts(history_id)
        entry = serialize(record, with_envelope=True)
        entry["artifacts"] = artifacts
        return entry

    def search(
        self,
        board_id: str,
        *,
        q: str | None = None,
        source_kind: str | None = None,
        loop_key: str | None = None,
        qa_status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        self.board_service.require_row(board_id)
        query: HistoryQuery = {}
        engine = "like"
        fts = False
        if q:
            if self.index.fts_available(board_id):
                fts = True
                query["match"] = fts_query(q)
                engine = "fts5"
            else:
                query["q"] = f"%{q}%"
        if source_kind:
            query["source_kind"] = source_kind
        if loop_key:
            query["loop_key"] = loop_key
            query["loop_key_like"] = f"%{loop_key}%"
        if qa_status:
            query["qa_status"] = qa_status
        if date_from:
            query["date_from"] = date_from
        if date_to:
            query["date_to"] = date_to
        with self.store.reader(board_id) as repos:
            total = repos.history.count(query, fts=fts)
            records = repos.history.page(query, fts=fts, limit=limit, offset=offset)
        return {
            "items": [serialize(record, with_envelope=False) for record in records],
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
            "engine": engine,
        }

    # --- legacy import boundary ------------------------------------------------

    def import_legacy(
        self, actor: ActorContext, board_id: str, payload: LegacyImportRequest
    ) -> tuple[HistoryEntry, bool]:
        """Validate and store the envelope only; never create Tickets or approvals."""
        actor.require("boards:write")
        actor.require_human("Importing legacy material")
        self.board_service.ensure_active(board_id)
        if payload.idempotency_key:
            with self.store.reader(board_id) as repos:
                earlier = repos.idempotency.get(actor.actor_id, payload.idempotency_key)
            if earlier is not None:
                response: object = json.loads(earlier.response_json)
                record_id = response.get("id") if _is_object(response) else None
                if isinstance(record_id, str) and record_id:
                    return self.detail(board_id, record_id), True
        now = self._clock()
        history_id = self._new_id()
        warnings: list[str] = []
        if not payload.documents:
            warnings.append("No document content was supplied")
        if payload.reported_qa_status:
            warnings.append(
                "Reported QA status is source information, not a verified Tralala QA result"
            )
        envelope: Envelope = {
            "history_schema_version": HISTORY_SCHEMA_VERSION,
            "source_kind": "imported_legacy",
            "conformance": "legacy_unvalidated",
            "board_id": board_id,
            "loop": {
                "id": None,
                "key": None,
                "name": payload.loop_name,
                "stage": "imported",
                "completed_at": None,
            },
            "imported_at": now,
            "imported_by": actor.actor_id,
            "source_project": payload.source_project,
            "source_reference": payload.source_reference,
            "source_format": payload.source_format,
            "source_version": payload.source_version,
            "reported_metadata": payload.reported_metadata,
            "reported_qa_status": payload.reported_qa_status,
            "documents": [
                {"kind": kind, "content": content, "revision_number": None}
                for kind, content in payload.documents.items()
            ],
            "raw_text": payload.raw_text,
            "validation_warnings": warnings,
        }
        blob = canonical(envelope)
        search_text = "\n".join(
            [payload.loop_name, payload.raw_text, *payload.documents.values()]
        )[:MAX_SEARCH_TEXT]
        with self.store.writer(board_id) as repos:
            repos.history.add_imported(
                {
                    "id": history_id,
                    "history_schema_version": HISTORY_SCHEMA_VERSION,
                    "board_id": board_id,
                    "loop_name": payload.loop_name,
                    "qa_status": "unknown",
                    "envelope_json": blob,
                    "search_text": search_text,
                    "content_hash": _digest(blob),
                    "now": now,
                    "imported_by_actor_id": actor.actor_id,
                    "source_project": payload.source_project,
                    "source_reference": payload.source_reference,
                    "source_format": payload.source_format,
                    "source_version": payload.source_version,
                    "validation_warnings_json": json.dumps(warnings),
                }
            )
            if payload.idempotency_key:
                repos.idempotency.put(
                    IdempotencyRecordsRow(
                        actor_id=actor.actor_id,
                        idempotency_key=payload.idempotency_key,
                        request_hash=_digest(blob),
                        response_json=json.dumps({"id": history_id}),
                        created_at=now,
                        expires_at=now,
                    )
                )
            repos.activity.add(
                activity_entry(
                    actor,
                    action="loop.legacy_imported",
                    entity_type="loop_history",
                    entity_id=history_id,
                    changes={"loop_name": payload.loop_name},
                    entry_id=self._new_id(),
                    timestamp=now,
                )
            )
        return self.detail(board_id, history_id), False


__all__ = ["HISTORY_SCHEMA_VERSION", "LEGACY_LABEL", "LoopHistoryService"]
