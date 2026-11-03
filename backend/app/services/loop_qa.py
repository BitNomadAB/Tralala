"""Completion review and QA handover.

One logical QA Task carries both an AI-oriented and a human-oriented instruction view built from
the same scenario ids. Agents may submit results; only a human accepts QA and finalizes the Loop.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import ApiError, Conflict, NotFound, ValidationFailure, VersionConflict
from ..schemas.loops import (
    GenerationRequest,
    ImplementationAcceptance,
    QaDecision,
    QaInstructions,
    QaResultSubmission,
    QaScenario,
)
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import (
    check_idempotency,
    one,
    request_fingerprint,
    rows,
    store_idempotency,
)
from .loop_history import LoopHistoryService
from .loop_identifiers import format_ticket_key
from .loop_links import LoopWorkflowLinks
from .loops import LoopService

QA_PHASE_NAME = "Verification"
BLOCKING_RESULT_STATUSES = {"failed", "blocked", "not_run"}


def render_qa_ai(instructions: QaInstructions) -> str:
    lines = ["## QA instructions (agent view)", ""]
    if instructions.summary:
        lines += [instructions.summary, ""]
    lines.append(
        "Report each scenario id with an outcome of passed, failed, blocked, not_run or "
        "not_applicable. State which of your own tools are available; never infer a pass from "
        "the absence of an error report."
    )
    lines += ["", "Prerequisites and environment must be supplied by whoever runs this task.", ""]
    if instructions.known_risks:
        lines += ["**Known risks**", ""] + [f"- {risk}" for risk in instructions.known_risks] + [""]
    for scenario in instructions.scenarios:
        lines += [f"### {scenario.id} — {scenario.title} ({scenario.kind})", ""]
        if scenario.prerequisites:
            lines += ["Prerequisites:"] + [f"- {item}" for item in scenario.prerequisites] + [""]
        lines += [f"{index}. {step}" for index, step in enumerate(scenario.steps_ai, start=1)]
        lines += ["", f"Expected result: {scenario.expected_result}", ""]
        if scenario.evidence:
            lines += ["Capture:"] + [f"- {item}" for item in scenario.evidence] + [""]
    return "\n".join(lines).strip() + "\n"


def render_qa_human(instructions: QaInstructions) -> str:
    lines = ["## QA instructions (human view)", ""]
    if instructions.summary:
        lines += [instructions.summary, ""]
    for scenario in instructions.scenarios:
        lines += [f"### Scenario {scenario.id}: {scenario.title}", ""]
        if scenario.prerequisites:
            lines += ["Before you start:"] + [f"- {item}" for item in scenario.prerequisites] + [""]
        lines += [f"{index}. {step}" for index, step in enumerate(scenario.steps_human, start=1)]
        lines += ["", f"Expected result: {scenario.expected_result}", ""]
    return "\n".join(lines).strip() + "\n"


def render_qa_task(instructions: QaInstructions, cycle_number: int) -> str:
    return (
        f"QA cycle {cycle_number}. One task, both views, the same scenario ids.\n\n"
        + render_qa_human(instructions)
        + "\n---\n\n"
        + render_qa_ai(instructions)
    )


class LoopQaService:
    def __init__(
        self,
        board_service: BoardService,
        loop_service: LoopService,
        history_service: LoopHistoryService,
        links: LoopWorkflowLinks,
    ) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.loops = loop_service
        self.history = history_service
        self.links = links

    # --- helpers ---------------------------------------------------------------

    def _active_cycle(self, conn: Any, loop_id: str) -> dict[str, Any] | None:
        return one(
            conn,
            "SELECT * FROM loop_qa_cycles WHERE loop_id = :id AND status IN"
            " ('pending','instructions_ready','in_progress')",
            {"id": loop_id},
        )

    def _latest_cycle(self, conn: Any, loop_id: str) -> dict[str, Any] | None:
        return one(
            conn,
            "SELECT * FROM loop_qa_cycles WHERE loop_id = :id ORDER BY cycle_number DESC",
            {"id": loop_id},
        )

    def _qa_phase(self, conn: Any, loop_id: str) -> dict[str, Any]:
        existing = one(
            conn,
            "SELECT * FROM loop_phases WHERE loop_id = :id AND is_qa_phase = 1"
            " ORDER BY number LIMIT 1",
            {"id": loop_id},
        )
        if existing is not None:
            return existing
        plan = one(
            conn, "SELECT * FROM loop_plans WHERE loop_id = :id AND status = 'active'",
            {"id": loop_id}
        )
        if plan is None:
            raise Conflict(
                "A QA Task needs an approved plan before implementation can be accepted",
                code="approval_required",
            )
        number = conn.execute(
            text("SELECT COALESCE(MAX(number), 0) + 1 FROM loop_phases WHERE loop_id = :id"),
            {"id": loop_id},
        ).scalar_one()
        phase_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO loop_phases (id, loop_id, plan_id, number, name, objective,"
                " entry_conditions_json, exit_conditions_json, is_qa_phase, created_at)"
                " VALUES (:id, :loop_id, :plan_id, :number, :name, :objective, '[]', '[]', 1, :now)"
            ),
            {
                "id": phase_id,
                "loop_id": loop_id,
                "plan_id": plan["id"],
                "number": int(number),
                "name": QA_PHASE_NAME,
                "objective": "Verify the delivered work against the approved requirements.",
                "now": utcnow(),
            },
        )
        return one(conn, "SELECT * FROM loop_phases WHERE id = :id", {"id": phase_id})

    def ensure_cycle(self, conn: Any, loop: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        """One active QA cycle per Loop; repeated attempts reuse it."""
        active = self._active_cycle(conn, loop["id"])
        if active is not None:
            return active
        number = conn.execute(
            text(
                "SELECT COALESCE(MAX(cycle_number), 0) + 1 FROM loop_qa_cycles"
                " WHERE loop_id = :id"
            ),
            {"id": loop["id"]},
        ).scalar_one()
        phase = self._qa_phase(conn, loop["id"])
        lists = rows(
            conn,
            "SELECT id FROM lists WHERE loop_id = :id AND archived_at IS NULL"
            " ORDER BY position, id LIMIT 1",
            {"id": loop["id"]},
        )
        if not lists:
            raise Conflict(
                "The Loop has no column for its QA Task", code="loop_required"
            )
        cycle_id = str(uuid4())
        card_id = str(uuid4())
        key = format_ticket_key(loop["key"], "QA", int(phase["number"]), int(number))
        now = utcnow()
        position = conn.execute(
            text("SELECT COALESCE(MAX(position), 0) + 1024 FROM cards WHERE list_id = :id"),
            {"id": lists[0]["id"]},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO cards (id, loop_id, list_id, title, description, position, priority,"
                " created_at, updated_at, version, phase_id, ticket_key, kind, required_actor,"
                " execution_mode, plan_revision_id)"
                " VALUES (:id, :loop_id, :list_id, :title, :description, :position, 'none', :now,"
                " :now, 1, :phase_id, :key, 'qa', 'human', 'normal', :plan_id)"
            ),
            {
                "id": card_id,
                "loop_id": loop["id"],
                "list_id": lists[0]["id"],
                "title": f"QA — {loop['name']}",
                "description": (
                    "QA is outstanding. Instructions are generated from the approved plan and "
                    "the recorded delivery results."
                ),
                "position": int(position),
                "phase_id": phase["id"],
                "key": key,
                "plan_id": loop.get("current_plan_id"),
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO loop_qa_cycles (id, loop_id, cycle_number, status, card_id,"
                " ai_instructions_json, human_instructions_json, instruction_revision,"
                " delivery_baseline, created_at, updated_at)"
                " VALUES (:id, :loop_id, :number, 'pending', :card_id, '{}', '{}', 0,"
                " :baseline, :now, :now)"
            ),
            {
                "id": cycle_id,
                "loop_id": loop["id"],
                "number": int(number),
                "card_id": card_id,
                "baseline": self._delivery_baseline(conn, loop["id"]),
                "now": now,
            },
        )
        conn.execute(
            text(
                "UPDATE loops SET active_qa_cycle_id = :cycle_id, updated_at = :now"
                " WHERE id = :id"
            ),
            {"cycle_id": cycle_id, "now": now, "id": loop["id"]},
        )
        log_activity(
            conn,
            actor,
            action="loop.qa_cycle_created",
            entity_type="loop",
            entity_id=loop["id"],
            changes={"cycle": int(number), "card_id": card_id, "key": key},
        )
        return one(conn, "SELECT * FROM loop_qa_cycles WHERE id = :id", {"id": cycle_id})

    def _delivery_baseline(self, conn: Any, loop_id: str) -> str:
        records = rows(
            conn,
            "SELECT ticket_key, completed_at FROM cards WHERE loop_id = :id"
            " AND kind = 'ticket' ORDER BY ticket_key",
            {"id": loop_id},
        )
        return json.dumps(records, sort_keys=True)

    # --- implementation acceptance ---------------------------------------------

    def open_delivery(self, conn: Any, loop_id: str) -> list[dict[str, Any]]:
        return rows(
            conn,
            "SELECT ticket_key, title, completed_at, archived_at FROM cards"
            " WHERE loop_id = :id AND kind = 'ticket' AND completed_at IS NULL"
            " ORDER BY ticket_key",
            {"id": loop_id},
        )

    def accept_implementation(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: ImplementationAcceptance,
    ) -> dict[str, Any]:
        actor.require_human("Accepting implementation as complete")
        actor.require("loops:review")
        if not payload.accepted:
            raise ValidationFailure("Implementation was not accepted by the reviewer")
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
            self.loops.ensure_execution_allowed(loop)
            open_work = self.open_delivery(conn, loop_id)
            if open_work:
                raise Conflict(
                    "Delivery Tickets are still open",
                    code="ticket_blocked",
                    details={"open": open_work},
                )
            approval_id = self._record_decision(
                conn,
                loop,
                actor,
                scope="implementation",
                decision="approved",
                feedback=payload.note,
                extra={"qa_status": payload.qa_status, "attestation": payload.attestation},
            )
            if payload.qa_status == "passed":
                self._validate_attestation(payload.attestation)
                qa_approval_id = self._record_decision(
                    conn,
                    loop,
                    actor,
                    scope="qa",
                    decision="approved",
                    feedback=payload.note,
                    extra={"attestation": payload.attestation, "external": True},
                )
                conn.execute(
                    text(
                        "UPDATE loops SET implementation_approval_id = :implementation,"
                        " qa_approval_id = :qa, version = version + 1, updated_at = :now"
                        " WHERE id = :id"
                    ),
                    {
                        "implementation": approval_id,
                        "qa": qa_approval_id,
                        "now": utcnow(),
                        "id": loop_id,
                    },
                )
                return self.history.finalize(
                    conn,
                    loop_id,
                    board_id=board_id,
                    actor=actor,
                    qa_approval_id=qa_approval_id,
                    attestation=payload.attestation,
                )
            cycle = self.ensure_cycle(conn, loop, actor)
            conn.execute(
                text(
                    "UPDATE loops SET implementation_approval_id = :approval,"
                    " active_qa_cycle_id = :cycle, version = version + 1, updated_at = :now"
                    " WHERE id = :id"
                ),
                {
                    "approval": approval_id,
                    "cycle": cycle["id"],
                    "now": utcnow(),
                    "id": loop_id,
                },
            )
            log_activity(
                conn,
                actor,
                action="loop.implementation_accepted",
                entity_type="loop",
                entity_id=loop_id,
                changes={"qa_status": payload.qa_status, "cycle": cycle["cycle_number"]},
            )
            self.loops.refresh_stage(conn, loop_id)
        self._request_instructions(actor, board_id, loop_id)
        result = self.cycle(board_id, loop_id)
        result["finalized"] = False
        result["stage"] = self.loops.get(board_id, loop_id)["stage"]
        return result

    def _request_instructions(
        self, actor: ActorContext, board_id: str, loop_id: str
    ) -> None:
        """Start QA instruction generation when a provider exists; never block acceptance."""
        start = self.links.start_generation
        if start is None:
            return
        try:
            start(
                actor,
                board_id,
                loop_id,
                GenerationRequest(purpose="qa"),
            )
        except ApiError:
            # No agent or an active run is not an acceptance failure; the Task shows the state.
            return

    @staticmethod
    def _validate_attestation(attestation: dict[str, Any]) -> None:
        scope = str(attestation.get("scope") or "").strip()
        results = str(attestation.get("results") or "").strip()
        if not scope or not results:
            raise ValidationFailure(
                "A human QA attestation must describe what was tested and the results",
                details={"required": ["scope", "results"]},
            )

    def _record_decision(
        self,
        conn: Any,
        loop: dict[str, Any],
        actor: ActorContext,
        *,
        scope: str,
        decision: str,
        feedback: str,
        extra: dict[str, Any],
    ) -> str:
        approval_id = str(uuid4())
        now = utcnow()
        conn.execute(
            text(
                "INSERT INTO loop_approvals (id, loop_id, scope, decision, reviewer_actor_id,"
                " reviewer_name, feedback, revisions_json, source_hashes_json, loop_version,"
                " created_at) VALUES (:id, :loop_id, :scope, :decision, :actor_id, :actor_name,"
                " :feedback, :revisions, :hashes, :version, :now)"
            ),
            {
                "id": approval_id,
                "loop_id": loop["id"],
                "scope": scope,
                "decision": decision,
                "actor_id": actor.actor_id,
                "actor_name": actor.actor_name,
                "feedback": feedback,
                "revisions": json.dumps(extra),
                "hashes": json.dumps(
                    {"delivery_baseline": self._delivery_baseline(conn, loop["id"])}
                ),
                "version": loop["version"],
                "now": now,
            },
        )
        conn.execute(
            text(
                "UPDATE loop_approvals SET superseded_at = :now WHERE loop_id = :loop_id"
                " AND scope = :scope AND id != :id AND superseded_at IS NULL"
            ),
            {"now": now, "loop_id": loop["id"], "scope": scope, "id": approval_id},
        )
        return approval_id

    # --- instructions ----------------------------------------------------------

    def apply_instructions(
        self,
        conn: Any,
        loop: dict[str, Any],
        instructions: QaInstructions,
        *,
        run_id: str,
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        actor = ActorContext(
            actor_id=str(provenance.get("agent_id") or "generation"),
            actor_type="agent",
            actor_name=str(provenance.get("agent_name") or "QA agent"),
        )
        cycle = self.ensure_cycle(conn, loop, actor)
        revision = int(cycle["instruction_revision"]) + 1
        now = utcnow()
        ai_view = {"markdown": render_qa_ai(instructions), "scenarios": [
            scenario.model_dump() for scenario in instructions.scenarios
        ], "provenance": provenance}
        human_view = {"markdown": render_qa_human(instructions), "scenarios": [
            scenario.model_dump() for scenario in instructions.scenarios
        ]}
        conn.execute(
            text(
                "UPDATE loop_qa_cycles SET status = 'instructions_ready',"
                " ai_instructions_json = :ai, human_instructions_json = :human,"
                " instruction_revision = :revision, generation_run_id = :run_id,"
                " delivery_baseline = :baseline, updated_at = :now WHERE id = :id"
            ),
            {
                "ai": json.dumps(ai_view),
                "human": json.dumps(human_view),
                "revision": revision,
                "run_id": run_id,
                "baseline": self._delivery_baseline(conn, loop["id"]),
                "now": now,
                "id": cycle["id"],
            },
        )
        if cycle["card_id"]:
            conn.execute(
                text(
                    "UPDATE cards SET description = :description, updated_at = :now,"
                    " version = version + 1 WHERE id = :id"
                ),
                {
                    "description": render_qa_task(instructions, cycle["cycle_number"]),
                    "now": now,
                    "id": cycle["card_id"],
                },
            )
        return {
            "cycle_id": cycle["id"],
            "instruction_revision": revision,
            "card_id": cycle["card_id"],
        }

    @staticmethod
    def get_instructions(cycle: dict[str, Any]) -> QaInstructions | None:
        payload = json.loads(cycle["ai_instructions_json"] or "{}")
        scenarios = payload.get("scenarios")
        if not scenarios:
            return None
        return QaInstructions.model_validate(
            {"schema_version": 1, "summary": "", "scenarios": scenarios}
        )

    def submit_instructions(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: QaInstructions
    ) -> dict[str, Any]:
        """A human or an external agent may supply the scenario set without a provider."""
        actor.require("loops:generate")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            self.ensure_cycle(conn, loop, actor)
            self.apply_instructions(
                conn,
                loop,
                payload,
                run_id="",
                provenance={
                    "submitted": True,
                    "submitted_by": actor.actor_id,
                    "agent_id": actor.actor_id,
                    "agent_name": actor.actor_name,
                },
            )
        return self.cycle(board_id, loop_id)

    # --- results ---------------------------------------------------------------

    def submit_results(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: QaResultSubmission,
    ) -> dict[str, Any]:
        actor.require("loops:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            cycle = (
                one(
                    conn,
                    "SELECT * FROM loop_qa_cycles WHERE id = :id AND loop_id = :loop_id",
                    {"id": payload.cycle_id, "loop_id": loop_id},
                )
                if payload.cycle_id
                else self._active_cycle(conn, loop_id)
            )
            if cycle is None:
                raise NotFound("QA cycle not found", code="qa_incomplete")
            if cycle["status"] not in {"pending", "instructions_ready", "in_progress"}:
                raise Conflict(
                    "This QA cycle is closed", code="qa_incomplete",
                    details={"cycle_id": cycle["id"]}
                )
            now = utcnow()
            for result in payload.results:
                conn.execute(
                    text(
                        "INSERT INTO loop_qa_results (id, cycle_id, scenario_id, status, reason,"
                        " evidence, actor_id, actor_type, actor_name, tested_baseline,"
                        " instruction_revision, created_at)"
                        " VALUES (:id, :cycle_id, :scenario_id, :status, :reason, :evidence,"
                        " :actor_id, :actor_type, :actor_name, :baseline, :revision, :now)"
                    ),
                    {
                        "id": str(uuid4()),
                        "cycle_id": cycle["id"],
                        "scenario_id": result.scenario_id,
                        "status": result.status,
                        "reason": result.reason,
                        "evidence": result.evidence,
                        "actor_id": actor.actor_id,
                        "actor_type": actor.actor_type,
                        "actor_name": actor.actor_name,
                        "baseline": result.tested_baseline or cycle["delivery_baseline"],
                        "revision": cycle["instruction_revision"],
                        "now": now,
                    },
                )
            conn.execute(
                text(
                    "UPDATE loop_qa_cycles SET status = 'in_progress', updated_at = :now"
                    " WHERE id = :id"
                ),
                {"now": now, "id": cycle["id"]},
            )
            log_activity(
                conn,
                actor,
                action="loop.qa_results_recorded",
                entity_type="loop",
                entity_id=loop_id,
                changes={"cycle_id": cycle["id"], "scenarios": len(payload.results)},
            )
        return self.cycle(board_id, loop_id)

    # --- final decision --------------------------------------------------------

    def decide(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: QaDecision,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor.require_human("Accepting QA")
        actor.require("loops:review")
        self.board_service.ensure_active(board_id)
        fingerprint = request_fingerprint(
            {"op": "loop.qa_decide", "loop_id": loop_id, "payload": payload.model_dump()}
        )
        with self.boards.session(board_id) as conn:
            cached = check_idempotency(
                conn,
                actor_id=actor.actor_id,
                key=idempotency_key,
                fingerprint=fingerprint,
            )
            if cached is not None:
                return cached
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            cycle = one(
                conn,
                "SELECT * FROM loop_qa_cycles WHERE id = :id AND loop_id = :loop_id",
                {"id": payload.cycle_id, "loop_id": loop_id},
            )
            if loop["completed_at"] is not None or loop["stage"] == "completed":
                if cycle is None or cycle["status"] != "accepted":
                    raise Conflict(
                        "This Loop is completed and read-only",
                        code="loop_read_only",
                        details={"loop_id": loop_id},
                    )
                return self.history.existing(board_id, loop_id)
            self.loops.ensure_writable(loop)
            if loop["version"] != payload.version:
                raise VersionConflict(
                    "Loop was modified by another actor",
                    details={
                        "expected_version": payload.version,
                        "current_version": loop["version"],
                    },
                )
            if cycle is None:
                raise NotFound("QA cycle not found", code="qa_incomplete")
            if cycle["status"] == "accepted":
                return self.history.existing(board_id, loop_id)
            now = utcnow()
            if payload.decision == "rejected":
                conn.execute(
                    text(
                        "UPDATE loop_qa_cycles SET status = 'rejected', decided_at = :now,"
                        " decided_by_actor_id = :actor, decision_note = :note, updated_at = :now"
                        " WHERE id = :id"
                    ),
                    {
                        "now": now,
                        "actor": actor.actor_id,
                        "note": payload.note,
                        "id": cycle["id"],
                    },
                )
                log_activity(
                    conn,
                    actor,
                    action="loop.qa_rejected",
                    entity_type="loop",
                    entity_id=loop_id,
                    changes={"cycle_id": cycle["id"]},
                )
                self.loops.refresh_stage(conn, loop_id)
                rejected = self.cycle(board_id, loop_id)
                store_idempotency(
                    conn,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    result=rejected,
                    ttl_seconds=self.board_service.settings.idempotency_ttl_seconds,
                )
                return rejected
            blockers = self.acceptance_blockers(conn, cycle, payload.not_applicable_approvals)
            if blockers:
                raise Conflict(
                    "QA is incomplete; required scenarios are unresolved",
                    code="qa_incomplete",
                    details={"blockers": blockers},
                )
            for scenario_id in payload.not_applicable_approvals:
                conn.execute(
                    text(
                        "UPDATE loop_qa_results SET disposition_approved_by_actor_id = :actor,"
                        " disposition_note = :note WHERE cycle_id = :cycle AND scenario_id = :sid"
                        " AND status = 'not_applicable'"
                    ),
                    {
                        "actor": actor.actor_id,
                        "note": payload.note,
                        "cycle": cycle["id"],
                        "sid": scenario_id,
                    },
                )
            approval_id = self._record_decision(
                conn,
                loop,
                actor,
                scope="qa",
                decision="approved",
                feedback=payload.note,
                extra={"cycle_id": cycle["id"], "not_applicable": payload.not_applicable_approvals},
            )
            conn.execute(
                text(
                    "UPDATE loop_qa_cycles SET status = 'accepted', decided_at = :now,"
                    " decided_by_actor_id = :actor, decision_note = :note, updated_at = :now"
                    " WHERE id = :id"
                ),
                {"now": now, "actor": actor.actor_id, "note": payload.note, "id": cycle["id"]},
            )
            conn.execute(
                text(
                    "UPDATE loops SET qa_approval_id = :approval, version = version + 1,"
                    " updated_at = :now WHERE id = :id"
                ),
                {"approval": approval_id, "now": now, "id": loop_id},
            )
            log_activity(
                conn,
                actor,
                action="loop.qa_accepted",
                entity_type="loop",
                entity_id=loop_id,
                changes={"cycle_id": cycle["id"], "approval_id": approval_id},
            )
            finalized = self.history.finalize(
                conn,
                loop_id,
                board_id=board_id,
                actor=actor,
                qa_approval_id=approval_id,
                attestation={},
            )
            store_idempotency(
                conn,
                actor_id=actor.actor_id,
                key=idempotency_key,
                fingerprint=fingerprint,
                result=finalized,
                ttl_seconds=self.board_service.settings.idempotency_ttl_seconds,
            )
            return finalized

    def acceptance_blockers(
        self, conn: Any, cycle: dict[str, Any], approved_not_applicable: list[str]
    ) -> list[dict[str, Any]]:
        instructions = self.get_instructions(cycle)
        if instructions is None:
            return [{"scenario_id": None, "reason": "instructions_missing"}]
        latest: dict[str, dict[str, Any]] = {}
        for record in rows(
            conn,
            "SELECT * FROM loop_qa_results WHERE cycle_id = :id"
            " ORDER BY created_at, rowid",
            {"id": cycle["id"]},
        ):
            latest[record["scenario_id"]] = record
        blockers: list[dict[str, Any]] = []
        for scenario in instructions.scenarios:
            result = latest.get(scenario.id)
            if result is None:
                blockers.append({"scenario_id": scenario.id, "reason": "not_run"})
                continue
            if result["status"] == "not_applicable":
                if scenario.id not in approved_not_applicable:
                    blockers.append(
                        {
                            "scenario_id": scenario.id,
                            "reason": "not_applicable_requires_human_approval",
                        }
                    )
                continue
            if result["status"] in BLOCKING_RESULT_STATUSES:
                blockers.append(
                    {
                        "scenario_id": scenario.id,
                        "reason": result["status"],
                        "detail": result["reason"],
                    }
                )
            if result["instruction_revision"] != cycle["instruction_revision"]:
                blockers.append(
                    {"scenario_id": scenario.id, "reason": "instructions_revised"}
                )
        return blockers

    # --- views -----------------------------------------------------------------

    def _serialize_cycle(self, conn: Any, cycle: dict[str, Any]) -> dict[str, Any]:
        results = rows(
            conn,
            "SELECT * FROM loop_qa_results WHERE cycle_id = :id ORDER BY created_at, rowid",
            {"id": cycle["id"]},
        )
        entry = dict(cycle)
        entry["ai_instructions"] = json.loads(entry.pop("ai_instructions_json", "{}") or "{}")
        entry["human_instructions"] = json.loads(
            entry.pop("human_instructions_json", "{}") or "{}"
        )
        entry["attestation"] = json.loads(entry.pop("attestation_json", "{}") or "{}")
        entry["results"] = results
        return entry

    def cycle(self, board_id: str, loop_id: str) -> dict[str, Any]:
        with self.boards.reader(board_id) as conn:
            self.loops.require_loop_row(conn, board_id, loop_id)
            cycle = self._latest_cycle(conn, loop_id)
            if cycle is None:
                raise NotFound("This Loop has no QA cycle", code="qa_incomplete")
            return self._serialize_cycle(conn, cycle)

    def cycle_for(self, conn: Any, loop_id: str) -> dict[str, Any] | None:
        cycle = self._latest_cycle(conn, loop_id)
        return self._serialize_cycle(conn, cycle) if cycle else None


__all__ = [
    "LoopQaService",
    "QaScenario",
    "render_qa_ai",
    "render_qa_human",
    "render_qa_task",
]
