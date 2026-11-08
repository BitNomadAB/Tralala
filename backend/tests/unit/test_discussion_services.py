"""The discussion round engine, run control and discussions on the in-memory fakes, with the agent
call replaced by a scripted answer: no model, no network, no database."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeIs

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.db.generated.board import DiscussionParticipantsRow, DiscussionRunsRow
from app.schemas.discussions import DiscussionCreate, DiscussionMessageCreate, DiscussionRunStart
from app.services.agents import AgentService, RoleSnapshot
from app.services.discussion_ask import AnswerCall
from app.services.discussions import (
    DiscussionService,
    RoleSnapshots,
    requests_agent_reply,
)
from app.services.orchestrator import Orchestrator, RoundOutcome, usage_tokens
from app.services.runs import RunService, classify
from app.services.runtime import Completion, ResponseSchema
from app.services.runtime_tools import Message
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    discussion_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import RegistryState, agent_row, board_row, registry_unit_of_work

NOW = "2026-11-03T10:00:00Z"
THREAD = "thread-1"
CARD = "card-1"
ADA = ActorContext(
    actor_id="actor-1",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"discussions:write", "discussions:admin"}),
)
BOT = ActorContext(
    actor_id="agent-key", actor_type="agent", actor_name="Bot", scopes=frozenset(ADA.scopes)
)


def agent_service_fits(service: AgentService) -> RoleSnapshots:
    """Never called: pyright proves that AgentService gives discussions their role snapshots."""
    return service


def runtime_fits() -> AnswerCall:
    """Never called: pyright proves that runtime.call_completion fits the engine's agent call."""
    from app.services import runtime

    return runtime.call_completion


class Ids:
    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"id-{self.issued}"


@dataclass
class ScriptedAgents:
    """Answers per agent id, in order; a missing script means the call failed. Every call's
    messages and schema are kept, so a test reads what a repair asked."""

    scripts: dict[str, list[Completion]] = field(default_factory=dict[str, list[Completion]])
    calls: list[str] = field(default_factory=list[str])
    prompts: list[Sequence[Message]] = field(default_factory=list[Sequence[Message]])
    schemas: list[ResponseSchema | None] = field(default_factory=list[ResponseSchema | None])

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: Sequence[Message],
        response_schema: ResponseSchema | None,
    ) -> Completion:
        del settings, system_prompt
        agent_id = str(agent_row["id"])
        self.calls.append(agent_id)
        self.prompts.append(messages)
        self.schemas.append(response_schema)
        script = self.scripts.get(agent_id) or []
        if not script:
            return {"ok": False, "error": "unreachable", "text": "", "tool_calls": []}
        return script.pop(0)


def said(text: str, tokens: int = 10) -> Completion:
    """A provider's answer with this text."""
    return {
        "ok": True,
        "error": None,
        "text": text,
        "tool_calls": [],
        "model": "m",
        "usage": {"total_tokens": tokens},
    }


def answer(
    text: str, position: str = "yes", tokens: int = 10, **fields: object
) -> Completion:
    """An answer in the standard: the position, a recommendation and ``text`` as its reasoning."""
    payload: dict[str, object] = {
        "position": position,
        "recommendation": f"Recommend: {text}",
        "confidence": "high",
        "reasoning": text,
    }
    if position == "yes_with_conditions":
        payload["conditions"] = ["A rollback exists."]
    if position == "unclear":
        payload["open_questions"] = ["Who owns it?"]
    payload.update(fields)
    return said(json.dumps(payload), tokens)


@dataclass
class Settings:
    discussion_max_rounds: int = 4
    discussion_token_budget: int = 0
    discussion_time_budget_seconds: int = 0


def participant(agent_id: str, joined_at: str = NOW) -> DiscussionParticipantsRow:
    return DiscussionParticipantsRow(
        id=f"p-{agent_id}",
        discussion_id=THREAD,
        participant_id=agent_id,
        participant_type="agent",
        display_name=agent_id.title(),
        role_template_id=None,
        role_template_name="Reviewer",
        role_template_updated_at=None,
        role_source="default",
        system_prompt="Review it.",
        system_prompt_sha256="0" * 64,
        snapshot_at=joined_at,
        joined_at=joined_at,
    )


