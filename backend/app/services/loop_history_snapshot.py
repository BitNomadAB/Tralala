"""A completed Loop as its history records it: the envelope, its search text and asset manifest.

The snapshot is read through the archive repositories inside the unit of work that completes the
Loop, so it holds what the Loop held at that moment. Generation provenance proves which agent and
instructions produced a document without handing over the prompt.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import TypeGuard

from ..db.generated.board import LoopGenerationRunsRow, LoopsRow
from ..repositories.board import BoardRepositories

HISTORY_SCHEMA_VERSION = 1
MAX_SEARCH_TEXT = 200_000

Envelope = dict[str, object]
"""A history snapshot as JSON."""


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _prompt_digest(role_snapshot_json: str | None) -> str | None:
    try:
        snapshot: object = json.loads(role_snapshot_json or "{}")
    except ValueError:
        return None
    prompt = snapshot.get("system_prompt") if is_object(snapshot) else None
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
    notes = repos.notes.for_loop(loop_id)
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
        "notes": [
            {
                "id": note.id,
                "author_actor_id": note.author_actor_id,
                "author_actor_type": note.author_actor_type,
                "author_name": note.author_name,
                "content": note.content,
                "created_at": note.created_at,
            }
            for note in notes
        ],
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
    parts.extend(note.content for note in notes)
    parts.extend(canonical(json.loads(cycle.ai_instructions_json or "{}")) for cycle in qa_cycles)
    for result in qa_results:
        parts.append(result.evidence)
        parts.append(result.reason)
    search_text = "\n".join(part for part in parts if part)[:MAX_SEARCH_TEXT]
    return envelope, search_text, manifest


__all__ = [
    "HISTORY_SCHEMA_VERSION",
    "MAX_SEARCH_TEXT",
    "Envelope",
    "canonical",
    "generation_provenance",
    "is_object",
    "snapshot",
]
