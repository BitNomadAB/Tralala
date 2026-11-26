"""LoopQaService on the in-memory fakes: accepting implementation opens one QA cycle with its Task
and asks for instructions, instructions and results move the cycle on, and only a complete,
human-accepted cycle finalizes the Loop."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

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
from app.services.plan_views import open_delivery, unplanned_tickets
from tests.unit.decision_questions import LAPTOP, changes, question_row, through
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

UNFINISHED = {
    "id": "t-1",
    "ticket_key": "L-1-P01-001",
    "title": "Card t-1",
    "completed_at": None,
    "archived_at": None,
}
"""The delivery Ticket ``make(open_ticket=True)`` leaves open, as the service names it."""

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
    assert refused.value.details == {"open": [UNFINISHED]}
    assert state.qa_cycles == {}
    assert state.approvals == []
    assert generation.started == []


def test_a_person_may_accept_the_implementation_without_the_unfinished_tickets(
    tmp_path: Path,
) -> None:
    service, state, generation = make(tmp_path, open_ticket=True)
    result = accept(service, accept_unfinished=True, note="the rest is dropped")
    # The Ticket is left as it was: accepting never completes it.
    assert state.cards["t-1"].completed_at is None
    (cycle,) = state.qa_cycles.values()
    (decision,) = state.approvals
    assert (decision.scope, decision.decision) == ("implementation", "approved")
    # The decision and the Loop's activity name what was left unfinished.
    assert json.loads(decision.revisions_json) == {
        "qa_status": "not_tested",
        "attestation": {},
        "unfinished": ["L-1-P01-001"],
    }
    assert actions(state) == [
        "loop.accepted_unfinished",
        "loop.qa_cycle_created",
        "loop.implementation_accepted",
    ]
    named = state.activity[0]
    assert (named.actor_id, json.loads(named.changes_json)) == (
        "actor-1",
        {"tickets": ["L-1-P01-001"]},
    )
    assert json.loads(cycle.delivery_baseline) == [
        {"completed_at": None, "ticket_key": "L-1-P01-001"}
    ]
    assert generation.started == [("actor-1", BOARD_ID, LOOP, "qa")]
    assert (result["finalized"], result["unfinished"]) == (False, [UNFINISHED])


def test_accepting_without_unfinished_tickets_names_none_when_all_are_done(
    tmp_path: Path,
) -> None:
    service, state, _ = make(tmp_path)
    result = accept(service, accept_unfinished=True)
    (decision,) = state.approvals
    assert json.loads(decision.revisions_json) == {"qa_status": "not_tested", "attestation": {}}
    assert actions(state) == ["loop.qa_cycle_created", "loop.implementation_accepted"]
    assert result["unfinished"] == []


def test_leaving_tickets_unfinished_is_a_persons_decision(tmp_path: Path) -> None:
    service, state, _ = make(tmp_path, open_ticket=True)
    payload = ImplementationAcceptance(version=1, accept_unfinished=True)
    with pytest.raises(Forbidden) as refused:
        service.accept_implementation(BOT, BOARD_ID, LOOP, payload)
    assert refused.value.code == "human_action_required"
    assert state.approvals == []
    assert state.activity == []


def test_an_external_qa_pass_completes_the_loop_past_its_unfinished_tickets(
    tmp_path: Path,
) -> None:
    service, state, _ = make(tmp_path, open_ticket=True)
    state.cards["t-2"] = card_row("t-2", "list-a", LOOP).__replace__(
        kind="ticket", ticket_key="L-1-P01-002", completed_at=NOW
    )
    attestation = {"scope": "the export", "results": "all passed"}
    record = accept(service, qa_status="passed", attestation=attestation, accept_unfinished=True)
    loop = state.loops[LOOP]
    assert loop.completed_at == NOW
    assert record["unfinished"] == [UNFINISHED]
    # Completing the Loop does not complete the Ticket: it stays not done, and so reads not_done.
    assert state.cards["t-1"].completed_at is None
    (stored,) = state.history.values()
    envelope = json.loads(stored.envelope_json)
    assert {
        ticket["key"]: ticket["disposition"] for ticket in envelope["delivery"]["tickets"]
    } == {"L-1-P01-001": "open", "L-1-P01-002": "completed"}
    # The snapshot holds the decision that left it, and the activity that names it.
    implementation = next(
        entry for entry in envelope["human_decisions"] if entry["scope"] == "implementation"
    )
    assert implementation["revisions"]["unfinished"] == ["L-1-P01-001"]
    assert [
        entry["changes"]
        for entry in envelope["activity"]
        if entry["action"] == "loop.accepted_unfinished"
    ] == [{"tickets": ["L-1-P01-001"]}]


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
            "workplace": "unknown",
            "waiting_for": "nothing",
            "state": "ready",
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


# --- a Loop without a plan --------------------------------------------------------------------

UNP_OPEN = {
    "id": "u-2",
    "ticket_key": "L-1-UNP-002",
    "title": "Card u-2",
    "completed_at": None,
    "archived_at": None,
}
"""The Ticket ``make_without_plan(open_ticket=True)`` leaves open, as the service names it."""


def store_of(service: LoopQaService) -> FakeBoardUnitOfWork:
    store = service.store
    assert isinstance(store, FakeBoardUnitOfWork)
    return store


def make_without_plan(
    tmp_path: Path, *, open_ticket: bool = False, stage: str = "in_progress"
) -> tuple[LoopQaService, BoardState, Generation, FakeBoardUnitOfWork]:
    """A Loop that runs its Tickets without a plan: no plan and no Phase, and outside ``draft``
    its manual Tickets, one completed, one archived and, with ``open_ticket``, one open."""
    service, state, generation = make(tmp_path)
    state.loops[LOOP] = loop_row(LOOP, stage=stage)
    state.plans.clear()
    state.phases.clear()
    state.cards.clear()
    if stage != "draft":
        state.cards["u-1"] = card_row("u-1", "list-a", LOOP).__replace__(
            kind="manual", ticket_key="L-1-UNP-001", completed_at=NOW
        )
        state.cards["u-3"] = card_row("u-3", "list-a", LOOP, archived_at=NOW).__replace__(
            kind="manual", ticket_key="L-1-UNP-003"
        )
    if open_ticket:
        state.cards["u-2"] = card_row("u-2", "list-a", LOOP).__replace__(
            kind="manual", ticket_key="L-1-UNP-002"
        )
    return service, state, generation, store_of(service)


def test_a_loop_without_a_plan_closes_in_one_decision(tmp_path: Path) -> None:
    service, state, generation, store = make_without_plan(tmp_path)
    # What the payload says of QA is not read: such a Loop has no QA to report on.
    record = accept(service, note="small fix", qa_status="passed", attestation={})
    loop = state.loops[LOOP]
    (decision,) = state.approvals
    assert (decision.scope, decision.decision, decision.feedback) == (
        "implementation",
        "approved",
        "small fix",
    )
    assert json.loads(decision.revisions_json) == {"without_plan": True}
    assert (loop.stage, loop.completed_at, loop.version) == ("completed", NOW, 3)
    assert (loop.implementation_approval_id, loop.qa_approval_id) == (decision.id, None)
    # No QA cycle, no QA Task, no QA decision and no request for QA instructions.
    assert (state.qa_cycles, loop.active_qa_cycle_id) == ({}, None)
    assert [card.kind for card in state.cards.values()] == ["manual", "manual"]
    assert generation.started == []
    # The decision and the history are one write.
    assert (store.commits, store.rollbacks) == (1, 0)
    (stored,) = state.history.values()
    assert (stored.qa_status, loop.history_id, record["id"]) == ("not_run", stored.id, stored.id)
    envelope = json.loads(stored.envelope_json)
    assert (envelope["loop"]["without_plan"], envelope["loop"]["stage"]) == (True, "in_progress")
    assert (envelope["qa"], envelope["qa_attestation"]) == ({"cycles": [], "results": []}, {})
    assert {
        ticket["key"]: (ticket["kind"], ticket["disposition"])
        for ticket in envelope["delivery"]["tickets"]
    } == {"L-1-UNP-001": ("manual", "completed"), "L-1-UNP-003": ("manual", "archived")}
    assert (record["without_plan"], record["qa_status"]) == (True, "not_run")
    assert (record["unfinished"], record["unplanned_open"]) == ([], [])
    assert actions(state) == ["loop.completed"]


def test_an_open_ticket_holds_up_closing_a_loop_without_a_plan(tmp_path: Path) -> None:
    service, state, generation, store = make_without_plan(tmp_path, open_ticket=True)
    with pytest.raises(Conflict) as refused:
        accept(service)
    assert refused.value.code == "ticket_blocked"
    # Only the open Ticket is named: neither the completed nor the archived one.
    assert refused.value.details == {"open": [UNP_OPEN]}
    assert (state.approvals, state.history, state.activity) == ([], {}, [])
    assert state.loops[LOOP].completed_at is None
    assert (store.commits, store.rollbacks, generation.started) == (0, 1, [])


def test_a_person_closes_a_loop_without_a_plan_without_its_open_tickets(tmp_path: Path) -> None:
    service, state, _, store = make_without_plan(tmp_path, open_ticket=True)
    # A Ticket from before the keys is named by its id.
    state.cards["u-0"] = card_row("u-0", "list-a", LOOP).__replace__(kind="manual")
    keyless = {**UNP_OPEN, "id": "u-0", "ticket_key": None, "title": "Card u-0"}
    record = accept(service, accept_unfinished=True, note="the rest is dropped")
    loop = state.loops[LOOP]
    assert loop.completed_at == NOW
    # Closing the Loop never completes a Ticket: each stays as it was, and so reads not_done.
    assert (state.cards["u-0"].completed_at, state.cards["u-2"].completed_at) == (None, None)
    (decision,) = state.approvals
    assert json.loads(decision.revisions_json) == {
        "without_plan": True,
        "unfinished": ["u-0", "L-1-UNP-002"],
    }
    assert actions(state) == ["loop.accepted_unfinished", "loop.completed"]
    assert json.loads(state.activity[0].changes_json) == {"tickets": ["u-0", "L-1-UNP-002"]}
    with store.reader(BOARD_ID) as repos:
        states = {ticket["id"]: ticket["state"] for ticket in unplanned_tickets(repos, loop)}
    assert states == {"u-0": "not_done", "u-1": None, "u-2": "not_done", "u-3": "not_done"}
    (stored,) = state.history.values()
    envelope = json.loads(stored.envelope_json)
    assert {
        ticket["id"]: ticket["disposition"] for ticket in envelope["delivery"]["tickets"]
    } == {"u-0": "not_done", "u-1": "completed", "u-2": "not_done", "u-3": "archived"}
    (implementation,) = envelope["human_decisions"]
    assert implementation["revisions"] == {
        "without_plan": True,
        "unfinished": ["u-0", "L-1-UNP-002"],
    }
    # The open Tickets are named once, as what was left; never again as work outside a plan.
    assert (record["unfinished"], record["unplanned_open"]) == ([keyless, UNP_OPEN], [])


def test_closing_a_loop_without_a_plan_is_a_persons_decision_on_its_version(
    tmp_path: Path,
) -> None:
    service, state, _, store = make_without_plan(tmp_path, open_ticket=True)
    payload = ImplementationAcceptance(version=1, accept_unfinished=True)
    with pytest.raises(Forbidden) as refused:
        service.accept_implementation(BOT, BOARD_ID, LOOP, payload)
    assert refused.value.code == "human_action_required"
    with pytest.raises(VersionConflict):
        accept(service, version=3, accept_unfinished=True)
    assert (state.approvals, state.history, state.activity) == ([], {}, [])
    assert state.loops[LOOP].completed_at is None
    assert store.commits == 0


def test_a_loop_without_a_plan_or_tickets_has_nothing_to_close(tmp_path: Path) -> None:
    service, state, _, _ = make_without_plan(tmp_path, stage="draft")
    with pytest.raises(Conflict) as refused:
        accept(service)
    assert refused.value.code == "approval_required"
    assert (state.approvals, state.history, state.qa_cycles) == ([], {}, {})


def test_open_delivery_of_a_loop_without_a_plan_is_its_open_tickets(tmp_path: Path) -> None:
    _, state, _, store = make_without_plan(tmp_path, open_ticket=True)
    # A Ticket a plan once published does not count in a Loop that runs without one.
    state.cards["t-9"] = card_row("t-9", "list-a", LOOP).__replace__(
        kind="ticket", ticket_key="L-1-P01-009"
    )
    with store.reader(BOARD_ID) as repos:
        assert open_delivery(repos, state.loops[LOOP]) == [UNP_OPEN]
        # With a plan, the same Loop's open delivery is the plan's Tickets, as before.
        planned = state.loops[LOOP].__replace__(current_plan_id="plan-1")
        assert [ticket["id"] for ticket in open_delivery(repos, planned)] == ["t-9"]


# --- the implementation and QA a coding session asked for ----------------------------------------

ASKED = "2026-11-03T09:50:00Z"


def _logged(state: BoardState, action: str) -> dict[str, JsonValue]:
    (row,) = [entry for entry in state.activity if entry.action == action]
    return changes(row)


def test_an_acceptance_that_answers_a_question_names_the_key_in_the_decision(
    tmp_path: Path,
) -> None:
    service, state, _ = make(tmp_path)
    state.activity.append(question_row("q-1", "implementation", ("loop", LOOP), at=ASKED))
    accept(service)
    (implementation,) = [row for row in state.approvals if row.scope == "implementation"]
    extra = json.loads(implementation.revisions_json)
    assert extra["asked_through"] == through(LAPTOP)
    assert _logged(state, "loop.implementation_accepted")["asked_through"] == through(LAPTOP)
    assert state.comments == {}


def test_an_acceptance_nobody_asked_for_is_recorded_as_before(tmp_path: Path) -> None:
    service, state, _ = make(tmp_path)
    state.activity.append(question_row("q-1", "qa", ("loop", LOOP), at=ASKED))
    accept(service)
    (implementation,) = [row for row in state.approvals if row.scope == "implementation"]
    assert "asked_through" not in json.loads(implementation.revisions_json)
    assert "asked_through" not in _logged(state, "loop.implementation_accepted")


@pytest.mark.parametrize("outcome", ["accepted", "rejected"])
def test_a_qa_decision_that_answers_a_question_names_the_key(tmp_path: Path, outcome: str) -> None:
    service, state, cycle_id = _ready(
        tmp_path,
        [
            {"scenario_id": "S1", "status": "passed"},
            {"scenario_id": "S2", "status": "passed"},
        ],
    )
    state.activity.append(question_row("q-1", "qa", ("loop", LOOP), at=NOW))
    service.decide(ADA, BOARD_ID, LOOP, decision(cycle_id, outcome))
    assert _logged(state, f"loop.qa_{outcome}")["asked_through"] == through(LAPTOP)
    if outcome == "accepted":
        qa = state.approvals[-1]
        assert json.loads(qa.revisions_json)["asked_through"] == through(LAPTOP)
    assert state.comments == {}


def test_a_qa_decision_nobody_asked_for_is_recorded_as_before(tmp_path: Path) -> None:
    service, state, cycle_id = _ready(
        tmp_path,
        [
            {"scenario_id": "S1", "status": "passed"},
            {"scenario_id": "S2", "status": "passed"},
        ],
    )
    service.decide(ADA, BOARD_ID, LOOP, decision(cycle_id, "rejected"))
    assert _logged(state, "loop.qa_rejected") == {"cycle_id": cycle_id}
