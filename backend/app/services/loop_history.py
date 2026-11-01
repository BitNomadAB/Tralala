"""Immutable Board-local Loop history and the future legacy-import envelope.

Completing a Loop stores a self-contained, hashed snapshot in the owning Board database. Nothing
here writes Markdown into the project repository, and nothing converts imported legacy material
into active Loops.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound
from ..schemas.loops import LegacyImportRequest
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import one, rows

HISTORY_SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_TOTAL = 20 * 1024 * 1024
LEGACY_LABEL = "Imported legacy reference - may not follow the current standard"
MAX_SEARCH_TEXT = 200_000


def generation_provenance(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prove which agent and instructions produced a document without handing over the prompt."""
    return [
        {
            "run_id": run["id"],
            "purpose": run["purpose"],
            "status": run["status"],
            "agent_id": run["agent_id"],
            "agent_name": run["agent_name"],
            "model": run["model"],
            "system_prompt_sha256": _prompt_digest(run["role_snapshot_json"]),
            "usage": json.loads(run["usage_json"] or "{}"),
            "created_at": run["created_at"],
            "finished_at": run["finished_at"],
            "error_code": run["error_code"],
        }
        for run in runs
    ]


def _prompt_digest(role_snapshot_json: str | None) -> str | None:
    try:
        snapshot = json.loads(role_snapshot_json or "{}")
    except (TypeError, ValueError):
        return None
    prompt = snapshot.get("system_prompt") if isinstance(snapshot, dict) else None
    if not isinstance(prompt, str) or not prompt:
        return None
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _fts_query(value: str) -> str:
    tokens = [token.replace('"', " ") for token in value.split() if token.strip()]
    return " AND ".join(f'"{token}"*' for token in tokens)


