"""Completion review and QA handover.

One logical QA Task carries both an AI-oriented and a human-oriented instruction view built from
the same scenario ids. Agents may submit results; only a human accepts QA and finalizes the Loop.

``LoopQaService`` reaches the board database only through the board unit of work and the registry
only through ``BoardChecks``; it takes the clock and the id source as arguments, so every rule here
runs in a unit test without a database.

The cycle and its Task live in ``loop_qa_cycles``, the scenario set in ``loop_qa_instructions``
and its Markdown views in ``loop_qa_render``; this module keeps the service and the import path.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import ApiError, Conflict, NotFound, ValidationFailure, VersionConflict
from ..db.generated.board import LoopApprovalsRow, LoopQaCyclesRow, LoopQaResultsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..schemas.loops import (
    GenerationRequest,
    ImplementationAcceptance,
    QaDecision,
    QaInstructions,
    QaResultSubmission,
    QaScenario,
)
from .idempotency import remember, request_fingerprint, stored_answer
from .lists import BoardChecks
from .loop_history import LoopHistoryService
from .loop_links import LoopWorkflowLinks
from .loop_qa_cycles import (
    QA_PHASE_NAME,
    Entry,
    active_cycle,
    cycle_by_id,
    delivery_baseline,
    delivery_tickets,
    ensure_qa_cycle,
    log_loop_activity,
    serialize_cycle,
)
from .loop_qa_instructions import (
    BLOCKING_RESULT_STATUSES,
    apply_qa_instructions,
    qa_acceptance_blockers,
    read_qa_instructions,
)
from .loop_qa_render import render_qa_ai, render_qa_human, render_qa_task
from .loops import (
    QA_OPEN_STATUSES,
    ensure_execution_allowed,
    ensure_writable,
    refresh_stage,
    require_loop,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


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
        log_loop_activity(repos, actor, action, loop_id, changes, now, new_id=self._new_id)

    # --- helpers ---------------------------------------------------------------

    def ensure_cycle(
        self, repos: BoardRepositories, loop: LoopsRow, actor: ActorContext
    ) -> LoopQaCyclesRow:
        """One active QA cycle per Loop; repeated attempts reuse it."""
        return ensure_qa_cycle(repos, loop, actor, new_id=self._new_id, timestamp=self._now)

    _delivery_tickets = staticmethod(delivery_tickets)
    _delivery_baseline = staticmethod(delivery_baseline)

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
        return apply_qa_instructions(
            repos,
            loop,
            instructions,
            run_id=run_id,
            provenance=provenance,
            new_id=self._new_id,
            timestamp=self._now,
        )

    @staticmethod
    def get_instructions(cycle: LoopQaCyclesRow) -> QaInstructions | None:
        return read_qa_instructions(cycle)

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
                cycle_by_id(cycles, payload.cycle_id) if payload.cycle_id else active_cycle(cycles)
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
            cycle = cycle_by_id(repos.qa.cycles(loop_id), payload.cycle_id)
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
        return qa_acceptance_blockers(repos, cycle, approved_not_applicable)

    # --- views -----------------------------------------------------------------

    _serialize_cycle = staticmethod(serialize_cycle)

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
    "BLOCKING_RESULT_STATUSES",
    "QA_PHASE_NAME",
    "Entry",
    "LoopQaService",
    "QaScenario",
    "render_qa_ai",
    "render_qa_human",
    "render_qa_task",
]
