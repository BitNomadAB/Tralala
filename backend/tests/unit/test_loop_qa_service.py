"""LoopQaService on the in-memory fakes: accepting implementation opens one QA cycle with its Task
and asks for instructions, instructions and results move the cycle on, and only a complete,
human-accepted cycle finalizes the Loop."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, VersionConflict
from app.schemas.loops import (
    GenerationRequest,
    ImplementationAcceptance,
    QaDecision,
    QaInstructions,
    QaResultSubmission,
)
from app.services.loop_history import LoopHistoryService
from app.services.loop_links import LoopWorkflowLinks
from app.services.loop_qa import LoopQaService, render_qa_task
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
    phase_row,
    plan_row,
)
from tests.unit.test_loop_history_service import Files, Ids, Index

NOW = "2026-11-03T10:00:00Z"
MOMENT = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
LOOP = "loop-a"
SCOPES = frozenset({"loops:review", "loops:write", "loops:generate"})
ADA = ActorContext(actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=SCOPES)
BOT = ActorContext(actor_id="bot", actor_type="agent", actor_name="Bot", scopes=SCOPES)

INSTRUCTIONS = QaInstructions.model_validate(
    {
        "summary": "Check the export",
        "scenarios": [
            {
                "id": "S1",
                "title": "Export works",
                "kind": "happy_path",
                "steps_ai": ["Call the export"],
                "steps_human": ["Click Export"],
                "expected_result": "A file is written",
            },
            {
                "id": "S2",
                "title": "Bad input is refused",
                "kind": "failure_path",
                "steps_human": ["Upload a broken file"],
                "expected_result": "An error is shown",
            },
        ],
    }
)


class Generation:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, str, str]] = []

    def __call__(
        self, actor: ActorContext, board_id: str, loop_id: str, request: GenerationRequest
    ) -> None:
        self.started.append((actor.actor_id, board_id, loop_id, request.purpose))


def make(
    tmp_path: Path, *, open_ticket: bool = False, qa_phase: bool = False
) -> tuple[LoopQaService, BoardState, Generation]:
    state = BoardState()
    state.loops[LOOP] = loop_row(LOOP, stage="in_progress").__replace__(current_plan_id="plan-1")
    state.plans["plan-1"] = plan_row("plan-1", LOOP)
    state.phases["phase-1"] = phase_row("phase-1", LOOP, "plan-1", 1)
    if qa_phase:
        state.phases["phase-qa"] = phase_row("phase-qa", LOOP, "plan-1", 2).__replace__(
            is_qa_phase=1
        )
    state.lists["list-a"] = list_row("list-a", LOOP, 1)
    state.cards["t-1"] = card_row("t-1", "list-a", LOOP).__replace__(
        kind="ticket", ticket_key="L-1-P01-001", completed_at=None if open_ticket else NOW
    )
    store = FakeBoardUnitOfWork(state)
    ids = Ids()
    history = LoopHistoryService(
        FakeBoardChecks(), store, Files(tmp_path), Index(), clock=lambda: NOW, new_id=ids
    )
    links = LoopWorkflowLinks()
    generation = Generation()
    service = LoopQaService(
        FakeBoardChecks(),
        store,
        history,
        links,
        idempotency_ttl_seconds=3600,
        clock=lambda: MOMENT,
        new_id=ids,
    )
    links.bind(start_generation=generation, apply_qa_instructions=service.apply_instructions)
    return service, state, generation


def accept(service: LoopQaService, **fields: object) -> Mapping[str, object]:
    payload = ImplementationAcceptance.model_validate({"version": 1, **fields})
    return service.accept_implementation(ADA, BOARD_ID, LOOP, payload)


def actions(state: BoardState) -> list[str]:
    return [entry.action for entry in state.activity]


# --- accepting implementation -----------------------------------------------------------------


def test_accepting_implementation_opens_a_qa_cycle_with_its_task(tmp_path: Path) -> None:
    service, state, generation = make(tmp_path)
    result = accept(service, note="done")
    (cycle,) = state.qa_cycles.values()
    task = state.cards[cycle.card_id or ""]
    (qa_phase,) = [phase for phase in state.phases.values() if phase.is_qa_phase == 1]
    loop = state.loops[LOOP]
    assert (cycle.cycle_number, cycle.status, cycle.instruction_revision) == (1, "pending", 0)
    assert (qa_phase.name, qa_phase.number, qa_phase.plan_id) == ("Verification", 2, "plan-1")
    assert (task.kind, task.required_actor, task.priority, task.position) == (
        "qa",
        "human",
        "none",
        2048,
    )
    assert (task.title, task.ticket_key, task.phase_id) == (
        "QA — Loop loop-a",
        "L-1-QA02-001",
        qa_phase.id,
    )
    assert task.plan_revision_id == "plan-1"
    assert json.loads(cycle.delivery_baseline) == [
        {"completed_at": NOW, "ticket_key": "L-1-P01-001"}
    ]
    assert loop.active_qa_cycle_id == cycle.id
    assert loop.version == 2
    (decision,) = state.approvals
    assert (decision.scope, decision.decision, decision.feedback) == (
        "implementation",
        "approved",
        "done",
    )
    assert loop.implementation_approval_id == decision.id
    assert actions(state) == ["loop.qa_cycle_created", "loop.implementation_accepted"]
    assert generation.started == [("actor-1", BOARD_ID, LOOP, "qa")]
    assert (result["id"], result["finalized"], result["stage"]) == (cycle.id, False, loop.stage)
    assert result["results"] == []
    assert "ai_instructions_json" not in result


def test_a_second_acceptance_reuses_the_open_cycle(tmp_path: Path) -> None:
    service, state, _ = make(tmp_path, qa_phase=True)
    accept(service)
    # The fakes hold no planning documents, so the refreshed stage is not an execution stage.
    state.loops[LOOP] = state.loops[LOOP].__replace__(stage="awaiting_qa")
    payload = ImplementationAcceptance(version=2)
    service.accept_implementation(ADA, BOARD_ID, LOOP, payload)
    assert len(state.qa_cycles) == 1
    assert [card.kind for card in state.cards.values()].count("qa") == 1
    assert [phase.id for phase in state.phases.values() if phase.is_qa_phase == 1] == ["phase-qa"]


def test_open_delivery_tickets_block_acceptance(tmp_path: Path) -> None:
    service, state, generation = make(tmp_path, open_ticket=True)
    with pytest.raises(Conflict) as refused:
        accept(service)
    assert refused.value.code == "ticket_blocked"
    assert refused.value.details == {
        "open": [
            {
                "ticket_key": "L-1-P01-001",
                "title": "Card t-1",
                "completed_at": None,
                "archived_at": None,
            }
        ]
    }
    assert state.qa_cycles == {}
    assert state.approvals == []
    assert generation.started == []


def test_unplanned_work_never_blocks_acceptance_and_the_answer_names_what_is_open(
    tmp_path: Path,
) -> None:
    service, state, _ = make(tmp_path)
    state.cards["u-1"] = card_row("u-1", "list-a", LOOP).__replace__(
        kind="manual", ticket_key="L-1-UNP-001", title="Rename the export"
    )
    state.cards["u-2"] = card_row("u-2", "list-a", LOOP).__replace__(
        kind="manual", ticket_key="L-1-UNP-002", completed_at=NOW
    )
    result = accept(service)
    assert result["unplanned_open"] == [
        {
            "id": "u-1",
            "key": "L-1-UNP-001",
            "title": "Rename the export",
            "completed_at": None,
            "archived_at": None,
        }
    ]
    assert len(state.qa_cycles) == 1


def test_acceptance_without_an_active_plan_needs_approval(tmp_path: Path) -> None:
    service, state, _ = make(tmp_path)
    state.plans.clear()
    with pytest.raises(Conflict) as refused:
        accept(service)
    assert refused.value.code == "approval_required"
    assert state.qa_cycles == {}


def test_acceptance_is_a_human_decision_on_the_current_version(tmp_path: Path) -> None:
    service, _, _ = make(tmp_path)
    with pytest.raises(Forbidden) as refused:
        service.accept_implementation(BOT, BOARD_ID, LOOP, ImplementationAcceptance(version=1))
    assert refused.value.code == "human_action_required"
    with pytest.raises(VersionConflict):
        accept(service, version=3)


def test_an_external_qa_pass_finalizes_the_loop(tmp_path: Path) -> None:
    service, state, generation = make(tmp_path)
    attestation = {"scope": "the export", "results": "all passed"}
    record = accept(service, qa_status="passed", attestation=attestation)
    loop = state.loops[LOOP]
    implementation, qa = state.approvals
    assert (implementation.scope, qa.scope) == ("implementation", "qa")
    assert loop.qa_approval_id == qa.id
    assert loop.implementation_approval_id == implementation.id
    assert loop.completed_at == NOW
    (stored,) = state.history.values()
    assert record["id"] == stored.id
    assert state.qa_cycles == {}
    assert generation.started == []


def test_an_external_qa_pass_needs_an_attestation(tmp_path: Path) -> None:
    service, state, _ = make(tmp_path)
    with pytest.raises(Exception) as refused:
        accept(service, qa_status="passed", attestation={"scope": "the export"})
    assert "attestation" in str(refused.value)
    assert state.history == {}


# --- instructions and results -----------------------------------------------------------------


def test_submitted_instructions_fill_both_views_and_the_task(tmp_path: Path) -> None:
    service, state, _ = make(tmp_path)
    accept(service)
    (cycle,) = state.qa_cycles.values()
    task_version = state.cards[cycle.card_id or ""].version
    entry = service.submit_instructions(BOT, BOARD_ID, LOOP, INSTRUCTIONS)
    (cycle,) = state.qa_cycles.values()
    task = state.cards[cycle.card_id or ""]
    assert (cycle.status, cycle.instruction_revision, cycle.generation_run_id) == (
        "instructions_ready",
        1,
        "",
    )
    assert task.description == render_qa_task(INSTRUCTIONS, 1)
    assert task.version == task_version + 1
    ai_view = json.loads(cycle.ai_instructions_json)
    human_view = json.loads(cycle.human_instructions_json)
    assert entry["ai_instructions"] == ai_view
    assert entry["human_instructions"] == human_view
    assert [scenario["id"] for scenario in ai_view["scenarios"]] == ["S1", "S2"]
    assert ai_view["provenance"]["agent_id"] == "bot"
    assert "provenance" not in human_view
    assert service.get_instructions(cycle) is not None


def test_results_move_the_cycle_into_progress(tmp_path: Path) -> None:
    service, state, _ = make(tmp_path)
    accept(service)
    service.submit_instructions(ADA, BOARD_ID, LOOP, INSTRUCTIONS)
    payload = QaResultSubmission.model_validate(
        {"results": [{"scenario_id": "S1", "status": "passed", "evidence": "log"}]}
    )
    entry = service.submit_results(BOT, BOARD_ID, LOOP, payload)
    (cycle,) = state.qa_cycles.values()
    (result,) = state.qa_results
    assert cycle.status == "in_progress"
    assert (result.actor_id, result.instruction_revision, result.tested_baseline) == (
        "bot",
        1,
        cycle.delivery_baseline,
    )
    assert entry["results"] == [
        {
            "id": result.id,
            "cycle_id": cycle.id,
            "scenario_id": "S1",
            "status": "passed",
            "reason": "",
            "evidence": "log",
            "actor_id": "bot",
            "actor_type": "agent",
            "actor_name": "Bot",
            "tested_baseline": cycle.delivery_baseline,
            "instruction_revision": 1,
            "disposition_approved_by_actor_id": None,
            "disposition_note": "",
            "created_at": NOW,
        }
    ]
    assert actions(state)[-1] == "loop.qa_results_recorded"


def test_results_need_an_open_cycle(tmp_path: Path) -> None:
    service, _, _ = make(tmp_path)
    payload = QaResultSubmission.model_validate(
        {"results": [{"scenario_id": "S1", "status": "passed"}]}
    )
    with pytest.raises(NotFound) as missing:
        service.submit_results(BOT, BOARD_ID, LOOP, payload)
    assert missing.value.code == "qa_incomplete"


# --- the decision -----------------------------------------------------------------------------


def _ready(tmp_path: Path, results: list[dict[str, str]]) -> tuple[LoopQaService, BoardState, str]:
    service, state, _ = make(tmp_path)
    accept(service)
    service.submit_instructions(ADA, BOARD_ID, LOOP, INSTRUCTIONS)
    service.submit_results(
        BOT, BOARD_ID, LOOP, QaResultSubmission.model_validate({"results": results})
    )
    (cycle,) = state.qa_cycles.values()
    return service, state, cycle.id


def decision(cycle_id: str, decision: str, **fields: object) -> QaDecision:
    return QaDecision.model_validate(
        {"version": 2, "cycle_id": cycle_id, "decision": decision, **fields}
    )


def test_unresolved_scenarios_block_acceptance(tmp_path: Path) -> None:
    service, state, cycle_id = _ready(
        tmp_path,
        [
            {"scenario_id": "S1", "status": "failed", "reason": "crash"},
            {"scenario_id": "S2", "status": "not_applicable"},
        ],
    )
    with pytest.raises(Conflict) as refused:
        service.decide(ADA, BOARD_ID, LOOP, decision(cycle_id, "accepted"))
    assert refused.value.code == "qa_incomplete"
    assert refused.value.details == {
        "blockers": [
            {"scenario_id": "S1", "reason": "failed", "detail": "crash"},
            {"scenario_id": "S2", "reason": "not_applicable_requires_human_approval"},
        ]
    }
    assert state.loops[LOOP].completed_at is None


def test_accepting_a_complete_cycle_finalizes_the_loop(tmp_path: Path) -> None:
    service, state, cycle_id = _ready(
        tmp_path,
        [
            {"scenario_id": "S1", "status": "passed"},
            {"scenario_id": "S2", "status": "not_applicable", "reason": "no uploads"},
        ],
    )
    record = service.decide(
        ADA,
        BOARD_ID,
        LOOP,
        decision(cycle_id, "accepted", not_applicable_approvals=["S2"], note="ok"),
    )
    cycle = state.qa_cycles[cycle_id]
    loop = state.loops[LOOP]
    qa = state.approvals[-1]
    assert (cycle.status, cycle.decided_by_actor_id, cycle.decision_note) == (
        "accepted",
        "actor-1",
        "ok",
    )
    assert (qa.scope, loop.qa_approval_id, loop.completed_at) == ("qa", qa.id, NOW)
    assert [result.disposition_approved_by_actor_id for result in state.qa_results] == [
        None,
        "actor-1",
    ]
    (stored,) = state.history.values()
    assert record["id"] == stored.id
    assert "loop.qa_accepted" in actions(state)
    again = service.decide(ADA, BOARD_ID, LOOP, decision(cycle_id, "accepted"))
    assert again["id"] == stored.id


def test_a_rejection_closes_the_cycle_and_replays_by_key(tmp_path: Path) -> None:
    service, state, cycle_id = _ready(tmp_path, [{"scenario_id": "S1", "status": "failed"}])
    answer = service.decide(
        ADA, BOARD_ID, LOOP, decision(cycle_id, "rejected", note="redo"), idempotency_key="k1"
    )
    cycle = state.qa_cycles[cycle_id]
    assert (cycle.status, cycle.decision_note) == ("rejected", "redo")
    assert (answer["id"], answer["status"]) == (cycle_id, "rejected")
    assert actions(state)[-1] == "loop.qa_rejected"
    replay = service.decide(
        ADA, BOARD_ID, LOOP, decision(cycle_id, "rejected", note="redo"), idempotency_key="k1"
    )
    assert replay == answer
    assert actions(state).count("loop.qa_rejected") == 1


def test_a_completed_loop_refuses_a_decision_on_an_open_cycle(tmp_path: Path) -> None:
    service, state, cycle_id = _ready(tmp_path, [{"scenario_id": "S1", "status": "passed"}])
    state.loops[LOOP] = state.loops[LOOP].__replace__(stage="completed", completed_at=NOW)
    with pytest.raises(Conflict) as refused:
        service.decide(ADA, BOARD_ID, LOOP, decision(cycle_id, "accepted"))
    assert refused.value.code == "loop_read_only"


def test_revised_instructions_invalidate_earlier_results(tmp_path: Path) -> None:
    service, state, cycle_id = _ready(
        tmp_path,
        [{"scenario_id": "S1", "status": "passed"}, {"scenario_id": "S2", "status": "passed"}],
    )
    service.submit_instructions(ADA, BOARD_ID, LOOP, INSTRUCTIONS)
    with pytest.raises(Conflict) as refused:
        service.decide(ADA, BOARD_ID, LOOP, decision(cycle_id, "accepted"))
    assert refused.value.details == {
        "blockers": [
            {"scenario_id": "S1", "reason": "instructions_revised"},
            {"scenario_id": "S2", "reason": "instructions_revised"},
        ]
    }
    assert state.qa_cycles[cycle_id].instruction_revision == 2