def run_row(
    run_id: str = "run-1", *, status: str = "running", requested: int = 1
) -> DiscussionRunsRow:
    return DiscussionRunsRow(
        id=run_id,
        discussion_id=THREAD,
        status=status,
        autonomy=0,
        rounds_requested=requested,
        rounds_completed=0,
        token_budget=None,
        tokens_used=0,
        time_budget_seconds=None,
        elapsed_ms=0,
        stop_reason=None,
        error=None,
        started_by_actor_id="actor-1",
        started_by_type="user",
        started_by_name="Ada",
        created_at=NOW,
        started_at=NOW,
        finished_at=None,
    )


@dataclass
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    registry: RegistryState
    agents: ScriptedAgents
    engine: Orchestrator
    runs: RunService
    discussions: DiscussionService


class Snapshots:
    def role_snapshot(self, agent_id: str) -> RoleSnapshot:
        return {
            "agent_id": agent_id,
            "agent_name": agent_id,
            "role_template_id": None,
            "role_template_name": "Reviewer",
            "role_template_updated_at": None,
            "role_source": "default",
            "system_prompt": f"You are {agent_id}.",
            "system_prompt_sha256": "0" * 64,
            "snapshot_at": NOW,
        }


def world(*agent_ids: str, mode: str = "manual") -> World:
    state = BoardState()
    state.loops["loop-a"] = loop_row("loop-a")
    state.lists["list-a"] = list_row("list-a", "loop-a", 1)
    state.cards[CARD] = card_row(CARD, "list-a", "loop-a")
    thread = discussion_row(THREAD, card_id=CARD)
    state.discussions[THREAD] = thread.__replace__(mode=mode)
    for agent_id in agent_ids:
        state.participants.append(participant(agent_id))
    registry = RegistryState()
    registry.boards[BOARD_ID] = board_row(BOARD_ID, name="Board")
    for agent_id in agent_ids:
        registry.agents[agent_id] = agent_row(agent_id, name=agent_id.title())
    store = FakeBoardUnitOfWork(state)
    registry_store = registry_unit_of_work(registry)
    agents = ScriptedAgents()
    ids = Ids()
    engine = Orchestrator(
        object(),
        store,
        registry_store,
        call_completion=agents,
        clock=lambda: NOW,
        new_id=ids,
        monotonic=lambda: 0.0,
    )
    checks = FakeBoardChecks()
    runs = RunService(Settings(), checks, engine, store, clock=lambda: NOW, new_id=ids)
    discussions = DiscussionService(
        checks, Snapshots(), store, registry_store, clock=lambda: NOW, new_id=ids
    )
    discussions.runs = runs
    return World(state, store, registry, agents, engine, runs, discussions)


def round_of(w: World, run_id: str = "run-1", round_number: int = 1) -> RoundOutcome:
    if run_id not in w.state.runs:
        w.state.runs[run_id] = run_row(run_id)
    return w.engine.run_round(
        BOARD_ID, THREAD, run_id=run_id, round_number=round_number, token_budget=None
    )


# --- the round engine ----------------------------------------------------------------------------


def test_usage_tokens_reads_the_total_or_adds_the_parts() -> None:
    assert usage_tokens({"usage": {"total_tokens": 7}}) == 7
    assert usage_tokens({"usage": {"input_tokens": 2, "output_tokens": 3}}) == 5
    assert usage_tokens({"usage": None}) == 0
    assert usage_tokens({}) == 0


