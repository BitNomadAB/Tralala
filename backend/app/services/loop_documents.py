"""Revisioned Loop documents and human approvals.

Five slots per Loop: ``info`` (human intent), ``analysis_ai``/``analysis`` and
``roadmap_ai``/``roadmap``. Revisions are immutable; current and approved pointers are separate.
Human-facing Markdown is rendered from the validated structure so the human and machine views
cannot drift apart.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

from ..core import sql
from ..core.context import ActorContext
from ..core.errors import Conflict, Forbidden, ValidationFailure, VersionConflict
from ..schemas.loops import (
    AnalysisPayload,
    ApprovalRequest,
    CandidateSubmission,
    InfoRevisionWrite,
    PlanPayload,
    QaInstructions,
    ScopeResetRequest,
)
from ..storage.board_db import BoardDatabaseManager
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import one, rows
from .loop_bridge import LoopConnectionHelpers
from .loop_plans import LoopPlanService
from .loops import DOCUMENT_KINDS

ANALYSIS_SCOPE_KINDS = ("info", "analysis_ai", "analysis")
ROADMAP_SCOPE_KINDS = ("info", "analysis_ai", "analysis", "roadmap_ai", "roadmap")
REVIEW_SCOPES = ("analysis", "roadmap")
# A Loop's approval columns, upstream first; the names are formatted into SQL text (core/sql.py).
_APPROVAL_COLUMNS = (
    "analysis_approval_id",
    "roadmap_approval_id",
    "implementation_approval_id",
    "qa_approval_id",
)
MATERIAL_FINDING_CATEGORIES = {"risk", "blocker", "legal", "security", "question"}
MAX_DOCUMENT_PAYLOAD = 200_000

# A worker may seed or refine Info while the Loop is still speculative — the phase in which a person
# and their agent agree on what to build. Once planning has started, changing the input invalidates
# approvals, so the edit belongs to a signed-in person.
WORKER_INFO_STAGES = frozenset({"draft", "analysis_review"})


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_of(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return content_hash(canonical)


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


def render_roadmap(payload: dict[str, Any]) -> str:
    """Render the validated plan; prose is additive and structure comes from the server."""
    lines: list[str] = ["# RoadMap", ""]
    if payload.get("summary"):
        lines += [payload["summary"], ""]
    phases = payload.get("phases", [])
    by_id = {phase["id"]: phase for phase in phases}
    tickets_by_id = {
        ticket["id"]: ticket for phase in phases for ticket in phase.get("tickets", [])
    }
    for phase in phases:
        lines += [f"## Phase {phase['number']} — {phase['name']}", ""]
        if phase.get("objective"):
            lines += [phase["objective"], ""]
        if phase.get("narrative"):
            lines += [phase["narrative"], ""]
        prerequisites: list[str] = []
        for reference in phase.get("prerequisite_phase_ids", []):
            other = by_id.get(reference)
            if other:
                prerequisites.append(f"Phase {other['number']} ({other['name']})")
        for reference in phase.get("prerequisite_ticket_ids", []):
            other = tickets_by_id.get(reference)
            if other:
                prerequisites.append(f"Ticket {other['key']}")
        if prerequisites:
            lines += ["**Starts after:** " + ", ".join(prerequisites), ""]
        if phase.get("entry_conditions"):
            lines += ["**Before it can start:**"] + [
                f"- {item}" for item in phase["entry_conditions"]
            ] + [""]
        if phase.get("exit_conditions"):
            lines += ["**Done when:**"] + [f"- {item}" for item in phase["exit_conditions"]] + [""]
        tickets = phase.get("tickets", [])
        if tickets:
            lines += ["**Tickets**", ""]
        for ticket in tickets:
            human = ticket.get("required_actor") == "human"
            gate = ticket.get("execution_mode") == "pre_phase_gate"
            suffix = " — **Human action required**" if human else ""
            lines.append(f"- `{ticket['key']}` {ticket['title']}{suffix}")
            if gate:
                lines.append("  - This is a gate: the Phase cannot start until it is confirmed.")
            if ticket.get("objective"):
                lines.append(f"  - Why: {ticket['objective']}")
            if ticket.get("note"):
                lines.append(f"  - {ticket['note']}")
            if human:
                lines.append(f"  - Why a human is needed: {ticket['human_action_reason']}")
                lines.append(f"  - What you must do: {ticket['human_instructions']}")
            blocking: list[str] = []
            for reference in ticket.get("prerequisite_ticket_ids", []):
                other = tickets_by_id.get(reference)
                if other:
                    blocking.append(f"Ticket {other['key']}")
            for reference in ticket.get("prerequisite_phase_ids", []):
                other = by_id.get(reference)
                if other:
                    blocking.append(f"Phase {other['number']}")
            if blocking:
                lines.append("  - Can be done after: " + ", ".join(blocking))
            if ticket.get("acceptance_criteria"):
                lines.append("  - Accepted when: " + "; ".join(ticket["acceptance_criteria"]))
        lines.append("")
    lines += ["---", "", "Generated from the validated structured plan; the plan is authoritative."]
    return "\n".join(lines).strip() + "\n"


def render_analysis_technical(payload: AnalysisPayload) -> str:
    return "```json\n" + json.dumps(payload.model_dump(), indent=2, ensure_ascii=False) + "\n```\n"


class LoopDocumentService:
    def __init__(
        self,
        board_service: BoardService,
        loop_service: LoopConnectionHelpers,
        plan_service: LoopPlanService,
        *,
        boards: BoardDatabaseManager,
    ) -> None:
        self.board_service = board_service
        self.boards = boards
        self.loops = loop_service
        self.plans = plan_service

    # --- reads -----------------------------------------------------------------

    def _document_payload(self, row: dict[str, Any] | None) -> dict | None:
        if row is None or not row.get("payload_json"):
            return None
        try:
            return json.loads(row["payload_json"])
        except (TypeError, ValueError):
            return None

    def _serialize_document(
        self,
        conn: Any,
        loop_id: str,
        kind: str,
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        stale: dict[str, list[str]],
    ) -> dict[str, Any]:
        state = self.loops._document_state(kind, documents, approvals, stale)
        current = state["current"]
        approved = state["approved"]
        history = rows(
            conn,
            "SELECT id, revision_number, status, author_name, author_actor_type, created_at,"
            " content_hash FROM loop_documents WHERE loop_id = :id AND kind = :kind"
            " ORDER BY revision_number DESC LIMIT 20",
            {"id": loop_id, "kind": kind},
        )
        return {
            "loop_id": loop_id,
            "kind": kind,
            "state": state["state"],
            "current_revision_id": current["id"] if current else None,
            "current_revision_number": current["revision_number"] if current else None,
            "current_content": current["content"] if current else None,
            "current_payload": self._document_payload(current),
            "current_created_at": current["created_at"] if current else None,
            "approved_revision_id": approved["id"] if approved else None,
            "approved_revision_number": approved["revision_number"] if approved else None,
            "approved_content": approved["content"] if approved else None,
            "source_revisions": {
                "info": current["source_info_revision_id"] if current else None,
                "analysis_ai": current["source_analysis_ai_revision_id"] if current else None,
                "analysis": current["source_analysis_revision_id"] if current else None,
                "roadmap_ai": current["source_roadmap_ai_revision_id"] if current else None,
            }
            if current
            else {},
            "stale": state["state"] == "stale",
            "stale_reasons": state["stale_reasons"],
            "revisions": history,
        }

    def documents(self, board_id: str, loop_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            documents = self.loops.document_rows(conn, loop_id)
            approvals = self.loops.latest_approvals(conn, loop_id)
            stale = self.loops._stale_reasons(documents, approvals)
            return {
                "loop_id": loop_id,
                "loop_version": loop["version"],
                "documents": {
                    kind: self._serialize_document(
                        conn, loop_id, kind, documents, approvals, stale
                    )
                    for kind in DOCUMENT_KINDS
                },
                "approvals": {
                    scope: approval for scope, approval in approvals.items() if approval
                },
            }

    def revision_history(
        self, board_id: str, loop_id: str, kind: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        if kind not in DOCUMENT_KINDS:
            raise ValidationFailure(
                "Unknown document kind",
                details={"allowed": list(DOCUMENT_KINDS)},
            )
        with self.boards.reader(board_id) as conn:
            self.loops.require_loop_row(conn, board_id, loop_id)
            total = conn.execute(
                text(
                    "SELECT COUNT(*) FROM loop_documents WHERE loop_id = :id AND kind = :kind"
                ),
                {"id": loop_id, "kind": kind},
            ).scalar_one()
            records = rows(
                conn,
                "SELECT * FROM loop_documents WHERE loop_id = :id AND kind = :kind"
                " ORDER BY revision_number DESC LIMIT :limit OFFSET :offset",
                {"id": loop_id, "kind": kind, "limit": limit, "offset": offset},
            )
        items = []
        for record in records:
            entry = dict(record)
            entry["payload"] = self._document_payload(record)
            entry.pop("payload_json", None)
            items.append(entry)
        return items, int(total)

    # --- writes ----------------------------------------------------------------

    def context(self, board_id: str, loop_id: str) -> dict[str, Any]:
        """Versioned context for external agents; never contains credentials or other Loops."""
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            context = self.collect_context(conn, loop)
        context["schemas"] = {
            "analysis": AnalysisPayload.model_json_schema(),
            "roadmap": PlanPayload.model_json_schema(),
            "qa": QaInstructions.model_json_schema(),
        }
        return context

    def _next_revision(self, conn: Any, loop_id: str, kind: str) -> int:
        value = conn.execute(
            text(
                "SELECT COALESCE(MAX(revision_number), 0) FROM loop_documents"
                " WHERE loop_id = :id AND kind = :kind"
            ),
            {"id": loop_id, "kind": kind},
        ).scalar_one()
        return int(value) + 1

    def _write_revision(
        self,
        conn: Any,
        *,
        loop_id: str,
        kind: str,
        content: str,
        payload: dict[str, Any] | None,
        actor: ActorContext,
        status: str = "ready_for_review",
        sources: dict[str, str | None] | None = None,
        generation_run_id: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if payload is not None:
            encoded = json.dumps(payload)
            if len(encoded) > MAX_DOCUMENT_PAYLOAD:
                raise ValidationFailure(
                    "Generated document exceeds the configured size limit",
                    code="payload_too_large",
                    details={"limit": MAX_DOCUMENT_PAYLOAD},
                )
        now = utcnow()
        revision = self._next_revision(conn, loop_id, kind)
        document_id = str(__import__("uuid").uuid4())
        conn.execute(
            text("UPDATE loop_documents SET is_current = 0 WHERE loop_id = :id AND kind = :kind"),
            {"id": loop_id, "kind": kind},
        )
        conn.execute(
            text("UPDATE loop_documents SET is_approved = 0 WHERE loop_id = :id AND kind = :kind"),
            {"id": loop_id, "kind": kind},
        )
        sources = sources or {}
        conn.execute(
            text(
                "INSERT INTO loop_documents (id, loop_id, kind, revision_number, content,"
                " payload_json, content_hash, status, source_info_revision_id,"
                " source_analysis_ai_revision_id, source_analysis_revision_id,"
                " source_roadmap_ai_revision_id, generation_run_id, author_actor_id,"
                " author_actor_type, author_name, provenance_json, is_current, is_approved,"
                " created_at) VALUES (:id, :loop_id, :kind, :revision, :content, :payload, :hash,"
                " :status, :info, :analysis_ai, :analysis, :roadmap_ai, :run_id, :actor_id,"
                " :actor_type, :actor_name, :provenance, 1, 0, :now)"
            ),
            {
                "id": document_id,
                "loop_id": loop_id,
                "kind": kind,
                "revision": revision,
                "content": content,
                "payload": json.dumps(payload) if payload is not None else None,
                "hash": content_hash(content + (json.dumps(payload,
                sort_keys=True) if payload else "")),
                "status": status,
                "info": sources.get("info"),
                "analysis_ai": sources.get("analysis_ai"),
                "analysis": sources.get("analysis"),
                "roadmap_ai": sources.get("roadmap_ai"),
                "run_id": generation_run_id,
                "actor_id": actor.actor_id,
                "actor_type": actor.actor_type,
                "actor_name": actor.actor_name,
                "provenance": json.dumps(provenance or {}),
                "now": now,
            },
        )
        return one(conn, "SELECT * FROM loop_documents WHERE id = :id", {"id": document_id})  # type: ignore[return-value]

    def _invalidate_downstream(self, conn: Any, loop_id: str, kind: str) -> None:
        """A changed input invalidates the approvals that authorized execution."""
        if kind in {"info", "analysis_ai", "analysis"}:
            clears = _APPROVAL_COLUMNS
        elif kind in {"roadmap_ai", "roadmap"}:
            clears = _APPROVAL_COLUMNS[1:]
        else:
            return
        assignments = sql.assignments(clears, _APPROVAL_COLUMNS)
        conn.execute(
            text(
                "UPDATE loops"  # noqa: S608 - from _APPROVAL_COLUMNS
                f" SET {assignments}, updated_at = :now WHERE id = :id"
            ),
            {**dict.fromkeys(clears), "now": utcnow(), "id": loop_id},
        )
        stale_kinds = {
            "info": ("analysis_ai", "analysis", "roadmap_ai", "roadmap"),
            "analysis_ai": ("roadmap_ai", "roadmap"),
            "analysis": ("roadmap_ai", "roadmap"),
        }.get(kind, ())
        for stale_kind in stale_kinds:
            conn.execute(
                text(
                    "UPDATE loop_documents SET is_approved = 0 WHERE loop_id = :id"
                    " AND kind = :kind"
                ),
                {"id": loop_id, "kind": stale_kind},
            )
        conn.execute(
            text(
                "UPDATE loop_qa_cycles SET status = 'superseded', updated_at = :now"
                " WHERE loop_id = :id AND status IN ('pending','instructions_ready','in_progress')"
            ),
            {"now": utcnow(), "id": loop_id},
        )

    def save_info(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: InfoRevisionWrite
    ) -> dict[str, Any]:
        actor.require("loops:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            if not actor.is_user and loop["stage"] not in WORKER_INFO_STAGES:
                raise Forbidden(
                    "Info is a person's decision once the Loop is being planned",
                    code="human_action_required",
                    details={"stage": loop["stage"], "action": "Editing Loop Info"},
                )
            current = one(
                conn,
                "SELECT * FROM loop_documents WHERE loop_id = :id AND kind = 'info'"
                " AND is_current = 1",
                {"id": loop_id},
            )
            if (
                payload.expected_revision_id is not None
                and (current is None or current["id"] != payload.expected_revision_id)
            ):
                raise VersionConflict(
                    "Info changed since it was loaded",
                    code="document_stale",
                    details={
                        "expected_revision_id": payload.expected_revision_id,
                        "current_revision_id": current["id"] if current else None,
                    },
                )
            document = self._write_revision(
                conn,
                loop_id=loop_id,
                kind="info",
                content=payload.content,
                payload=None,
                actor=actor,
                status="ready_for_review",
                sources={},
                provenance={"note": payload.note},
            )
            self._invalidate_downstream(conn, loop_id, "info")
            log_activity(
                conn,
                actor,
                action="loop.info_revised",
                entity_type="loop",
                entity_id=loop_id,
                changes={"revision": document["revision_number"]},
            )
            self.loops.refresh_stage(conn, loop_id)
        return self.documents(board_id, loop_id)

    def submit_candidate(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: CandidateSubmission
    ) -> dict[str, Any]:
        actor.require("loops:generate")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            if payload.kind == "analysis":
                if payload.analysis is None:
                    raise ValidationFailure("An analysis candidate needs an analysis payload")
                self._store_analysis(conn, loop, payload.analysis, actor, payload)
            else:
                if payload.plan is None:
                    raise ValidationFailure("A RoadMap candidate needs a plan payload")
                self._store_roadmap(conn, loop, payload.plan, actor, payload)
            self.loops.refresh_stage(conn, loop_id)
        return self.documents(board_id, loop_id)

    def _validate_analysis(self, payload: AnalysisPayload) -> None:
        missing = [
            finding.id
            for finding in payload.findings
            if finding.category in MATERIAL_FINDING_CATEGORIES
            and not finding.plain_language.strip()
        ]
        if missing:
            raise ValidationFailure(
                "Material findings need a plain-language explanation",
                code="validation_failed",
                details={"finding_ids": missing},
            )

    def _store_analysis(
        self,
        conn: Any,
        loop: dict[str, Any],
        payload: AnalysisPayload,
        actor: ActorContext,
        submission: CandidateSubmission,
    ) -> None:
        self._validate_analysis(payload)
        info = one(
            conn,
            "SELECT * FROM loop_documents WHERE loop_id = :id AND kind = 'info'"
            " AND is_current = 1",
            {"id": loop["id"]},
        )
        if info is None and not submission.source_info_revision_id:
            raise Conflict(
                "Analysis needs a current Info revision from a human",
                code="document_stale",
                details={"missing": "info"},
            )
        info_id = info["id"] if info else submission.source_info_revision_id
        technical = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="analysis_ai",
            content=render_analysis_technical(payload),
            payload=payload.model_dump(),
            actor=actor,
            sources={"info": info_id},
            provenance={"submitted": True, **submission.provenance},
        )
        human = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="analysis",
            content=render_analysis(payload),
            payload=None,
            actor=actor,
            sources={"analysis_ai": technical["id"], "info": info_id},
            provenance={"submitted": True, **submission.provenance},
        )
        self._invalidate_downstream(conn, loop["id"], "analysis_ai")
        log_activity(
            conn,
            actor,
            action="loop.analysis_candidate",
            entity_type="loop",
            entity_id=loop["id"],
            changes={
                "analysis_ai_revision": technical["revision_number"],
                "analysis_revision": human["revision_number"],
            },
        )

    def _store_roadmap(
        self,
        conn: Any,
        loop: dict[str, Any],
        payload: PlanPayload,
        actor: ActorContext,
        submission: CandidateSubmission,
    ) -> None:
        documents = self.loops.document_rows(conn, loop["id"])
        approvals = self.loops.latest_approvals(conn, loop["id"])
        stale = self.loops._stale_reasons(documents, approvals)
        if not self.loops.analysis_approved(documents, approvals, stale):
            raise Conflict(
                "RoadMap generation requires a current approved analysis",
                code="approval_required",
                details={"scope": "analysis"},
            )
        info = documents["info"]["current"]
        analysis_ai = documents["analysis_ai"]["current"]
        analysis = documents["analysis"]["current"]
        draft = self.plans.register_draft(
            conn,
            loop,
            payload,
            actor,
            source_revisions={},
        )
        canonical = draft["payload"]
        technical = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="roadmap_ai",
            content="```json\n" + json.dumps(canonical, indent=2, ensure_ascii=False) + "\n```\n",
            payload=canonical,
            actor=actor,
            sources={
                "info": info["id"] if info else None,
                "analysis_ai": analysis_ai["id"] if analysis_ai else None,
                "analysis": analysis["id"] if analysis else None,
            },
            provenance={"plan_id": draft["plan_id"], **submission.provenance},
        )
        human = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="roadmap",
            content=render_roadmap(canonical),
            payload=None,
            actor=actor,
            sources={"roadmap_ai": technical["id"]},
            provenance={"plan_id": draft["plan_id"], **submission.provenance},
        )
        self.plans.attach_revisions(
            conn,
            draft["plan_id"],
            roadmap_ai_revision_id=technical["id"],
            roadmap_revision_id=human["id"],
        )
        self._invalidate_downstream(conn, loop["id"], "roadmap_ai")
        log_activity(
            conn,
            actor,
            action="loop.roadmap_candidate",
            entity_type="loop",
            entity_id=loop["id"],
            changes={"plan_id": draft["plan_id"], "phases": len(canonical["phases"])},
        )

    # --- approvals -------------------------------------------------------------

    def _expected_revisions(
        self,
        documents: dict[str, dict[str, Any]],
        scope: str,
    ) -> dict[str, str]:
        kinds = ANALYSIS_SCOPE_KINDS if scope == "analysis" else ROADMAP_SCOPE_KINDS
        expected: dict[str, str] = {}
        for kind in kinds:
            current = documents[kind]["current"]
            if current is None:
                raise Conflict(
                    f"{kind.replace('_', ' ').title()} is missing",
                    code="document_stale",
                    details={"missing": kind},
                )
            expected[kind] = current["id"]
        return expected

    def review(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        scope: str,
        payload: ApprovalRequest,
    ) -> dict[str, Any]:
        actor.require_human(
            "Approving an analysis" if scope == "analysis" else "Approving a RoadMap"
        )
        actor.require("loops:review")
        if scope not in {"analysis", "roadmap"}:
            raise ValidationFailure(
                "Unknown review scope", details={"allowed": ["analysis", "roadmap"]}
            )
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            if loop["version"] != payload.version:
                raise VersionConflict(
                    "Loop was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": loop["version"],
                    },
                )
            documents = self.loops.document_rows(conn, loop_id)
            expected = self._expected_revisions(documents, scope)
            for kind in expected:
                current = documents[kind]["current"]
                blank = current is not None and not (current["content"] or "").strip()
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
                conn,
                loop_id=loop_id,
                scope=scope,
                decision=payload.decision,
                actor=actor,
                revisions=expected,
                documents=documents,
                loop_version=loop["version"],
                feedback=payload.feedback,
            )
            if payload.decision == "approved":
                kinds = ANALYSIS_SCOPE_KINDS if scope == "analysis" else ROADMAP_SCOPE_KINDS
                for kind in kinds:
                    if kind == "info":
                        continue
                    conn.execute(
                        text(
                            "UPDATE loop_documents SET is_approved = 1, status = 'approved'"
                            " WHERE id = :id"
                        ),
                        {"id": expected[kind]},
                    )
                column = sql.identifier(
                    "analysis_approval_id" if scope == "analysis" else "roadmap_approval_id",
                    _APPROVAL_COLUMNS,
                )
                conn.execute(
                    text(
                        "UPDATE loops"  # noqa: S608 - from _APPROVAL_COLUMNS
                        f" SET {column} = :approval_id, version = version + 1,"
                        " updated_at = :now WHERE id = :id"
                    ),
                    {"approval_id": approval_id, "now": utcnow(), "id": loop_id},
                )
                if scope == "roadmap":
                    roadmap_ai = documents["roadmap_ai"]["current"]
                    provenance = json.loads(roadmap_ai["provenance_json"] or "{}")
                    plan_id = provenance.get("plan_id")
                    if not plan_id:
                        raise Conflict(
                            "The RoadMap revision has no registered plan",
                            code="plan_change_required",
                        )
                    self.plans.publish(
                        conn, loop, plan_id, actor, approval_id=approval_id
                    )
            else:
                kinds = ANALYSIS_SCOPE_KINDS if scope == "analysis" else ROADMAP_SCOPE_KINDS
                for kind in kinds:
                    if kind == "info":
                        continue
                    conn.execute(
                        text(
                            "UPDATE loop_documents SET is_approved = 0,"
                            " status = 'changes_requested' WHERE id = :id"
                        ),
                        {"id": expected[kind]},
                    )
            log_activity(
                conn,
                actor,
                action=f"loop.{scope}_reviewed",
                entity_type="loop",
                entity_id=loop_id,
                changes={"decision": payload.decision, "approval_id": approval_id},
            )
            self.loops.refresh_stage(conn, loop_id)
            approval = one(
                conn, "SELECT * FROM loop_approvals WHERE id = :id", {"id": approval_id}
            )
            return self._serialize_approval(approval)

    def reset(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        scope: str,
        payload: ScopeResetRequest,
    ) -> dict[str, Any]:
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
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            if loop["version"] != payload.version:
                raise VersionConflict(
                    "Loop was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": loop["version"],
                    },
                )
            approval = self.loops.latest_approvals(conn, loop_id).get(scope)
            approved = approval is not None and approval["decision"] == "approved"
            documents = self.loops.document_rows(conn, loop_id)
            kinds = (
                ("analysis_ai", "analysis")
                if scope == "analysis"
                else ("roadmap_ai", "roadmap")
            )
            has_text = any(
                (documents[kind]["current"] or {}).get("content", "").strip() for kind in kinds
            )
            if not has_text and not approved:
                raise Conflict(
                    "There is nothing to reset in this scope",
                    code="nothing_to_reset",
                    details={"scope": scope},
                )
            approval_id = approval["id"] if approved and approval else None
            now = utcnow()
            if approval_id:
                conn.execute(
                    text("UPDATE loop_approvals SET superseded_at = :now WHERE id = :id"),
                    {"now": now, "id": approval_id},
                )

            def current_id(kind: str) -> str | None:
                row = documents[kind]["current"]
                return row["id"] if row else None

            provenance = {"reset_by": actor.actor_id, "reset_approval_id": approval_id}
            # The cleared revisions chain to their inputs, so the scope reads as an ordinary draft
            # rather than as stale text that was left behind.
            if scope == "analysis":
                technical = self._write_revision(
                    conn,
                    loop_id=loop_id,
                    kind="analysis_ai",
                    content="",
                    payload=None,
                    actor=actor,
                    status="draft",
                    sources={"info": current_id("info")},
                    provenance=provenance,
                )
                self._write_revision(
                    conn,
                    loop_id=loop_id,
                    kind="analysis",
                    content="",
                    payload=None,
                    actor=actor,
                    status="draft",
                    sources={"analysis_ai": technical["id"]},
                    provenance=provenance,
                )
            else:
                technical = self._write_revision(
                    conn,
                    loop_id=loop_id,
                    kind="roadmap_ai",
                    content="",
                    payload=None,
                    actor=actor,
                    status="draft",
                    sources={
                        "info": current_id("info"),
                        "analysis_ai": current_id("analysis_ai"),
                        "analysis": current_id("analysis"),
                    },
                    provenance=provenance,
                )
                self._write_revision(
                    conn,
                    loop_id=loop_id,
                    kind="roadmap",
                    content="",
                    payload=None,
                    actor=actor,
                    status="draft",
                    sources={"roadmap_ai": technical["id"]},
                    provenance=provenance,
                )
            cleared = list(kinds)
            self._invalidate_downstream(
                conn, loop_id, "analysis" if scope == "analysis" else "roadmap_ai"
            )
            conn.execute(
                text(
                    "UPDATE loops SET version = version + 1, updated_at = :now WHERE id = :id"
                ),
                {"now": now, "id": loop_id},
            )
            log_activity(
                conn,
                actor,
                action=f"loop.{scope}_reset",
                entity_type="loop",
                entity_id=loop_id,
                changes={"approval_id": approval_id, "cleared": cleared},
            )
            self.loops.refresh_stage(conn, loop_id)
            version = one(conn, "SELECT version FROM loops WHERE id = :id", {"id": loop_id})
            return {
                "scope": scope,
                "approval_id": approval_id,
                "cleared": cleared,
                "version": int(version["version"]),
            }

    def _record_approval(
        self,
        conn: Any,
        *,
        loop_id: str,
        scope: str,
        decision: str,
        actor: ActorContext,
        revisions: dict[str, str],
        documents: dict[str, dict[str, Any]],
        loop_version: int,
        feedback: str,
    ) -> str:
        import uuid

        approval_id = str(uuid.uuid4())
        hashes = {
            kind:
            (documents[kind]["current"]["content_hash"] if documents[kind]["current"] else None)
            for kind in revisions
        }
        conn.execute(
            text(
                "INSERT INTO loop_approvals (id, loop_id, scope, decision, reviewer_actor_id,"
                " reviewer_name, feedback, revisions_json, source_hashes_json, loop_version,"
                " created_at) VALUES (:id, :loop_id, :scope, :decision, :actor_id, :actor_name,"
                " :feedback, :revisions, :hashes, :version, :now)"
            ),
            {
                "id": approval_id,
                "loop_id": loop_id,
                "scope": scope,
                "decision": decision,
                "actor_id": actor.actor_id,
                "actor_name": actor.actor_name,
                "feedback": feedback,
                "revisions": json.dumps(revisions),
                "hashes": json.dumps(hashes),
                "version": loop_version,
                "now": utcnow(),
            },
        )
        conn.execute(
            text(
                "UPDATE loop_approvals SET superseded_at = :now WHERE loop_id = :loop_id"
                " AND scope = :scope AND id != :id AND superseded_at IS NULL"
            ),
            {"now": utcnow(), "loop_id": loop_id, "scope": scope, "id": approval_id},
        )
        return approval_id

    @staticmethod
    def _serialize_approval(row: dict[str, Any]) -> dict[str, Any]:
        entry = dict(row)
        entry["revisions"] = json.loads(entry.pop("revisions_json", "{}") or "{}")
        entry["source_hashes"] = json.loads(entry.pop("source_hashes_json", "{}") or "{}")
        return entry

    # --- generation inputs -----------------------------------------------------

    def collect_context(self, conn: Any, loop: dict[str, Any]) -> dict[str, Any]:
        """Bounded, versioned context for a generation run or an external agent."""
        documents = self.loops.document_rows(conn, loop["id"])
        context: dict[str, Any] = {
            "loop_id": loop["id"],
            "loop_key": loop["key"],
            "loop_name": loop["name"],
            "goal": loop["goal"],
            "stage": loop["stage"],
            "documents": {},
        }
        for kind in DOCUMENT_KINDS:
            current = documents[kind]["current"]
            context["documents"][kind] = (
                {
                    "revision_id": current["id"],
                    "revision_number": current["revision_number"],
                    "content": current["content"],
                    "payload": self._document_payload(current),
                }
                if current
                else None
            )
        plan = self.plans.plan_view(conn, loop, include_readiness=True)
        context["plan"] = {
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
        }
        return context

    def store_generated_analysis(
        self,
        conn: Any,
        loop: dict[str, Any],
        payload: AnalysisPayload,
        actor: ActorContext,
        *,
        run_id: str,
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_analysis(payload)
        info = one(
            conn,
            "SELECT * FROM loop_documents WHERE loop_id = :id AND kind = 'info'"
            " AND is_current = 1",
            {"id": loop["id"]},
        )
        if info is None:
            raise Conflict("Analysis needs a current Info revision", code="document_stale")
        technical = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="analysis_ai",
            content=render_analysis_technical(payload),
            payload=payload.model_dump(),
            actor=actor,
            sources={"info": info["id"]},
            generation_run_id=run_id,
            provenance=provenance,
        )
        human = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="analysis",
            content=render_analysis(payload),
            payload=None,
            actor=actor,
            sources={"analysis_ai": technical["id"], "info": info["id"]},
            generation_run_id=run_id,
            provenance=provenance,
        )
        self._invalidate_downstream(conn, loop["id"], "analysis_ai")
        self.loops.refresh_stage(conn, loop["id"])
        return {"analysis_ai": technical["id"], "analysis": human["id"]}

    def store_generated_roadmap(
        self,
        conn: Any,
        loop: dict[str, Any],
        payload: PlanPayload,
        actor: ActorContext,
        *,
        run_id: str,
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        documents = self.loops.document_rows(conn, loop["id"])
        approvals = self.loops.latest_approvals(conn, loop["id"])
        stale = self.loops._stale_reasons(documents, approvals)
        if not self.loops.analysis_approved(documents, approvals, stale):
            raise Conflict(
                "RoadMap generation requires a current approved analysis",
                code="approval_required",
            )
        info = documents["info"]["current"]
        analysis_ai = documents["analysis_ai"]["current"]
        analysis = documents["analysis"]["current"]
        draft = self.plans.register_draft(conn, loop, payload, actor, source_revisions={})
        canonical = draft["payload"]
        technical = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="roadmap_ai",
            content="```json\n" + json.dumps(canonical, indent=2, ensure_ascii=False) + "\n```\n",
            payload=canonical,
            actor=actor,
            sources={
                "info": info["id"] if info else None,
                "analysis_ai": analysis_ai["id"] if analysis_ai else None,
                "analysis": analysis["id"] if analysis else None,
            },
            generation_run_id=run_id,
            provenance={"plan_id": draft["plan_id"], **provenance},
        )
        human = self._write_revision(
            conn,
            loop_id=loop["id"],
            kind="roadmap",
            content=render_roadmap(canonical),
            payload=None,
            actor=actor,
            sources={"roadmap_ai": technical["id"]},
            generation_run_id=run_id,
            provenance={"plan_id": draft["plan_id"], **provenance},
        )
        self.plans.attach_revisions(
            conn,
            draft["plan_id"],
            roadmap_ai_revision_id=technical["id"],
            roadmap_revision_id=human["id"],
        )
        self._invalidate_downstream(conn, loop["id"], "roadmap_ai")
        self.loops.refresh_stage(conn, loop["id"])
        return {"plan_id": draft["plan_id"], "roadmap_ai": technical["id"], "roadmap": human["id"]}


__all__ = [
    "LoopDocumentService",
    "content_hash",
    "render_analysis",
    "render_analysis_technical",
    "render_roadmap",
]