class LoopHistoryService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards

    # --- snapshot --------------------------------------------------------------

    def envelope(self, conn: Any, loop: dict[str, Any]) -> dict[str, Any]:
        loop_id = loop["id"]
        documents = rows(
            conn,
            "SELECT * FROM loop_documents WHERE loop_id = :id ORDER BY kind, revision_number",
            {"id": loop_id},
        )
        approvals = rows(
            conn,
            "SELECT * FROM loop_approvals WHERE loop_id = :id ORDER BY created_at",
            {"id": loop_id},
        )
        plans = rows(
            conn,
            "SELECT * FROM loop_plans WHERE loop_id = :id ORDER BY revision_number",
            {"id": loop_id},
        )
        phases = rows(
            conn, "SELECT * FROM loop_phases WHERE loop_id = :id ORDER BY number", {"id": loop_id}
        )
        items = rows(
            conn,
            "SELECT * FROM loop_plan_items WHERE loop_id = :id ORDER BY phase_number,"
            " ticket_sequence",
            {"id": loop_id},
        )
        dependencies = rows(
            conn,
            "SELECT * FROM loop_dependencies WHERE loop_id = :id",
            {"id": loop_id},
        )
        cards = rows(
            conn,
            "SELECT * FROM cards WHERE loop_id = :id ORDER BY ticket_key, created_at",
            {"id": loop_id},
        )
        comments = rows(
            conn,
            "SELECT c.* FROM comments c JOIN cards k ON k.id = c.card_id"
            " WHERE k.loop_id = :id ORDER BY c.created_at",
            {"id": loop_id},
        )
        checklists = rows(
            conn,
            "SELECT ch.card_id, ch.title, i.text, i.completed FROM checklists ch"
            " JOIN cards k ON k.id = ch.card_id"
            " LEFT JOIN checklist_items i ON i.checklist_id = ch.id"
            " WHERE k.loop_id = :id ORDER BY ch.card_id, ch.position, i.position",
            {"id": loop_id},
        )
        qa_cycles = rows(
            conn,
            "SELECT * FROM loop_qa_cycles WHERE loop_id = :id ORDER BY cycle_number",
            {"id": loop_id},
        )
        qa_results = rows(
            conn,
            "SELECT r.* FROM loop_qa_results r JOIN loop_qa_cycles c ON c.id = r.cycle_id"
            " WHERE c.loop_id = :id ORDER BY r.created_at",
            {"id": loop_id},
        )
        runs = rows(
            conn,
            "SELECT id, purpose, status, agent_id, agent_name, model, role_snapshot_json,"
            " usage_json, created_at, finished_at, error_code FROM loop_generation_runs"
            " WHERE loop_id = :id ORDER BY created_at",
            {"id": loop_id},
        )
        activity = rows(
            conn,
            "SELECT actor_id, actor_type, action, entity_type, entity_id, timestamp, changes_json"
            " FROM activity_log WHERE entity_type = 'loop' AND entity_id = :id"
            " ORDER BY timestamp",
            {"id": loop_id},
        )
        attachments = rows(
            conn,
            "SELECT a.* FROM attachments a JOIN cards k ON k.id = a.card_id"
            " WHERE k.loop_id = :id AND a.deleted_at IS NULL ORDER BY a.created_at",
            {"id": loop_id},
        )
        return {
            "history_schema_version": HISTORY_SCHEMA_VERSION,
            "source_kind": "native",
            "conformance": "native",
            "board_id": loop["board_id"] if "board_id" in loop else None,
            "loop": {
                "id": loop["id"],
                "key": loop["key"],
                "name": loop["name"],
                "goal": loop["goal"],
                "stage": loop["stage"],
                "sequence": loop["sequence"],
                "created_at": loop["created_at"],
                "completed_at": loop["completed_at"] or utcnow(),
                "created_by_actor_id": loop["created_by_actor_id"],
                "created_by_name": loop["created_by_name"],
            },
            "documents": [
                {
                    "kind": record["kind"],
                    "revision_id": record["id"],
                    "revision_number": record["revision_number"],
                    "content": record["content"],
                    "payload": json.loads(record["payload_json"])
                    if record["payload_json"]
                    else None,
                    "content_hash": record["content_hash"],
                    "is_approved": bool(record["is_approved"]),
                    "author_name": record["author_name"],
                    "author_actor_type": record["author_actor_type"],
                    "created_at": record["created_at"],
                }
                for record in documents
            ],
            "plan": {
                "revisions": [
                    {
                        "plan_id": plan["id"],
                        "revision_number": plan["revision_number"],
                        "status": plan["status"],
                        "approval_id": plan["approval_id"],
                        "payload": json.loads(plan["payload_json"]),
                        "content_hash": plan["content_hash"],
                        "created_at": plan["created_at"],
                        "activated_at": plan["activated_at"],
                    }
                    for plan in plans
                ],
                "phases": [
                    {
                        "id": phase["id"],
                        "number": phase["number"],
                        "name": phase["name"],
                        "objective": phase["objective"],
                        "entry_conditions": json.loads(phase["entry_conditions_json"] or "[]"),
                        "exit_conditions": json.loads(phase["exit_conditions_json"] or "[]"),
                        "is_qa_phase": bool(phase["is_qa_phase"]),
                    }
                    for phase in phases
                ],
                "tickets": [
                    {
                        "id": item["id"],
                        "key": item["key"],
                        "title": item["title"],
                        "phase_number": item["phase_number"],
                        "objective": item["objective"],
                        "instructions": item["instructions"],
                        "required_actor": item["required_actor"],
                        "execution_mode": item["execution_mode"],
                        "acceptance_criteria": json.loads(
                            item["acceptance_criteria_json"] or "[]"
                        ),
                        "expected_evidence": json.loads(item["expected_evidence_json"] or "[]"),
                        "human_action_reason": item["human_action_reason"],
                        "human_instructions": item["human_instructions"],
                    }
                    for item in items
                ],
                "dependencies": [
                    {
                        "source_type": edge["source_type"],
                        "source_id": edge["source_id"],
                        "target_type": edge["target_type"],
                        "target_id": edge["target_id"],
                    }
                    for edge in dependencies
                ],
            },
            "delivery": {
                "tickets": [
                    {
                        "id": card["id"],
                        "key": card["ticket_key"],
                        "title": card["title"],
                        "kind": card["kind"],
                        "list_id": card["list_id"],
                        "completed_at": card["completed_at"],
                        "disposition": "completed"
                        if card["completed_at"]
                        else ("archived" if card["archived_at"] else "open"),
                        "human_confirmed_at": card["human_confirmed_at"],
                        "human_confirmed_by_actor_id": card["human_confirmed_by_actor_id"],
                        "assignee_name": card["assignee_name"],
                        "labels": [
                            label["name"]
                            for label in rows(
                                conn,
                                "SELECT l.name FROM card_labels cl JOIN labels l"
                                " ON l.id = cl.label_id WHERE cl.card_id = :id ORDER BY l.name",
                                {"id": card["id"]},
                            )
                        ],
                    }
                    for card in cards
                ],
                "comments": [
                    {
                        "card_id": comment["card_id"],
                        "actor_id": comment["actor_id"],
                        "content": comment["content"],
                        "created_at": comment["created_at"],
                    }
                    for comment in comments
                ],
                "checklists": [
                    {
                        "card_id": entry["card_id"],
                        "title": entry["title"],
                        "text": entry["text"],
                        "completed": entry["completed"],
                    }
                    for entry in checklists
                ],
            },
            "human_decisions": [
                {
                    "id": approval["id"],
                    "scope": approval["scope"],
                    "decision": approval["decision"],
                    "reviewer_actor_id": approval["reviewer_actor_id"],
                    "reviewer_name": approval["reviewer_name"],
                    "feedback": approval["feedback"],
                    "revisions": json.loads(approval["revisions_json"] or "{}"),
                    "source_hashes": json.loads(approval["source_hashes_json"] or "{}"),
                    "created_at": approval["created_at"],
                }
                for approval in approvals
            ],
            "qa": {
                "cycles": [
                    {
                        "id": cycle["id"],
                        "cycle_number": cycle["cycle_number"],
                        "status": cycle["status"],
                        "instruction_revision": cycle["instruction_revision"],
                        "ai_instructions": json.loads(cycle["ai_instructions_json"] or "{}"),
                        "human_instructions": json.loads(
                            cycle["human_instructions_json"] or "{}"
                        ),
                        "attestation": json.loads(cycle["attestation_json"] or "{}"),
                        "decided_at": cycle["decided_at"],
                        "decided_by_actor_id": cycle["decided_by_actor_id"],
                        "decision_note": cycle["decision_note"],
                    }
                    for cycle in qa_cycles
                ],
                "results": [
                    {
                        "scenario_id": result["scenario_id"],
                        "status": result["status"],
                        "reason": result["reason"],
                        "evidence": result["evidence"],
                        "actor_id": result["actor_id"],
                        "actor_type": result["actor_type"],
                        "actor_name": result["actor_name"],
                        "tested_baseline": result["tested_baseline"],
                        "instruction_revision": result["instruction_revision"],
                        "source": "reported"
                        if result["actor_type"] == "agent"
                        else "human_attestation",
                        "created_at": result["created_at"],
                    }
                    for result in qa_results
                ],
            },
            "generation_provenance": generation_provenance(runs),
            "activity": [
                {
                    "actor_id": entry["actor_id"],
                    "actor_type": entry["actor_type"],
                    "action": entry["action"],
                    "timestamp": entry["timestamp"],
                    "changes": json.loads(entry["changes_json"] or "{}"),
                }
                for entry in activity
            ],
            "assets": {
                "manifest": [
                    {
                        "filename": attachment["original_filename"],
                        "media_type": attachment["content_type"],
                        "content_hash": attachment["sha256"],
                        "size_bytes": attachment["size_bytes"],
                        "attachment_id": attachment["id"],
                    }
                    for attachment in attachments
                ]
            },
        }

    def _search_text(self, loop: dict[str, Any], envelope: dict[str, Any]) -> str:
        parts: list[str] = [loop["name"], loop["goal"], loop["key"]]
        for document in envelope["documents"]:
            parts.append(document["content"])
            if document["payload"]:
                parts.append(_canonical(document["payload"]))
        for decision in envelope["human_decisions"]:
            parts.append(decision["feedback"])
            parts.append(_canonical(decision["revisions"]))
        for ticket in envelope["plan"]["tickets"]:
            parts.extend(
                [
                    ticket["key"],
                    ticket["title"],
                    ticket["objective"],
                    ticket["instructions"],
                    ticket["human_instructions"],
                ]
            )
        for ticket in envelope["delivery"]["tickets"]:
            parts.append(ticket["title"])
        for comment in envelope["delivery"]["comments"]:
            parts.append(comment["content"])
        for cycle in envelope["qa"]["cycles"]:
            parts.append(_canonical(cycle["ai_instructions"]))
        for result in envelope["qa"]["results"]:
            parts.append(result["evidence"])
            parts.append(result["reason"])
        text_output = "\n".join(part for part in parts if part)
        return text_output[:MAX_SEARCH_TEXT]

    def finalize(
        self,
        conn: Any,
        loop_id: str,
        *,
        actor: ActorContext,
        qa_approval_id: str | None,
        attestation: dict[str, Any],
        board_id: str,
    ) -> dict[str, Any]:
        """Atomically capture history and mark the Loop completed. Idempotent."""
        loop = one(conn, "SELECT * FROM loops WHERE id = :id", {"id": loop_id})
        if loop is None:
            raise NotFound("Loop not found", code="loop_not_found")
        existing = one(
            conn,
            "SELECT * FROM loop_history WHERE board_id = :board AND loop_id = :loop"
            " AND source_kind = 'native'",
            {"board": board_id, "loop": loop_id},
        )
        if existing is not None:
            return self._serialize(existing, with_envelope=True)
        if loop["qa_approval_id"] is None and qa_approval_id is None:
            raise Conflict(
                "QA must be accepted before the Loop can be completed", code="qa_incomplete"
            )
        now = utcnow()
        snapshot_loop = dict(loop)
        snapshot_loop["board_id"] = board_id
        snapshot_loop["completed_at"] = now
        envelope = self.envelope(conn, snapshot_loop)
        envelope["qa_attestation"] = attestation or {}
        blob = _canonical(envelope)
        content_digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        history_id = str(uuid4())
        search_text = self._search_text(loop, envelope)
        conn.execute(
            text(
                "INSERT INTO loop_history (id, history_schema_version, source_kind, conformance,"
                " board_id, loop_id, loop_key, loop_name, qa_status, envelope_json, search_text,"
                " content_hash, completed_at, created_at)"
                " VALUES (:id, :version, 'native', 'native', :board_id, :loop_id, :key, :name,"
                " :qa_status, :envelope, :search, :hash, :now, :now)"
            ),
            {
                "id": history_id,
                "version": HISTORY_SCHEMA_VERSION,
                "board_id": board_id,
                "loop_id": loop_id,
                "key": loop["key"],
                "name": loop["name"],
                "qa_status": "accepted",
                "envelope": blob,
                "search": search_text,
                "hash": content_digest,
                "now": now,
            },
        )
        self._store_artifacts(conn, history_id, board_id, loop_id, envelope)
        conn.execute(
            text(
                "UPDATE loops SET stage = 'completed', completed_at = :now, history_id = :history,"
                " version = version + 1, updated_at = :now WHERE id = :id"
            ),
            {"now": now, "history": history_id, "id": loop_id},
        )
        log_activity(
            conn,
            actor,
            action="loop.completed",
            entity_type="loop",
            entity_id=loop_id,
            changes={"history_id": history_id},
        )
        record = one(conn, "SELECT * FROM loop_history WHERE id = :id", {"id": history_id})
        return self._serialize(record, with_envelope=True)

    def _store_artifacts(
        self, conn: Any, history_id: str, board_id: str, loop_id: str, envelope: dict[str, Any]
    ) -> None:
        """Bounded, self-contained evidence bytes; anything not embedded is disclosed."""
        from .attachments import AttachmentService

        attachments = rows(
            conn,
            "SELECT a.* FROM attachments a JOIN cards k ON k.id = a.card_id"
            " WHERE k.loop_id = :id AND a.deleted_at IS NULL ORDER BY a.created_at",
            {"id": loop_id},
        )
        if not attachments:
            return
        service = AttachmentService(self.board_service)
        total = 0
        for attachment in attachments:
            included = False
            data: bytes | None = None
            if attachment["size_bytes"] <= MAX_ARTIFACT_BYTES and total < MAX_ARTIFACT_TOTAL:
                try:
                    path = service.file_path(board_id, attachment["stored_filename"])
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != attachment["sha256"]:
                        data = None
                    else:
                        included = True
                        total += len(data)
                except OSError:
                    data = None
            conn.execute(
                text(
                    "INSERT INTO loop_history_artifacts (id, history_id, filename, media_type,"
                    " content_hash, size_bytes, inclusion, data) VALUES (:id, :history_id,"
                    " :filename, :media, :hash, :size, :inclusion, :data)"
                ),
                {
                    "id": str(uuid4()),
                    "history_id": history_id,
                    "filename": attachment["original_filename"],
                    "media": attachment["content_type"],
                    "hash": attachment["sha256"],
                    "size": attachment["size_bytes"],
                    "inclusion": "included" if included else "excluded",
                    "data": data,
                },
            )
            for entry in envelope["assets"]["manifest"]:
                if entry["attachment_id"] == attachment["id"]:
                    entry["inclusion"] = "included" if included else "excluded"
        conn.execute(
            text("UPDATE loop_history SET envelope_json = :envelope WHERE id = :id"),
            {"envelope": _canonical(envelope), "id": history_id},
        )
        conn.execute(
            text("UPDATE loop_history SET content_hash = :hash WHERE id = :id"),
            {
                "hash": hashlib.sha256(_canonical(envelope).encode("utf-8")).hexdigest(),
                "id": history_id,
            },
        )

    # --- reads -----------------------------------------------------------------

    def existing(self, board_id: str, loop_id: str) -> dict[str, Any]:
        """Return the committed snapshot for a Loop; repeated finalization reuses it."""
        with self.boards.reader(board_id) as conn:
            record = one(
                conn,
                "SELECT * FROM loop_history WHERE board_id = :board AND loop_id = :loop"
                " AND source_kind = 'native'",
                {"board": board_id, "loop": loop_id},
            )
        if record is None:
            raise NotFound("This Loop has no completed history record", code="qa_incomplete")
        return self._serialize(record, with_envelope=True)

    def detail(self, board_id: str, history_id: str) -> dict[str, Any]:
        with self.boards.reader(board_id) as conn:
            record = one(
                conn, "SELECT * FROM loop_history WHERE id = :id", {"id": history_id}
            )
            if record is None:
                raise NotFound("History record not found")
            artifacts = rows(
                conn,
                "SELECT id, filename, media_type, content_hash, size_bytes, inclusion"
                " FROM loop_history_artifacts WHERE history_id = :id ORDER BY filename",
                {"id": history_id},
            )
        entry = self._serialize(record, with_envelope=True)
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
    ) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        clauses = ["1 = 1"]
        params: dict[str, Any] = {}
        engine = "like"
        join = ""
        if q:
            if self.boards.fts_available(board_id):
                join = " JOIN loop_history_fts f ON f.rowid = h.rowid"
                clauses.append("loop_history_fts MATCH :match")
                params["match"] = _fts_query(q)
                engine = "fts5"
            else:
                clauses.append("(h.search_text LIKE :q OR h.loop_name LIKE :q)")
                params["q"] = f"%{q}%"
        if source_kind:
            clauses.append("h.source_kind = :source_kind")
            params["source_kind"] = source_kind
        if loop_key:
            clauses.append("(h.loop_key = :loop_key OR h.loop_name LIKE :loop_key_like)")
            params["loop_key"] = loop_key
            params["loop_key_like"] = f"%{loop_key}%"
        if qa_status:
            clauses.append("h.qa_status = :qa_status")
            params["qa_status"] = qa_status
        if date_from:
            clauses.append("COALESCE(h.completed_at, h.imported_at, h.created_at) >= :date_from")
            params["date_from"] = date_from
        if date_to:
            clauses.append("COALESCE(h.completed_at, h.imported_at, h.created_at) <= :date_to")
            params["date_to"] = date_to
        where = " AND ".join(clauses)
        with self.boards.reader(board_id) as conn:
            total = conn.execute(
                text(f"SELECT COUNT(DISTINCT h.id) FROM loop_history h{join} WHERE {where}"),
                params,
            ).scalar_one()
            records = rows(
                conn,
                f"SELECT DISTINCT h.* FROM loop_history h{join} WHERE {where}"
                " ORDER BY COALESCE(h.completed_at, h.imported_at, h.created_at) DESC, h.id"
                " LIMIT :limit OFFSET :offset",
                {**params, "limit": limit, "offset": offset},
            )
        return {
            "items": [self._serialize(record, with_envelope=False) for record in records],
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < int(total),
            "engine": engine,
        }

    def _serialize(self, record: dict[str, Any], *, with_envelope: bool) -> dict[str, Any]:
        entry = dict(record)
        entry["warnings"] = json.loads(entry.pop("validation_warnings_json", "[]") or "[]")
        entry["label"] = LEGACY_LABEL if entry["source_kind"] == "imported_legacy" else ""
        if with_envelope:
            entry["envelope"] = json.loads(entry.pop("envelope_json", "{}") or "{}")
        else:
            entry.pop("envelope_json", None)
        entry.pop("search_text", None)
        return entry

    # --- legacy import boundary ------------------------------------------------

    def import_legacy(
        self, actor: ActorContext, board_id: str, payload: LegacyImportRequest
    ) -> tuple[dict[str, Any], bool]:
        """Validate and store the envelope only; never create Tickets or approvals."""
        actor.require("boards:write")
        actor.require_human("Importing legacy material")
        self.board_service.ensure_active(board_id)
        if payload.idempotency_key:
            with self.boards.reader(board_id) as conn:
                existing = one(
                    conn,
                    "SELECT * FROM idempotency_records WHERE actor_id = :actor"
                    " AND idempotency_key = :key",
                    {"actor": actor.actor_id, "key": payload.idempotency_key},
                )
            if existing is not None:
                record_id = json.loads(existing["response_json"]).get("id")
                if record_id:
                    return self.detail(board_id, record_id), True
        now = utcnow()
        history_id = str(uuid4())
        warnings: list[str] = []
        if not payload.documents:
            warnings.append("No document content was supplied")
        if payload.reported_qa_status:
            warnings.append(
                "Reported QA status is source information, not a verified Tralala QA result"
            )
        envelope = {
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
        blob = _canonical(envelope)
        search_text = "\n".join(
            [payload.loop_name, payload.raw_text, *payload.documents.values()]
        )[:MAX_SEARCH_TEXT]
        with self.boards.session(board_id) as conn:
            conn.execute(
                text(
                    "INSERT INTO loop_history (id, history_schema_version, source_kind,"
                    " conformance, board_id, loop_id, loop_key, loop_name, qa_status,"
                    " envelope_json, search_text, content_hash, imported_at,"
                    " imported_by_actor_id, source_project, source_reference, source_format,"
                    " source_version, validation_warnings_json, created_at)"
                    " VALUES (:id, :version, 'imported_legacy', 'legacy_unvalidated', :board_id,"
                    " NULL, NULL, :name, :qa_status, :envelope, :search, :hash, :now, :actor,"
                    " :project, :reference, :format, :source_version, :warnings, :now)"
                ),
                {
                    "id": history_id,
                    "version": HISTORY_SCHEMA_VERSION,
                    "board_id": board_id,
                    "name": payload.loop_name,
                    "qa_status": "unknown",
                    "envelope": blob,
                    "search": search_text,
                    "hash": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
                    "now": now,
                    "actor": actor.actor_id,
                    "project": payload.source_project,
                    "reference": payload.source_reference,
                    "format": payload.source_format,
                    "source_version": payload.source_version,
                    "warnings": json.dumps(warnings),
                },
            )
            if payload.idempotency_key:
                conn.execute(
                    text(
                        "INSERT OR REPLACE INTO idempotency_records (actor_id,"
                        " idempotency_key, request_hash, response_json, created_at, expires_at)"
                        " VALUES (:actor, :key, :hash, :response, :now, :expires)"
                    ),
                    {
                        "actor": actor.actor_id,
                        "key": payload.idempotency_key,
                        "hash": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
                        "response": json.dumps({"id": history_id}),
                        "now": now,
                        "expires": now,
                    },
                )
            log_activity(
                conn,
                actor,
                action="loop.legacy_imported",
                entity_type="loop_history",
                entity_id=history_id,
                changes={"loop_name": payload.loop_name},
            )
        return self.detail(board_id, history_id), False


__all__ = ["HISTORY_SCHEMA_VERSION", "LEGACY_LABEL", "LoopHistoryService"]
