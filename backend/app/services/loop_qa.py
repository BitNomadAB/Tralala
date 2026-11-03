"""Completion review and QA handover.

One logical QA Task carries both an AI-oriented and a human-oriented instruction view built from
the same scenario ids. Agents may submit results; only a human accepts QA and finalizes the Loop.

``LoopQaService`` reaches the board database only through the board unit of work and the registry
only through ``BoardChecks``; it takes the clock and the id source as arguments, so every rule here
runs in a unit test without a database.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import ApiError, Conflict, NotFound, ValidationFailure, VersionConflict
from ..db.generated.board import (
    CardsRow,
    LoopApprovalsRow,
    LoopPhasesRow,
    LoopQaCyclesRow,
    LoopQaResultsRow,
    LoopsRow,
)
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..schemas.loops import (
    GenerationRequest,
    ImplementationAcceptance,
    QaDecision,
    QaInstructions,
    QaResultSubmission,
    QaScenario,
)
from .activity import activity_entry
from .idempotency import remember, request_fingerprint, stored_answer
from .lists import BoardChecks
from .loop_history import LoopHistoryService
from .loop_identifiers import format_ticket_key
from .loop_links import LoopWorkflowLinks
from .loops import (
    QA_OPEN_STATUSES,
    ensure_execution_allowed,
    ensure_writable,
    refresh_stage,
    require_loop,
)

QA_PHASE_NAME = "Verification"
BLOCKING_RESULT_STATUSES = {"failed", "blocked", "not_run"}
# The instruction and attestation columns are answered parsed, under names without ``_json``.
_JSON_COLUMNS = ("ai_instructions_json", "human_instructions_json", "attestation_json")

type Entry = dict[str, object]


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


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


def _json_object(raw: str) -> object:
    return json.loads(raw or "{}")


def _active(cycles: list[LoopQaCyclesRow]) -> LoopQaCyclesRow | None:
    return next((cycle for cycle in cycles if cycle.status in QA_OPEN_STATUSES), None)


def _cycle_by_id(cycles: list[LoopQaCyclesRow], cycle_id: str) -> LoopQaCyclesRow | None:
    return next((cycle for cycle in cycles if cycle.id == cycle_id), None)


def _check_version(loop: LoopsRow, expected: int) -> None:
    if loop.version != expected:
        raise VersionConflict(
            "Loop was modified by another actor",
            details={"expected_version": expected, "current_version": loop.version},
        )


class LoopQaService:
    def __init__(
        self,
        board_service: BoardChecks,
        store: BoardUnitOfWork,
        history: LoopHistoryService,
        links: LoopWorkflowLinks,
        *,
        idempotency_ttl_seconds: int,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.board_service = board_service
        self.store = store
        self.history = history
        self.links = links
        self.idempotency_ttl_seconds = idempotency_ttl_seconds
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        loop_id: str,
        changes: Mapping[str, object],
        now: str,
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="loop",
                entity_id=loop_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=now,
            )
        )

    # --- helpers ---------------------------------------------------------------

    def _qa_phase(self, repos: BoardRepositories, loop_id: str) -> LoopPhasesRow:
        phases = repos.phases.for_loop(loop_id)
        existing = next((phase for phase in phases if phase.is_qa_phase == 1), None)
        if existing is not None:
            return existing
        plan = repos.plans.active(loop_id)
        if plan is None:
            raise Conflict(
                "A QA Task needs an approved plan before implementation can be accepted",
                code="approval_required",
            )
        phase = LoopPhasesRow(
            id=self._new_id(),
            loop_id=loop_id,
            plan_id=plan.id,
            number=max((other.number for other in phases), default=0) + 1,
            name=QA_PHASE_NAME,
            objective="Verify the delivered work against the approved requirements.",
            entry_conditions_json="[]",
            exit_conditions_json="[]",
            is_qa_phase=1,
            created_at=self._now(),
        )
        repos.phases.add(phase)
        return phase

    def ensure_cycle(
        self, repos: BoardRepositories, loop: LoopsRow, actor: ActorContext
    ) -> LoopQaCyclesRow:
        """One active QA cycle per Loop; repeated attempts reuse it."""
        cycles = repos.qa.cycles(loop.id)
        active = _active(cycles)
        if active is not None:
            return active
        number = max((cycle.cycle_number for cycle in cycles), default=0) + 1
        phase = self._qa_phase(repos, loop.id)
        columns = repos.lists.for_loop(loop.id, include_archived=False)
        if not columns:
            raise Conflict("The Loop has no column for its QA Task", code="loop_required")
        cycle_id = self._new_id()
        card_id = self._new_id()
        key = format_ticket_key(loop.key, "QA", phase.number, number)
        now = self._now()
        repos.cards.add(
            CardsRow(
                id=card_id,
                list_id=columns[0].id,
                title=f"QA — {loop.name}",
                description=(
                    "QA is outstanding. Instructions are generated from the approved plan and "
                    "the recorded delivery results."
                ),
                position=repos.cards.highest_position(columns[0].id) + 1024,
                priority="none",
                due_at=None,
                completed_at=None,
                created_at=now,
                updated_at=now,
                archived_at=None,
                version=1,
                assignee_actor_id=None,
                assignee_type=None,
                assignee_name=None,
                assigned_at=None,
                assigned_by_actor_id=None,
                loop_id=loop.id,
                phase_id=phase.id,
                plan_item_id=None,
                ticket_key=key,
                kind="qa",
                required_actor="human",
                execution_mode="normal",
                human_action_reason="",
                human_instructions="",
                human_confirmed_at=None,
                human_confirmed_by_actor_id=None,
                plan_revision_id=loop.current_plan_id,
            )
        )
        cycle = LoopQaCyclesRow(
            id=cycle_id,
            loop_id=loop.id,
            cycle_number=number,
            status="pending",
            card_id=card_id,
            ai_instructions_json="{}",
            human_instructions_json="{}",
            instruction_revision=0,
            delivery_baseline=self._delivery_baseline(repos, loop.id),
            generation_run_id=None,
            attestation_json="{}",
            created_at=now,
            updated_at=now,
            decided_at=None,
            decided_by_actor_id=None,
            decision_note="",
        )
        repos.qa.add(cycle)
        repos.loops.set_active_qa_cycle(loop.id, cycle_id, now=now)
        self._log(
            repos,
            actor,
            "loop.qa_cycle_created",
            loop.id,
            {"cycle": number, "card_id": card_id, "key": key},
            now,
        )
        return cycle

    @staticmethod
    def _delivery_tickets(repos: BoardRepositories, loop_id: str) -> list[CardsRow]:
        return [card for card in repos.archive.tickets(loop_id) if card.kind == "ticket"]

    def _delivery_baseline(self, repos: BoardRepositories, loop_id: str) -> str:
        records = [
            {"ticket_key": card.ticket_key, "completed_at": card.completed_at}
            for card in self._delivery_tickets(repos, loop_id)
        ]
        return json.dumps(records, sort_keys=True)

    # --- implementation acceptance ---------------------------------------------

    def open_delivery(self, repos: BoardRepositories, loop_id: str) -> list[dict[str, str | None]]:
        return [
            {
                "ticket_key": card.ticket_key,
                "title": card.title,
                "completed_at": card.completed_at,
                "archived_at": card.archived_at,
            }
            for card in self._delivery_tickets(repos, loop_id)
            if card.completed_at is None
        ]

    def accept_implementation(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        payload: ImplementationAcceptance,
    ) -> Entry:
        actor.require_human("Accepting implementation as complete")
        actor.require("loops:review")
        if not payload.accepted:
            raise ValidationFailure("Implementation was not accepted by the reviewer")
        self.board_service.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            _check_version(loop, payload.version)
            ensure_execution_allowed(loop)
            open_work = self.open_delivery(repos, loop_id)
            if open_work:
                raise Conflict(
                    "Delivery Tickets are still open",
                    code="ticket_blocked",
                    details={"open": open_work},
                )
            approval_id = self._record_decision(
                repos,
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
                    repos,
                    loop,
                    actor,
                    scope="qa",
                    decision="approved",
                    feedback=payload.note,
                    extra={"attestation": payload.attestation, "external": True},
                )
                repos.loops.accept_delivery(
                    loop_id,
                    implementation_approval_id=approval_id,
                    qa_approval_id=qa_approval_id,
                    now=self._now(),
                )
                return self.history.finalize(
                    repos,
                    loop_id,
                    board_id=board_id,
                    actor=actor,
                    qa_approval_id=qa_approval_id,
                    attestation=payload.attestation,
                )
            cycle = self.ensure_cycle(repos, loop, actor)
            now = self._now()
            repos.loops.start_qa(
                loop_id, implementation_approval_id=approval_id, cycle_id=cycle.id, now=now
            )
            self._log(
                repos,
                actor,
                "loop.implementation_accepted",
                loop_id,
                {"qa_status": payload.qa_status, "cycle": cycle.cycle_number},
                now,
            )
            refresh_stage(repos, loop_id, now=now)
        self._request_instructions(actor, board_id, loop_id)
        with self.store.reader(board_id) as repos:
            loop = require_loop(repos, loop_id)
            result = self._latest_entry(repos, loop_id)
            result["finalized"] = False
            result["stage"] = loop.stage
        return result

    def _request_instructions(self, actor: ActorContext, board_id: str, loop_id: str) -> None:
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
    def _validate_attestation(attestation: Mapping[str, object]) -> None:
        scope = str(attestation.get("scope") or "").strip()
        results = str(attestation.get("results") or "").strip()
        if not scope or not results:
            raise ValidationFailure(
                "A human QA attestation must describe what was tested and the results",
                details={"required": ["scope", "results"]},
            )

    def _record_decision(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        actor: ActorContext,
        *,
        scope: str,
        decision: str,
        feedback: str,
        extra: Mapping[str, object],
    ) -> str:
        approval_id = self._new_id()
        now = self._now()
        repos.approvals.add(
            LoopApprovalsRow(
                id=approval_id,
                loop_id=loop.id,
                scope=scope,
                decision=decision,
                reviewer_actor_id=actor.actor_id,
                reviewer_name=actor.actor_name,
                feedback=feedback,
                revisions_json=json.dumps(dict(extra)),
                source_hashes_json=json.dumps(
                    {"delivery_baseline": self._delivery_baseline(repos, loop.id)}
                ),
                loop_version=loop.version,
                superseded_at=None,
                created_at=now,
            )
        )
        repos.approvals.supersede_others(loop.id, scope, keep=approval_id, now=now)
        return approval_id

    # --- instructions ----------------------------------------------------------

    def apply_instructions(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        instructions: QaInstructions,
        *,
        run_id: str,
        provenance: Mapping[str, object],
    ) -> Entry:
        actor = ActorContext(
            actor_id=str(provenance.get("agent_id") or "generation"),
            actor_type="agent",
            actor_name=str(provenance.get("agent_name") or "QA agent"),
        )
        cycle = self.ensure_cycle(repos, loop, actor)
        revision = cycle.instruction_revision + 1
        now = self._now()
        ai_view = {
            "markdown": render_qa_ai(instructions),
            "scenarios": [scenario.model_dump() for scenario in instructions.scenarios],
            "provenance": dict(provenance),
        }
        human_view = {
            "markdown": render_qa_human(instructions),
            "scenarios": [scenario.model_dump() for scenario in instructions.scenarios],
        }
        repos.qa.set_instructions(
            cycle.id,
            ai_json=json.dumps(ai_view),
            human_json=json.dumps(human_view),
            revision=revision,
            run_id=run_id,
            baseline=self._delivery_baseline(repos, loop.id),
            now=now,
        )
        card = None if cycle.card_id is None else repos.cards.get(cycle.card_id)
        if card is not None:
            repos.cards.update(
                card.id,
                {
                    "description": render_qa_task(instructions, cycle.cycle_number),
                    "updated_at": now,
                    "version": card.version + 1,
                },
            )
        return {
            "cycle_id": cycle.id,
            "instruction_revision": revision,
            "card_id": cycle.card_id,
        }

    @staticmethod
    def get_instructions(cycle: LoopQaCyclesRow) -> QaInstructions | None:
        payload = json.loads(cycle.ai_instructions_json or "{}")
        scenarios = payload.get("scenarios")
        if not scenarios:
            return None
        return QaInstructions.model_validate(
            {"schema_version": 1, "summary": "", "scenarios": scenarios}
        )

    def submit_instructions(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: QaInstructions
    ) -> Entry:
        """A human or an external agent may supply the scenario set without a provider."""
        actor.require("loops:generate")
        self.board_service.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            self.ensure_cycle(repos, loop, actor)
            self.apply_instructions(
                repos,
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
    ) -> Entry:
        actor.require("loops:write")
        self.board_service.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            cycles = repos.qa.cycles(loop_id)
            cycle = (
                _cycle_by_id(cycles, payload.cycle_id) if payload.cycle_id else _active(cycles)
            )
            if cycle is None:
                raise NotFound("QA cycle not found", code="qa_incomplete")
            if cycle.status not in QA_OPEN_STATUSES:
                raise Conflict(
                    "This QA cycle is closed",
                    code="qa_incomplete",
                    details={"cycle_id": cycle.id},
                )
            now = self._now()
            for result in payload.results:
                repos.qa.add_result(
                    LoopQaResultsRow(
                        id=self._new_id(),
                        cycle_id=cycle.id,
                        scenario_id=result.scenario_id,
                        status=result.status,
                        reason=result.reason,
                        evidence=result.evidence,
                        actor_id=actor.actor_id,
                        actor_type=actor.actor_type,
                        actor_name=actor.actor_name,
                        tested_baseline=result.tested_baseline or cycle.delivery_baseline,
                        instruction_revision=cycle.instruction_revision,
                        disposition_approved_by_actor_id=None,
                        disposition_note="",
                        created_at=now,
                    )
                )
            repos.qa.mark_in_progress(cycle.id, now=now)
            self._log(
                repos,
                actor,
                "loop.qa_results_recorded",
                loop_id,
                {"cycle_id": cycle.id, "scenarios": len(payload.results)},
                now,
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
    ) -> Mapping[str, object]:
        actor.require_human("Accepting QA")
        actor.require("loops:review")
        self.board_service.ensure_active(board_id)
        fingerprint = request_fingerprint(
            {"op": "loop.qa_decide", "loop_id": loop_id, "payload": payload.model_dump()}
        )
        with self.store.writer(board_id) as repos:
            if idempotency_key is not None:
                cached = stored_answer(
                    repos.idempotency,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    now=self._clock(),
                )
                if cached is not None:
                    return cached
            loop = require_loop(repos, loop_id)
            cycle = _cycle_by_id(repos.qa.cycles(loop_id), payload.cycle_id)
            if loop.completed_at is not None or loop.stage == "completed":
                if cycle is None or cycle.status != "accepted":
                    raise Conflict(
                        "This Loop is completed and read-only",
                        code="loop_read_only",
                        details={"loop_id": loop_id},
                    )
                return self.history.existing(board_id, loop_id)
            ensure_writable(loop)
            _check_version(loop, payload.version)
            if cycle is None:
                raise NotFound("QA cycle not found", code="qa_incomplete")
            if cycle.status == "accepted":
                return self.history.existing(board_id, loop_id)
            now = self._now()
            if payload.decision == "rejected":
                repos.qa.decide(
                    cycle.id, status="rejected", actor_id=actor.actor_id, note=payload.note, now=now
                )
                self._log(repos, actor, "loop.qa_rejected", loop_id, {"cycle_id": cycle.id}, now)
                refresh_stage(repos, loop_id, now=now)
                rejected = self._latest_entry(repos, loop_id)
                self._remember(repos, actor, idempotency_key, fingerprint, rejected)
                return rejected
            blockers = self.acceptance_blockers(repos, cycle, payload.not_applicable_approvals)
            if blockers:
                raise Conflict(
                    "QA is incomplete; required scenarios are unresolved",
                    code="qa_incomplete",
                    details={"blockers": blockers},
                )
            for scenario_id in payload.not_applicable_approvals:
                repos.qa.approve_not_applicable(
                    cycle.id, scenario_id, actor_id=actor.actor_id, note=payload.note
                )
            approval_id = self._record_decision(
                repos,
                loop,
                actor,
                scope="qa",
                decision="approved",
                feedback=payload.note,
                extra={"cycle_id": cycle.id, "not_applicable": payload.not_applicable_approvals},
            )
            repos.qa.decide(
                cycle.id, status="accepted", actor_id=actor.actor_id, note=payload.note, now=now
            )
            repos.loops.set_approval(loop_id, "qa_approval_id", approval_id, now=now)
            self._log(
                repos,
                actor,
                "loop.qa_accepted",
                loop_id,
                {"cycle_id": cycle.id, "approval_id": approval_id},
                now,
            )
            finalized = self.history.finalize(
                repos,
                loop_id,
                board_id=board_id,
                actor=actor,
                qa_approval_id=approval_id,
                attestation={},
            )
            self._remember(repos, actor, idempotency_key, fingerprint, finalized)
            return finalized

    def _remember(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        key: str | None,
        fingerprint: str,
        answer: Mapping[str, object],
    ) -> None:
        if key is None:
            return
        remember(
            repos.idempotency,
            actor_id=actor.actor_id,
            key=key,
            fingerprint=fingerprint,
            answer=answer,
            now=self._clock(),
            ttl_seconds=self.idempotency_ttl_seconds,
        )

    def acceptance_blockers(
        self,
        repos: BoardRepositories,
        cycle: LoopQaCyclesRow,
        approved_not_applicable: list[str],
    ) -> list[dict[str, str | None]]:
        instructions = self.get_instructions(cycle)
        if instructions is None:
            return [{"scenario_id": None, "reason": "instructions_missing"}]
        latest = {record.scenario_id: record for record in repos.qa.results(cycle.id)}
        blockers: list[dict[str, str | None]] = []
        for scenario in instructions.scenarios:
            result = latest.get(scenario.id)
            if result is None:
                blockers.append({"scenario_id": scenario.id, "reason": "not_run"})
                continue
            if result.status == "not_applicable":
                if scenario.id not in approved_not_applicable:
                    blockers.append(
                        {
                            "scenario_id": scenario.id,
                            "reason": "not_applicable_requires_human_approval",
                        }
                    )
                continue
            if result.status in BLOCKING_RESULT_STATUSES:
                blockers.append(
                    {
                        "scenario_id": scenario.id,
                        "reason": result.status,
                        "detail": result.reason,
                    }
                )
            if result.instruction_revision != cycle.instruction_revision:
                blockers.append({"scenario_id": scenario.id, "reason": "instructions_revised"})
        return blockers

    # --- views -----------------------------------------------------------------

    @staticmethod
    def _serialize_cycle(repos: BoardRepositories, cycle: LoopQaCyclesRow) -> Entry:
        entry: Entry = {
            name: value for name, value in asdict(cycle).items() if name not in _JSON_COLUMNS
        }
        entry["ai_instructions"] = _json_object(cycle.ai_instructions_json)
        entry["human_instructions"] = _json_object(cycle.human_instructions_json)
        entry["attestation"] = _json_object(cycle.attestation_json)
        entry["results"] = [asdict(result) for result in repos.qa.results(cycle.id)]
        return entry

    def _latest_entry(self, repos: BoardRepositories, loop_id: str) -> Entry:
        entry = self.cycle_for(repos, loop_id)
        if entry is None:
            raise NotFound("This Loop has no QA cycle", code="qa_incomplete")
        return entry

    def cycle(self, board_id: str, loop_id: str) -> Entry:
        with self.store.reader(board_id) as repos:
            require_loop(repos, loop_id)
            return self._latest_entry(repos, loop_id)

    def cycle_for(self, repos: BoardRepositories, loop_id: str) -> Entry | None:
        cycles = repos.qa.cycles(loop_id)
        return self._serialize_cycle(repos, cycles[-1]) if cycles else None


__all__ = [
    "LoopQaService",
    "QaScenario",
    "render_qa_ai",
    "render_qa_human",
    "render_qa_task",
]