def test_a_round_stores_each_answer_and_vote_and_counts_its_tokens() -> None:
    w = world("alpha", "beta")
    w.agents.scripts = {"alpha": [answer("Yes.", tokens=5)], "beta": [answer("Agreed.", tokens=6)]}
    outcome = round_of(w)
    assert (outcome["answers"], outcome["repeats"], outcome["tokens"]) == (2, 0, 11)
    assert [m.author_actor_id for m in w.state.discussion_messages] == ["alpha", "beta"]
    assert [v.position for v in w.state.votes] == ["yes", "yes"]
    assert [m.content for m in w.state.discussion_messages] == ["Yes.", "Agreed."]
    assert w.state.runs["run-1"].tokens_used == 11
    assert outcome["unanimous"] is True
    assert outcome["card_id"] == CARD


def test_an_answer_repeated_word_for_word_is_not_stored_again() -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Same."), answer("Same.")]}
    round_of(w, round_number=1)
    outcome = round_of(w, round_number=2)
    assert (outcome["answers"], outcome["repeats"]) == (0, 1)
    assert len(w.state.discussion_messages) == 1
    # Nothing new was said, so the old agreement cannot count as a fresh one.
    assert outcome["unanimous"] is False


def test_a_vote_is_recorded_only_when_the_position_changes() -> None:
    w = world("alpha")
    w.agents.scripts = {
        "alpha": [answer("A", "yes"), answer("B", "yes"), answer("C", "no")]
    }
    for number in (1, 2, 3):
        round_of(w, round_number=number)
    assert [v.position for v in w.state.votes] == ["yes", "no"]
    assert [v.justification for v in w.state.votes] == ["Recommend: A", "Recommend: C"]


def test_a_failed_or_missing_agent_is_a_failure_not_an_answer() -> None:
    w = world("alpha", "beta")
    del w.registry.agents["beta"]
    outcome = round_of(w)
    assert outcome["answers"] == 0
    assert outcome["failures"] == [
        {"agent": "Alpha", "error": "unreachable"},
        {"agent": "Beta", "error": "agent_missing"},
    ]


def test_a_roundtable_cannot_agree_in_its_opening_round() -> None:
    w = world("alpha", "beta", mode="roundtable")
    w.agents.scripts = {"alpha": [answer("Yes.")], "beta": [answer("Yes too.")]}
    assert round_of(w)["unanimous"] is False


def test_a_round_stops_when_the_run_is_no_longer_running() -> None:
    w = world("alpha")
    w.state.runs["run-1"] = run_row(status="paused")
    outcome = round_of(w)
    assert outcome["interrupted"] == "paused"
    assert w.agents.calls == []


def test_an_unknown_thread_or_run_is_not_found() -> None:
    w = world("alpha")
    with pytest.raises(NotFound):
        w.engine.run_round(BOARD_ID, "missing", run_id="run-1", round_number=1, token_budget=None)


# --- run control ---------------------------------------------------------------------------------


def outcome_of(**changes: object) -> RoundOutcome:
    outcome: RoundOutcome = {
        "round_number": 1,
        "answers": 1,
        "repeats": 0,
        "failures": [],
        "tokens": 0,
        "elapsed_ms": 0,
        "interrupted": None,
        "budget_hit": False,
        "unanimous": False,
        "participants": 1,
        "latest_positions": [],
        "card_id": CARD,
    }
    for key, value in changes.items():
        if key == "answers" and isinstance(value, int):
            outcome["answers"] = value
        elif key == "repeats" and isinstance(value, int):
            outcome["repeats"] = value
        elif key == "unanimous" and isinstance(value, bool):
            outcome["unanimous"] = value
        elif key == "budget_hit" and isinstance(value, bool):
            outcome["budget_hit"] = value
        elif key == "interrupted" and (value is None or isinstance(value, str)):
            outcome["interrupted"] = value
    return outcome


def test_classify_names_why_a_round_ends_the_run() -> None:
    run = run_row()
    assert classify(run, outcome_of(interrupted="stopped")) == ("stopped", "stopped")
    assert classify(run, outcome_of(answers=0, repeats=1)) == ("no_progress", "duplicate_answers")
    assert classify(run, outcome_of(budget_hit=True)) == ("budget_exhausted", "token_budget")
    assert classify(run, outcome_of(unanimous=True)) == ("completed", "consensus")
    assert classify(run, outcome_of()) == ("completed", None)
    timed = run.__replace__(time_budget_seconds=1, elapsed_ms=2000)
    assert classify(timed, outcome_of()) == ("budget_exhausted", "time_budget")


