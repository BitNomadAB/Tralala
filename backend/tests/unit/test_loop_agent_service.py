"""LoopAgentService on the in-memory board fake: a stored preference per purpose, never a grant."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from app.core.context import ActorContext
from app.core.errors import Forbidden, NotFound, ValidationFailure
from app.services.agents import AgentService
from app.services.loop_agents import BoardAgentRoster, LoopAgentService
from tests.unit.fakes.board import BOARD_ID, BoardState, FakeBoardUnitOfWork, loop_row

NOW = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
WRITER = ActorContext(
    actor_id="actor-1",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"boards:write"}),
    request_id="request-1",
)
READER = ActorContext(
    actor_id="actor-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"boards:read"})
)


def agent_service_is_what_loop_agents_need(service: AgentService) -> BoardAgentRoster:
    """Never called: pyright proves that the AgentService wired in Services fits the roster."""
    return service


@dataclass(slots=True)
class Roster:
    known: frozenset[str] = frozenset({"agent-1", "agent-2", "agent-3"})
    on_board: list[str] = field(default_factory=list[str])

    def validate_ids(self, agent_ids: list[str]) -> None:
        unknown = [agent_id for agent_id in agent_ids if agent_id not in self.known]
        if unknown:
            raise ValidationFailure("Unknown agent", code="agent_not_found")

    def agent_ids(self, board_id: str) -> list[str]:
        assert board_id == BOARD_ID
        return list(self.on_board)


def make(roster: Roster | None = None) -> tuple[LoopAgentService, BoardState, FakeBoardUnitOfWork]:
    state = BoardState()
    state.loops[LOOP] = loop_row(LOOP)
    store = FakeBoardUnitOfWork(state)
    issued = iter(range(1, 1000))
    service = LoopAgentService(
        store, roster or Roster(), clock=lambda: NOW, new_id=lambda: f"activity-{next(issued)}"
    )
    return service, state, store


def test_a_loop_without_preferences_answers_none_for_every_purpose() -> None:
    service, _, _ = make()
    assert service.get(BOARD_ID, LOOP) == {"analysis": None, "roadmap": None, "qa": None}


def test_an_unknown_loop_is_not_found() -> None:
    service, _, _ = make()
    with pytest.raises(NotFound):
        service.get(BOARD_ID, "missing")
    with pytest.raises(NotFound):
        service.set(WRITER, BOARD_ID, "missing", {"analysis": "agent-1"})


def test_set_stores_the_agents_and_answers_every_purpose() -> None:
    service, state, store = make()
    stored = service.set(WRITER, BOARD_ID, LOOP, {"analysis": "agent-1", "qa": "agent-2"})
    assert stored == {"analysis": "agent-1", "roadmap": None, "qa": "agent-2"}
    assert state.loop_agents[(LOOP, "analysis")].updated_at == NOW
    assert store.commits == 1


def test_none_clears_one_purpose_and_keeps_the_others() -> None:
    service, _, _ = make()
    service.set(WRITER, BOARD_ID, LOOP, {"analysis": "agent-1", "roadmap": "agent-2"})
    stored = service.set(WRITER, BOARD_ID, LOOP, {"analysis": None})
    assert stored == {"analysis": None, "roadmap": "agent-2", "qa": None}


def test_set_writes_one_activity_entry_with_the_assignments() -> None:
    service, state, _ = make()
    service.set(WRITER, BOARD_ID, LOOP, {"qa": "agent-3"})
    (entry,) = state.activity
    assert (entry.id, entry.action, entry.entity_type, entry.entity_id) == (
        "activity-1",
        "loop.agents_updated",
        "loop",
        LOOP,
    )
    assert entry.timestamp == NOW
    assert json.loads(entry.changes_json) == {"agents": {"qa": "agent-3"}}


def test_set_needs_the_board_write_scope() -> None:
    service, state, _ = make()
    with pytest.raises(Forbidden):
        service.set(READER, BOARD_ID, LOOP, {"analysis": "agent-1"})
    assert state.loop_agents == {}


def test_an_unknown_agent_is_refused_before_anything_is_written() -> None:
    service, state, store = make()
    with pytest.raises(ValidationFailure):
        service.set(WRITER, BOARD_ID, LOOP, {"analysis": "nobody"})
    assert state.loop_agents == {}
    assert store.commits == 0


def test_an_agent_the_board_does_not_list_is_refused_with_its_purpose() -> None:
    service, state, _ = make(Roster(on_board=["agent-1"]))
    with pytest.raises(ValidationFailure) as refused:
        service.set(WRITER, BOARD_ID, LOOP, {"analysis": "agent-1", "qa": "agent-2"})
    assert refused.value.code == "agent_not_on_board"
    assert refused.value.details == {"purpose": "qa", "agent_id": "agent-2"}
    assert state.loop_agents == {}


def test_a_board_that_lists_no_agents_accepts_any_known_agent() -> None:
    service, _, _ = make(Roster(on_board=[]))
    assert service.set(WRITER, BOARD_ID, LOOP, {"roadmap": "agent-3"})["roadmap"] == "agent-3"


def test_resolve_answers_the_stored_agent_or_none() -> None:
    service, _, _ = make()
    service.set(WRITER, BOARD_ID, LOOP, {"roadmap": "agent-2"})
    assert service.resolve(BOARD_ID, LOOP, "roadmap") == "agent-2"
    assert service.resolve(BOARD_ID, LOOP, "qa") is None
