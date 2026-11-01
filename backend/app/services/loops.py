"""Loop ownership, lifecycle stage and machine-readable readiness.

A Loop owns its Kanban, planning documents, Phases and Tickets. A Board is a container of Loops
and its database remains the storage boundary. Every other Loop service takes its ownership
checks and stage computation from here so REST, the UI and WebMCP cannot disagree.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure, VersionConflict
from ..schemas.loops import LoopCancel, LoopCreate, LoopUpdate
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import one, position_for_index, request_fingerprint, rows, run_idempotent
from .loop_identifiers import format_loop_key, loop_prefix

DOCUMENT_KINDS: tuple[str, ...] = ("info", "analysis_ai", "analysis", "roadmap_ai", "roadmap")
OPEN_STAGES = ("draft", "analysis_review", "planning", "roadmap_review", "ready", "in_progress",
               "replanning", "awaiting_qa")
EXECUTION_STAGES = ("ready", "in_progress", "awaiting_qa")


def _decode(raw: Any, fallback: Any) -> Any:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return fallback
    return value if value is not None else fallback


class LoopService:
    def __init__(self, board_service: BoardService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.settings = board_service.settings
        self.plans: Any = None
        self.cards: Any = None

    # --- ownership -------------------------------------------------------------

    def require_loop_row(
        self, conn: Any, board_id: str, loop_id: str, *, include_archived: bool = True
    ) -> dict[str, Any]:
        row = one(conn, "SELECT * FROM loops WHERE id = :id", {"id": loop_id})
        if row is None:
            raise NotFound("Loop not found", code="loop_not_found")
        if not include_archived and row["archived_at"] is not None:
            raise NotFound("Loop not found", code="loop_not_found")
        del board_id
        return row

    def require_loop(self, board_id: str, loop_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        with self.boards.reader(board_id) as conn:
            return self.require_loop_row(conn, board_id, loop_id)

    def ensure_active_loop(self, board_id: str, loop_id: str) -> dict[str, Any]:
        """Loop lookup for mutations: archived and completed Loops are read-only."""
        row = self.require_loop(board_id, loop_id)
        self.ensure_writable(row)
        return row

    @staticmethod
    def ensure_writable(loop_row: dict[str, Any]) -> None:
        if loop_row["completed_at"] is not None or loop_row["stage"] == "completed":
            raise Conflict(
                "This Loop is completed and read-only",
                code="loop_read_only",
                details={"loop_id": loop_row["id"]},
            )
        if loop_row["cancelled_at"] is not None or loop_row["stage"] == "cancelled":
            raise Conflict(
                "This Loop was cancelled",
                code="loop_read_only",
                details={"loop_id": loop_row["id"]},
            )
        if loop_row["archived_at"] is not None:
            raise Conflict(
                "This Loop is archived",
                code="loop_read_only",
                details={"loop_id": loop_row["id"]},
            )

    def ensure_execution_allowed(self, loop_row: dict[str, Any]) -> None:
        stage = loop_row["stage"]
        if stage in EXECUTION_STAGES:
            return
        code = "plan_change_required" if stage in {"replanning", "roadmap_review"} else (
            "approval_required"
        )
        raise Conflict(
            "Delivery work cannot start or complete in this Loop stage",
            code=code,
            details={"stage": stage, "loop_id": loop_row["id"]},
        )

    # --- queries ---------------------------------------------------------------

    def next_sequence(self, conn: Any) -> int:
        value = conn.execute(text("SELECT COALESCE(MAX(sequence), 0) FROM loops")).scalar_one()
        return int(value) + 1

    def loop_defaults(self, conn: Any) -> list[str]:
        row = one(conn, "SELECT column_names_json FROM board_loop_defaults WHERE id = 1")
        names = _decode(row["column_names_json"] if row else None, [])
        return [str(name) for name in names if str(name).strip()]

    def set_loop_defaults(self, conn: Any, names: list[str]) -> None:
        conn.execute(
            text(
                "INSERT INTO board_loop_defaults (id, column_names_json, updated_at)"
                " VALUES (1, :names, :now)"
                " ON CONFLICT(id) DO UPDATE SET column_names_json = excluded.column_names_json,"
                " updated_at = excluded.updated_at"
            ),
            {"names": json.dumps(names), "now": utcnow()},
        )

    def list(
        self,
        board_id: str,
        *,
        include_completed: bool = False,
        stage: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        clauses = ["1 = 1"]
        params: dict[str, Any] = {}
        if not include_archived:
            clauses.append("archived_at IS NULL")
        if not include_completed:
            clauses.append("completed_at IS NULL")
        if stage:
            clauses.append("stage = :stage")
            params["stage"] = stage
        with self.boards.reader(board_id) as conn:
            records = rows(
                conn,
                f"SELECT * FROM loops WHERE {' AND '.join(clauses)}"
                " ORDER BY CASE WHEN completed_at IS NULL THEN 0 ELSE 1 END, sequence, id",
                params,
            )
            return [self.serialize(conn, board_id, row) for row in records]

    def get(self, board_id: str, loop_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            row = self.require_loop_row(conn, board_id, loop_id)
            return self.serialize(conn, board_id, row)

    # --- mutations -------------------------------------------------------------

    def create(
        self,
        actor: ActorContext,
        board_id: str,
        payload: LoopCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        actor.require("loops:write")
        self.board_service.ensure_active(board_id)
        fingerprint = request_fingerprint(
            {"op": "loop.create", "board_id": board_id, "payload": payload.model_dump()}
        )
        loop_id = str(uuid4())
        now = utcnow()

        with self.boards.session(board_id) as conn:
            result: dict[str, Any] = {}

            def action() -> dict[str, Any]:
                sequence = self.next_sequence(conn)
                key = format_loop_key(loop_prefix(payload.name), sequence)
                conn.execute(
                    text(
                        "INSERT INTO loops (id, name, goal, sequence, key_prefix, key, stage,"
                        " version, created_by_actor_id, created_by_actor_type, created_by_name,"
                        " created_at, updated_at) VALUES (:id, :name, :goal, :sequence, :prefix,"
                        " :key, 'draft', 1, :actor_id, :actor_type, :actor_name, :now, :now)"
                    ),
                    {
                        "id": loop_id,
                        "name": payload.name,
                        "goal": payload.goal,
                        "sequence": sequence,
                        "prefix": loop_prefix(payload.name),
                        "key": key,
                        "actor_id": actor.actor_id,
                        "actor_type": actor.actor_type,
                        "actor_name": actor.actor_name,
                        "now": now,
                    },
                )
                names = payload.column_names or self.loop_defaults(conn)
                if not names:
                    names = list(self.settings.list_names)
                for index, name in enumerate(names):
                    conn.execute(
                        text(
                            "INSERT INTO lists (id, loop_id, name, position, created_at,"
                            " updated_at) VALUES (:id, :loop_id, :name, :position, :now, :now)"
                        ),
                        {
                            "id": str(uuid4()),
                            "loop_id": loop_id,
                            "name": name,
                            "position": (index + 1) * 1024,
                            "now": now,
                        },
                    )
                log_activity(
                    conn,
                    actor,
                    action="loop.created",
                    entity_type="loop",
                    entity_id=loop_id,
                    changes={"name": payload.name, "key": key, "columns": names},
                )
                row = self.require_loop_row(conn, board_id, loop_id)
                result.update(self.serialize(conn, board_id, row))
                return result

            loop, replayed = run_idempotent(
                conn,
                actor_id=actor.actor_id,
                key=idempotency_key,
                fingerprint=fingerprint,
                ttl_seconds=self.settings.idempotency_ttl_seconds,
                action=action,
            )
        return loop, replayed

    def update(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: LoopUpdate
    ) -> dict[str, Any]:
        actor.require("loops:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self.require_loop_row(conn, board_id, loop_id)
            self.ensure_writable(existing)
            if existing["version"] != payload.version:
                raise VersionConflict(
                    "Loop was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": existing["version"],
                    },
                )
            updates: dict[str, Any] = {}
            changes: dict[str, Any] = {}
            if payload.name is not None and payload.name != existing["name"]:
                updates["name"] = payload.name
                changes["name"] = {"before": existing["name"], "after": payload.name}
            if payload.goal is not None and payload.goal != existing["goal"]:
                updates["goal"] = payload.goal
                changes["goal"] = {"changed": True}
            if updates:
                assignments = {**updates, "version": existing["version"] + 1,
                "updated_at": utcnow()}
                columns = ", ".join(f"{column} = :{column}" for column in assignments)
                conn.execute(
                    text(f"UPDATE loops SET {columns} WHERE id = :id"),
                    {**assignments, "id": loop_id},
                )
                log_activity(
                    conn,
                    actor,
                    action="loop.updated",
                    entity_type="loop",
                    entity_id=loop_id,
                    changes=changes,
                )
                self.refresh_stage(conn, loop_id)
            row = self.require_loop_row(conn, board_id, loop_id)
            return self.serialize(conn, board_id, row)

    def cancel(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: LoopCancel
    ) -> dict[str, Any]:
        actor.require_human("Cancelling a Loop")
        actor.require("loops:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self.require_loop_row(conn, board_id, loop_id)
            self.ensure_writable(existing)
            if existing["version"] != payload.version:
                raise VersionConflict(
                    "Loop was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": existing["version"],
                    },
                )
            now = utcnow()
            conn.execute(
                text(
                    "UPDATE loops SET stage = 'cancelled', cancelled_at = :now,"
                    " version = version + 1, updated_at = :now WHERE id = :id"
                ),
                {"now": now, "id": loop_id},
            )
            log_activity(
                conn,
                actor,
                action="loop.cancelled",
                entity_type="loop",
                entity_id=loop_id,
                changes={"reason": payload.reason},
            )
            row = self.require_loop_row(conn, board_id, loop_id)
            return self.serialize(conn, board_id, row)

    def archive(self, actor: ActorContext, board_id: str, loop_id: str) -> dict[str, Any]:
        actor.require("loops:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            existing = self.require_loop_row(conn, board_id, loop_id)
            if existing["archived_at"] is None:
                now = utcnow()
                conn.execute(
                    text(
                        "UPDATE loops SET archived_at = :now, version = version + 1,"
                        " updated_at = :now WHERE id = :id"
                    ),
                    {"now": now, "id": loop_id},
                )
                log_activity(
                    conn,
                    actor,
                    action="loop.archived",
                    entity_type="loop",
                    entity_id=loop_id,
                )
            row = self.require_loop_row(conn, board_id, loop_id)
            return self.serialize(conn, board_id, row)

    # --- documents and approvals (read side) ------------------------------------

    def document_rows(self, conn: Any, loop_id: str) -> dict[str, dict[str, Any]]:
        """Current and approved revisions for each of the five slots."""
        records = rows(
            conn,
            "SELECT * FROM loop_documents WHERE loop_id = :id AND (is_current = 1 OR"
            " is_approved = 1) ORDER BY kind, revision_number",
            {"id": loop_id},
        )
        snapshot: dict[str, dict[str, Any]] = {
            kind: {"current": None, "approved": None} for kind in DOCUMENT_KINDS
        }
        for record in records:
            bucket = snapshot.setdefault(record["kind"], {"current": None, "approved": None})
            if record["is_current"]:
                bucket["current"] = record
            if record["is_approved"]:
                bucket["approved"] = record
        return snapshot

    def latest_approvals(self, conn: Any, loop_id: str) -> dict[str, dict[str, Any]]:
        records = rows(
            conn,
            "SELECT * FROM loop_approvals WHERE loop_id = :id ORDER BY created_at DESC, rowid DESC",
            {"id": loop_id},
        )
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            latest.setdefault(record["scope"], record)
        return latest

    def _stale_reasons(
        self,
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
    ) -> dict[str, list[str]]:
        reasons: dict[str, list[str]] = {kind: [] for kind in DOCUMENT_KINDS}
        info = documents["info"]["current"]
        analysis_ai = documents["analysis_ai"]["current"]
        analysis = documents["analysis"]["current"]
        roadmap_ai = documents["roadmap_ai"]["current"]
        roadmap = documents["roadmap"]["current"]

        if analysis_ai is not None:
            if info is None:
                reasons["analysis_ai"].append("info_missing")
            elif analysis_ai["source_info_revision_id"] != info["id"]:
                reasons["analysis_ai"].append("info_changed")
        if analysis is not None:
            if analysis_ai is None:
                reasons["analysis"].append("analysis_ai_missing")
            elif analysis["source_analysis_ai_revision_id"] != analysis_ai["id"]:
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
            if info is not None and roadmap_ai["source_info_revision_id"] != info["id"]:
                reasons["roadmap_ai"].append("info_changed")
            if (
                analysis_ai is not None
                and roadmap_ai["source_analysis_ai_revision_id"] != analysis_ai["id"]
            ):
                reasons["roadmap_ai"].append("analysis_ai_changed")
            if (
                analysis is not None
                and roadmap_ai["source_analysis_revision_id"] != analysis["id"]
            ):
                reasons["roadmap_ai"].append("analysis_changed")
        if roadmap is not None:
            if roadmap_ai is None:
                reasons["roadmap"].append("roadmap_ai_missing")
            elif roadmap["source_roadmap_ai_revision_id"] != roadmap_ai["id"]:
                reasons["roadmap"].append("roadmap_ai_changed")

        current_pair = {
            "analysis": (info, analysis_ai, analysis),
            "roadmap": (info, analysis_ai, analysis),
        }
        for scope, (info_row, ai_row, human_row) in current_pair.items():
            approval = approvals.get(scope)
            if approval is None or approval["decision"] != "approved":
                continue
            reviewed = _decode(approval["revisions_json"], {})
            expected = {
                "info": info_row["id"] if info_row else None,
                "analysis_ai": ai_row["id"] if ai_row else None,
                "analysis": human_row["id"] if human_row else None,
            }
            if scope == "roadmap":
                expected["roadmap_ai"] = roadmap_ai["id"] if roadmap_ai else None
                expected["roadmap"] = roadmap["id"] if roadmap else None
            for kind, revision_id in expected.items():
                if revision_id is None:
                    continue
                if reviewed.get(kind) != revision_id:
                    reasons.setdefault(kind, []).append("approval_superseded")
        return reasons

    def analysis_approved(
        self,
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        stale: dict[str, list[str]],
    ) -> bool:
        approval = approvals.get("analysis")
        if approval is None or approval["decision"] != "approved":
            return False
        if any(stale.get(kind) for kind in ("info", "analysis_ai", "analysis")):
            return False
        return all(
            documents[kind]["current"] is not None
            for kind in ("info", "analysis_ai", "analysis")
        )

    def roadmap_approved(
        self,
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        stale: dict[str, list[str]],
    ) -> bool:
        approval = approvals.get("roadmap")
        if approval is None or approval["decision"] != "approved":
            return False
        if any(stale.get(kind) for kind in DOCUMENT_KINDS if stale.get(kind)):
            return False
        return all(
            documents[kind]["current"] is not None
            for kind in ("info", "analysis_ai", "analysis", "roadmap_ai", "roadmap")
        )

    def compute_stage(
        self,
        loop_row: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        stale: dict[str, list[str]],
        *,
        active_plan: dict[str, Any] | None,
        ticket_done: int,
    ) -> str:
        if loop_row["completed_at"] is not None:
            return "completed"
        if loop_row["cancelled_at"] is not None:
            return "cancelled"
        any_stale = any(stale.get(kind) for kind in DOCUMENT_KINDS)
        roadmap_current = documents["roadmap"]["current"]
        if loop_row["implementation_approval_id"] and not loop_row["qa_approval_id"]:
            if any_stale or not self.analysis_approved(documents, approvals, stale):
                return "replanning"
            return "awaiting_qa"
        if active_plan is not None:
            if any_stale or not self.roadmap_approved(documents, approvals, stale):
                return "replanning"
            return "in_progress" if ticket_done else "ready"
        if self.analysis_approved(documents, approvals, stale):
            if roadmap_current is None:
                return "planning"
            return "planning"
        if documents["analysis"]["current"] is not None:
            return "analysis_review"
        if roadmap_current is not None:
            return "roadmap_review"
        return "draft"

    def refresh_stage(self, conn: Any, loop_id: str) -> str:
        loop_row = one(conn, "SELECT * FROM loops WHERE id = :id", {"id": loop_id})
        if loop_row is None:
            raise NotFound("Loop not found", code="loop_not_found")
        documents = self.document_rows(conn, loop_id)
        approvals = self.latest_approvals(conn, loop_id)
        stale = self._stale_reasons(documents, approvals)
        active_plan = one(
            conn, "SELECT * FROM loop_plans WHERE loop_id = :id AND status = 'active'",
            {"id": loop_id}
        )
        ticket_done = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM cards WHERE loop_id = :id AND kind IN ('ticket','qa')"
                    " AND completed_at IS NOT NULL"
                ),
                {"id": loop_id},
            ).scalar_one()
        )
        stage = self.compute_stage(
            loop_row,
            documents,
            approvals,
            stale,
            active_plan=active_plan,
            ticket_done=ticket_done,
        )
        if stage != loop_row["stage"]:
            conn.execute(
                text("UPDATE loops SET stage = :stage, updated_at = :now WHERE id = :id"),
                {"stage": stage, "now": utcnow(), "id": loop_id},
            )
        return stage

    # --- serialization ---------------------------------------------------------

    def _document_state(
        self,
        kind: str,
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        stale: dict[str, list[str]],
    ) -> dict[str, Any]:
        current = documents[kind]["current"]
        approved = documents[kind]["approved"]
        reasons = list(stale.get(kind, []))
        if current is None:
            state = "empty"
        elif reasons:
            state = "stale"
        elif approved is not None and approved["id"] == current["id"]:
            state = "approved"
        elif current["status"] == "ready_for_review":
            state = "ready_for_review"
        else:
            state = current["status"] if current["status"] != "approved" else "draft"
            scope = "analysis" if kind in {"analysis_ai", "analysis"} else "roadmap"
            latest = approvals.get(scope)
            if (
                latest is not None
                and latest["decision"] == "changes_requested"
                and _decode(latest["revisions_json"], {}).get(kind) == current["id"]
            ):
                state = "changes_requested"
        return {
            "kind": kind,
            "state": state,
            "current": current,
            "approved": approved,
            "stale_reasons": reasons,
        }

    def _plan_summary(self, conn: Any, loop_row: dict[str, Any]) -> dict[str, Any] | None:
        plan = one(
            conn,
            "SELECT * FROM loop_plans WHERE loop_id = :id AND status = 'active'",
            {"id": loop_row["id"]},
        )
        if plan is None:
            return None
        totals = one(
            conn,
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN c.completed_at IS NOT NULL"
            " THEN 1 ELSE 0 END), 0) AS completed FROM loop_plan_items i"
            " LEFT JOIN cards c ON c.plan_item_id = i.id WHERE i.loop_id = :id",
            {"id": loop_row["id"]},
        ) or {"total": 0, "completed": 0}
        phases = conn.execute(
            text("SELECT COUNT(*) FROM loop_phases WHERE loop_id = :id"), {"id": loop_row["id"]}
        ).scalar_one()
        return {
            "plan_id": plan["id"],
            "revision_number": plan["revision_number"],
            "activated_at": plan["activated_at"],
            "phase_count": int(phases),
            "ticket_total": int(totals["total"]),
            "ticket_completed": int(totals["completed"]),
        }

    def _qa_summary(self, conn: Any, loop_row: dict[str, Any]) -> dict[str, Any] | None:
        cycle = one(
            conn,
            "SELECT * FROM loop_qa_cycles WHERE loop_id = :id AND status IN"
            " ('pending','instructions_ready','in_progress')",
            {"id": loop_row["id"]},
        )
        latest = cycle or one(
            conn,
            "SELECT * FROM loop_qa_cycles WHERE loop_id = :id ORDER BY cycle_number DESC",
            {"id": loop_row["id"]},
        )
        if latest is None:
            return None
        return {
            "cycle_id": latest["id"],
            "cycle_number": latest["cycle_number"],
            "status": latest["status"],
            "card_id": latest["card_id"],
            "open": cycle is not None,
        }

    def serialize(
        self, conn: Any, board_id: str, loop_row: dict[str, Any]
    ) -> dict[str, Any]:
        loop_id = loop_row["id"]
        documents = self.document_rows(conn, loop_id)
        approvals = self.latest_approvals(conn, loop_id)
        stale = self._stale_reasons(documents, approvals)
        entry = dict(loop_row)
        entry["board_id"] = board_id
        entry["documents"] = {
            kind: self._document_state(kind, documents, approvals, stale)
            for kind in DOCUMENT_KINDS
        }
        entry["plan"] = self._plan_summary(conn, loop_row)
        entry["qa"] = self._qa_summary(conn, loop_row)
        progress = one(
            conn,
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN completed_at IS NOT NULL"
            " THEN 1 ELSE 0 END), 0) AS completed, COALESCE(SUM(CASE WHEN archived_at IS NOT"
            " NULL AND completed_at IS NULL THEN 1 ELSE 0 END), 0) AS archived"
            " FROM cards WHERE loop_id = :id AND kind IN ('ticket','qa')",
            {"id": loop_id},
        ) or {"total": 0, "completed": 0, "archived": 0}
        entry["progress"] = {
            "ticket_total": int(progress["total"]),
            "ticket_completed": int(progress["completed"]),
            "ticket_archived_incomplete": int(progress["archived"]),
        }
        entry["warnings"] = self._warnings(entry, documents, approvals, stale)
        return entry

    def _warnings(
        self,
        entry: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        stale: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for kind in DOCUMENT_KINDS:
            reasons = stale.get(kind) or []
            if reasons and documents[kind]["current"] is not None:
                warnings.append(
                    {
                        "code": "document_stale",
                        "kind": kind,
                        "reasons": reasons,
                        "message": f"{kind.replace('_', ' ').title()} needs regeneration",
                    }
                )
        if entry["stage"] == "replanning":
            warnings.append(
                {
                    "code": "plan_change_required",
                    "message": "Execution is blocked until a replacement plan is approved",
                }
            )
        if entry["stage"] == "awaiting_qa":
            warnings.append(
                {
                    "code": "qa_incomplete",
                    "message": "QA is outstanding; the Loop cannot be completed yet",
                }
            )
        if not approvals.get("analysis"):
            warnings.append(
                {"code": "approval_required", "message": "Analysis has not been approved"}
            )
        return warnings


    # --- plan and readiness (read side) -----------------------------------------

    def plan(self, board_id: str, loop_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            loop = self.require_loop_row(conn, board_id, loop_id)
            return self.plans.plan_view(conn, loop)

    def readiness(self, board_id: str, loop_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            loop = self.require_loop_row(conn, board_id, loop_id)
            return self.plans.readiness(conn, loop)

    def confirm_human_ticket(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: Any,
    ) -> dict[str, Any]:
        """A human confirms that a human-only Ticket was performed."""
        actor.require_human("Confirming a human-only Ticket")
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self.require_loop_row(conn, board_id, loop_id)
            self.ensure_writable(loop)
            card = one(
                conn,
                "SELECT * FROM cards WHERE id = :id AND loop_id = :loop_id",
                {"id": card_id, "loop_id": loop_id},
            )
            if card is None:
                raise NotFound("Ticket not found")
            if card["version"] != payload.version:
                raise VersionConflict(
                    "Ticket was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": card["version"],
                    },
                )
            if card["required_actor"] != "human":
                raise ValidationFailure(
                    "This Ticket does not require a human action",
                    details={"ticket_id": card_id},
                )
            self.ensure_execution_allowed(loop)
            item = self.plans.readiness_item(conn, loop, card_id)
            if item is not None and not item["ready"]:
                raise Conflict(
                    "This human action is not available yet",
                    code="ticket_blocked",
                    details={"blockers": item["blockers"]},
                )
            now = utcnow()
            conn.execute(
                text(
                    "UPDATE cards SET completed_at = :now, human_confirmed_at = :now,"
                    " human_confirmed_by_actor_id = :actor, updated_at = :now,"
                    " version = version + 1 WHERE id = :id"
                ),
                {"now": now, "actor": actor.actor_id, "id": card_id},
            )
            log_activity(
                conn,
                actor,
                action="card.human_confirmed",
                entity_type="card",
                entity_id=card_id,
                changes={"note": payload.note, "ticket_key": card["ticket_key"]},
            )
            self.refresh_stage(conn, loop_id)
        return self.cards.get(board_id, loop_id, card_id)


def position_key(count: int) -> int:
    """Stable append position for Loop-scoped lists."""
    return (count + 1) * 1024


__all__ = [
    "DOCUMENT_KINDS",
    "EXECUTION_STAGES",
    "OPEN_STAGES",
    "LoopService",
    "position_for_index",
]