def test_a_single_round_runs_inline_and_finishes_the_run() -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Fine.", "no")]}
    summary = w.runs.start(ADA, BOARD_ID, THREAD, rounds=1, background=False)
    assert summary["run_status"] == "completed"
    assert summary["rounds_completed"] == 1
    (run,) = w.state.runs.values()
    assert (run.status, run.stop_reason) == ("completed", "rounds_completed")
    assert w.state.discussions[THREAD].run_state == "idle"
    assert [r.round_number for r in w.state.rounds] == [1]


def test_a_person_s_ask_defers_its_single_round_so_the_view_opens_at_once() -> None:
    """The Ask dialog sends ``background: true`` on ``/start``: the route turns it into
    ``background=True`` and the service answers before the round has run, so the view opens on
    "Agents are answering". Without the flag a single round stays inline, as a worker expects."""
    assert DiscussionRunStart().background is False
    assert DiscussionRunStart(background=True).background is True
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Fine.", "no")]}
    summary = w.runs.start(ADA, BOARD_ID, THREAD, rounds=1, background=True)
    # The deferred path: the answer says pending; the executor (synchronous in this world) then
    # runs the one round exactly as the inline path would.
    assert summary["pending"] is True
    assert summary["rounds_completed"] == 1
    assert w.state.discussions[THREAD].run_state == "idle"
    assert [r.round_number for r in w.state.rounds] == [1]


def test_consensus_ends_the_run_and_proposes_it_on_the_thread() -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Yes.")]}
    w.runs.start(ADA, BOARD_ID, THREAD, rounds=1, background=False)
    assert w.state.discussions[THREAD].status == "consensus_proposed"
    assert [o.summary for o in w.state.outcomes] == ["Every participant supports going ahead."]
    assert json.loads(w.state.outcomes[0].payload_json)["synthesis"]["suggestion"] == {
        "verdict": "yes",
        "reason": "Every participant supports going ahead.",
    }


def test_a_run_needs_participants_an_open_thread_and_no_other_active_run() -> None:
    w = world()
    with pytest.raises(ValidationFailure):
        w.runs.start(ADA, BOARD_ID, THREAD, background=False)
    w = world("alpha")
    w.state.runs["run-0"] = run_row("run-0", status="paused")
    with pytest.raises(Conflict) as active:
        w.runs.start(ADA, BOARD_ID, THREAD, background=False)
    assert active.value.details == {"run_id": "run-0", "status": "paused"}
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(status="approved")
    with pytest.raises(Conflict):
        w.runs.start(ADA, BOARD_ID, THREAD, background=False)


def test_pause_resume_and_stop_only_apply_in_their_states() -> None:
    w = world("alpha")
    w.state.runs["run-1"] = run_row(status="paused")
    with pytest.raises(Conflict):
        w.runs.pause(ADA, BOARD_ID, THREAD, "run-1")
    w.runs.stop(ADA, BOARD_ID, THREAD, "run-1")
    assert w.state.runs["run-1"].status == "stopped"
    assert w.state.discussions[THREAD].run_state == "stopped"
    with pytest.raises(Conflict):
        w.runs.stop(ADA, BOARD_ID, THREAD, "run-1")
    with pytest.raises(NotFound):
        w.runs.get(BOARD_ID, "other-thread", "run-1")


def test_recover_fails_interrupted_runs_and_settles_their_threads() -> None:
    w = world("alpha")
    w.state.runs["run-1"] = run_row(status="running")
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(run_state="running")
    assert w.runs.recover(BOARD_ID) == 1
    assert w.state.runs["run-1"].stop_reason == "process_restart"
    assert w.state.discussions[THREAD].run_state == "idle"
    assert w.runs.recover("no-such-board") == 0


# --- discussions ---------------------------------------------------------------------------------


def test_create_snapshots_each_enabled_agent_and_posts_the_goal() -> None:
    w = world()
    w.registry.agents["alpha"] = agent_row("alpha", name="Alpha")
    payload = DiscussionCreate(card_id=CARD, goal="Decide it.", participant_ids=["alpha"])
    created = w.discussions.create(ADA, BOARD_ID, payload)
    new_id = str(created["id"])
    assert created["card_title"] == w.state.cards[CARD].title
    (joined,) = [p for p in w.state.participants if p.discussion_id == new_id]
    assert (joined.participant_id, joined.system_prompt) == ("alpha", "You are alpha.")
    assert [m.content for m in w.state.discussion_messages] == ["Decide it."]


def test_create_refuses_a_missing_ticket_before_a_disabled_agent() -> None:
    w = world()
    w.registry.agents["off"] = agent_row("off", enabled=False)
    missing = DiscussionCreate(card_id="nope", goal="x", participant_ids=["off"])
    with pytest.raises(ValidationFailure) as refused:
        w.discussions.create(ADA, BOARD_ID, missing)
    assert refused.value.details == {"card_id": "nope"}
    disabled = DiscussionCreate(card_id=CARD, goal="x", participant_ids=["off"])
    with pytest.raises(ValidationFailure) as refused:
        w.discussions.create(ADA, BOARD_ID, disabled)
    assert refused.value.details == {"participant_id": "off"}


def test_a_message_reopens_an_open_thread_and_checks_its_parent() -> None:
    w = world("alpha")
    with pytest.raises(ValidationFailure):
        w.discussions.add_message(
            ADA, BOARD_ID, THREAD, DiscussionMessageCreate(content="x", parent_message_id="nope")
        )
    w.agents.scripts = {"alpha": [answer("Reply.")]}
    detail = w.discussions.add_message(
        BOT, BOARD_ID, THREAD, DiscussionMessageCreate(content="@agents please")
    )
    assert w.state.discussions[THREAD].status == "discussing"
    # Only a person's message starts a run on its own.
    assert detail["auto_run"] is None


def test_review_is_a_human_decision_with_a_reason_for_a_veto() -> None:
    w = world("alpha")
    with pytest.raises(Forbidden):
        w.discussions.review(BOT, BOARD_ID, THREAD, decision="approve")
    with pytest.raises(ValidationFailure):
        w.discussions.review(ADA, BOARD_ID, THREAD, decision="veto")
    with pytest.raises(Conflict):
        w.discussions.review(ADA, BOARD_ID, THREAD, decision="approve")
    ready = w.state.discussions[THREAD].__replace__(status="consensus_proposed")
    w.state.discussions[THREAD] = ready
    w.discussions.review(ADA, BOARD_ID, THREAD, decision="approve")
    assert w.state.discussions[THREAD].status == "approved"
    assert w.state.outcomes[-1].summary == "approve by Ada"


def test_a_participant_name_or_at_agents_asks_for_an_answer() -> None:
    people: list[Mapping[str, object]] = [{"participant_id": "a1", "display_name": "Alpha"}]
    assert requests_agent_reply("@agents go", people)
    assert requests_agent_reply("what do you think @Alpha", people)
    assert not requests_agent_reply("just a note", people)


# --- the answer standard in a round ---------------------------------------------------------------


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def entries(value: object) -> list[Mapping[str, object]]:
    """A thread detail's list of rows, narrowed."""
    assert _is_list(value)
    rows = [row for row in value if _is_mapping(row)]
    assert len(rows) == len(value)
    return rows


def answered_position(message: Mapping[str, object]) -> object:
    answer = message["answer"]
    return answer["position"] if _is_mapping(answer) else None


def test_a_round_asks_for_the_standard_and_stores_the_structure_beside_the_prose() -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Small change.", "yes_with_conditions")]}
    round_of(w)
    (stored,) = w.state.discussion_messages
    assert stored.content == "Small change."
    assert json.loads(stored.answer_json)["conditions"] == ["A rollback exists."]
    assert [schema and schema["name"] for schema in w.agents.schemas] == ["discussion_answer"]
    (prompt,) = w.agents.prompts[0]
    assert '"yes" | "yes_with_conditions" | "no" | "unclear"' in prompt["content"]
    assert [v.position for v in w.state.votes] == ["yes_with_conditions"]


def test_a_round_repairs_an_answer_once_and_keeps_one_that_stays_prose() -> None:
    w = world("alpha", "beta")
    w.agents.scripts = {
        "alpha": [said("Verdict: AGREE", tokens=3), answer("Fixed.", tokens=4)],
        "beta": [said("I would rather wait.", tokens=5), said("Still prose.", tokens=6)],
    }
    outcome = round_of(w)
    assert w.agents.calls == ["alpha", "alpha", "beta", "beta"]
    assert outcome["tokens"] == 18
    alpha, beta = w.state.discussion_messages
    assert (alpha.content, json.loads(alpha.answer_json)["format"]) == ("Fixed.", "repaired")
    kept = json.loads(beta.answer_json)
    assert beta.content == "I would rather wait."
    assert (kept["format"], kept["position"]) == ("prose", "unclear")
    assert [v.position for v in w.state.votes] == ["yes", "unclear"]
    assert w.state.votes[1].justification == "Answered in prose only."
    assert outcome["unanimous"] is False


def test_the_next_participant_reads_the_earlier_answer_as_one_line_first() -> None:
    w = world("alpha", "beta")
    w.agents.scripts = {"alpha": [answer("Small.")], "beta": [answer("Fine.")]}
    round_of(w)
    (prompt,) = w.agents.prompts[1]
    assert (
        "[Alpha · agent] (position: yes; recommendation: Recommend: Small.)\nSmall."
        in prompt["content"]
    )


def test_consensus_counts_yes_with_conditions_as_going_ahead() -> None:
    w = world("alpha", "beta")
    w.agents.scripts = {
        "alpha": [answer("Go.")],
        "beta": [answer("Go, if.", "yes_with_conditions")],
    }
    assert round_of(w)["unanimous"] is True
    w = world("alpha", "beta")
    w.agents.scripts = {"alpha": [answer("Go.")], "beta": [answer("Stop.", "no")]}
    assert round_of(w)["unanimous"] is False


def test_each_round_stores_its_synthesis_and_the_thread_answers_the_newest() -> None:
    w = world("alpha", "beta")
    w.agents.scripts = {
        "alpha": [answer("Go."), answer("Go again.")],
        "beta": [answer("Stop.", "no"), answer("Unsure.", "unclear")],
    }
    w.runs.start(ADA, BOARD_ID, THREAD, rounds=2, background=False)
    first, second = w.state.rounds
    assert json.loads(first.synthesis_json)["suggestion"]["reason"] == (
        "The participants differ: 1 for going ahead and 1 against."
    )
    assert json.loads(second.synthesis_json)["thread_round"] == 2
    detail = w.discussions.get(BOARD_ID, THREAD)
    synthesis = detail["synthesis"]
    assert isinstance(synthesis, dict)
    assert synthesis["round_id"] == second.id
    assert synthesis["suggestion"] == {
        "verdict": "unclear",
        "reason": "Not settled yet: 1 for going ahead and 1 cannot tell; read the open questions.",
    }
    stances = entries(detail["positions"])
    assert [(s["participant"], s["position"]) for s in stances] == [
        ("Alpha", "yes"),
        ("Beta", "unclear"),
    ]
    messages = entries(detail["messages"])
    assert [answered_position(m) for m in messages] == ["yes", "no", "yes", "unclear"]
    assert all("answer_json" not in m for m in messages)


def test_a_persons_message_has_no_answer_and_a_thread_without_rounds_no_synthesis() -> None:
    w = world("alpha")
    w.discussions.add_message(BOT, BOARD_ID, THREAD, DiscussionMessageCreate(content="Note."))
    detail = w.discussions.get(BOARD_ID, THREAD)
    assert detail["synthesis"] is None
    assert detail["positions"] == []
    assert [m["answer"] for m in entries(detail["messages"])] == [None]
