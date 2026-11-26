"""A Loop's stop list (``LoopStopService`` and its pure rules on the board fakes) and the stop a
wait on a Ticket names (``TicketWorkService.set_wait``), with a wait that names none working as it
always did."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.context import DECIDE_SCOPE, ActorContext, EditorDecision
from app.core.errors import Conflict, Forbidden, ValidationFailure
from app.db.generated.board import LoopsRow
from app.schemas.cards import TicketWaitClear, TicketWaitSet
from app.schemas.poc_decisions import StopListUpdate
from app.services.cards import CardService
from app.services.loop_stops import (
    DEFAULT_STOPS,
    NOT_A_STOP_MESSAGE,
    STOP_MAX_CHARS,
    STOPS_MAX_LINES,
    LoopStopService,
    checked_stops,
    match_stop,
    parse_stops,
    stop_problems,
)
from app.services.ticket_work import TicketWorkService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import FakePlanViews, plan_views
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
STAMP = "2026-11-26T09:00:00Z"
LOOP = "loop-a"
CARD = "card-1"
SCOPES = frozenset({"loops:read", "loops:write", "cards:read", "cards:write"})
ADA = ActorContext(actor_id="user-ada", actor_type="user", actor_name="Ada", scopes=SCOPES)
KEY = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Worker", scopes=SCOPES, credential_id="k1"
)
EDITOR = ActorContext(
    actor_id="user-ada",
    actor_type="user",
    actor_name="Ada",
    scopes=SCOPES | {DECIDE_SCOPE},
    credential_id="key-9",
    editor_decision=EditorDecision(credential_id="key-9", key_name="Editor"),
)
STOPS = ["Deployment to production", "Deleting data", "Money"]


@dataclass(frozen=True, slots=True)
class StopWorld:
    stops: LoopStopService
    work: TicketWorkService
    state: BoardState


def stop_world(settings: Settings, loop: LoopsRow | None = None) -> StopWorld:
    state = BoardState()
    state.loops = {LOOP: loop or loop_row(LOOP, stage="in_progress")}
    state.lists = {"todo": list_row("todo", LOOP, 512)}
    state.cards = {CARD: card_row(CARD, "todo", LOOP)}
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(state)
    cards = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=plan_views(FakePlanViews()),
        clock=lambda: NOW,
    )
    return StopWorld(
        stops=LoopStopService(checks, store, clock=lambda: NOW),
        work=TicketWorkService(checks, store, cards, clock=lambda: NOW),
        state=state,
    )


def wait(version: int = 1, *, stop: str | None = None, reason: str = "Ship it?") -> TicketWaitSet:
    if stop is None:
        return TicketWaitSet(version=version, waiting_for="decision", reason=reason)
    return TicketWaitSet(version=version, waiting_for="decision", reason=reason, stop=stop)


# --- the pure rules ------------------------------------------------------------------------------


def test_the_default_list_is_the_five_lines_and_null_reads_as_it() -> None:
    assert DEFAULT_STOPS == (
        "Deployment to production",
        "Deleting data",
        "Money",
        "Something sent to people outside",
        "A new kind of personal data",
    )
    assert parse_stops(None) == {"stops": list(DEFAULT_STOPS), "is_default": True}
    assert parse_stops("[]") == {"stops": [], "is_default": False}
    assert parse_stops('["Money"]') == {"stops": ["Money"], "is_default": False}
    for broken in ("not json", '{"a": 1}', "[1, 2]"):
        assert parse_stops(broken)["is_default"] is True


def test_a_list_holds_at_most_twelve_single_lines_of_1_to_140_characters_once() -> None:
    assert stop_problems([]) == []
    assert stop_problems([f"Line {n}" for n in range(STOPS_MAX_LINES)]) == []
    too_many = [f"Line {n}" for n in range(STOPS_MAX_LINES + 1)]
    assert stop_problems(too_many) == ["The list has 13 lines, at most 12."]
    assert stop_problems(["Money", "  ", "a\nb", "x" * (STOP_MAX_CHARS + 1), " money "]) == [
        "Line 2 is empty.",
        "Line 3 is more than one line.",
        f"Line 4 has {STOP_MAX_CHARS + 1} characters, at most {STOP_MAX_CHARS}.",
        "Line 5 repeats line 1.",
    ]
    assert checked_stops(["  Money  ", "x" * STOP_MAX_CHARS]) == ["Money", "x" * STOP_MAX_CHARS]
    with pytest.raises(ValidationFailure) as refused:
        checked_stops(["Money", "MONEY"])
    assert refused.value.code == "stops_invalid"
    assert refused.value.details == {"errors": ["Line 2 repeats line 1."], "error_count": 1}


def test_a_stop_is_found_by_its_text_or_its_number() -> None:
    assert match_stop(STOPS, "  deleting DATA ") == "Deleting data"
    assert match_stop(STOPS, "2") == "Deleting data"
    assert match_stop(STOPS, "3") == "Money"
    for nothing in ("0", "4", "-1", "Deleting", "", "two"):
        assert match_stop(STOPS, nothing) is None
    # A line whose text is a number is found by its text first.
    assert match_stop(["Money", "1"], "1") == "1"
    assert match_stop([], "1") is None


# --- reading and writing the list ----------------------------------------------------------------


def test_a_loop_without_a_list_reads_the_default(settings: Settings) -> None:
    world = stop_world(settings)
    assert world.stops.read(KEY, BOARD_ID, LOOP) == {
        "stops": list(DEFAULT_STOPS),
        "is_default": True,
    }
    with pytest.raises(Forbidden):
        world.stops.read(KEY.__replace__(scopes=frozenset()), BOARD_ID, LOOP)


def test_a_person_writes_the_list_and_the_log_says_what_it_was(settings: Settings) -> None:
    world = stop_world(settings)
    written = world.stops.write(ADA, BOARD_ID, LOOP, ["  Money ", "Deleting data"])
    assert written == {"stops": ["Money", "Deleting data"], "is_default": False}
    assert world.state.loops[LOOP].stops_json == '["Money", "Deleting data"]'
    assert world.state.loops[LOOP].version == 1
    assert world.stops.read(KEY, BOARD_ID, LOOP) == written
    (entry,) = world.state.activity
    assert (entry.action, entry.entity_type, entry.entity_id) == (
        "loop.stops_changed",
        "loop",
        LOOP,
    )
    assert json.loads(entry.changes_json) == {
        "stops": ["Money", "Deleting data"],
        "before": list(DEFAULT_STOPS),
        "was_default": True,
    }
    # The same list again changes nothing.
    world.stops.write(ADA, BOARD_ID, LOOP, ["Money", "Deleting data"])
    assert len(world.state.activity) == 1


def test_an_empty_list_is_stored_as_a_choice_of_its_own(settings: Settings) -> None:
    world = stop_world(settings)
    assert world.stops.write(ADA, BOARD_ID, LOOP, []) == {"stops": [], "is_default": False}
    assert world.state.loops[LOOP].stops_json == "[]"


@pytest.mark.parametrize("stage", ["draft", "planning", "in_progress", "awaiting_qa"])
def test_a_person_writes_the_list_at_every_stage_and_a_key_never_does(
    settings: Settings, stage: str
) -> None:
    world = stop_world(settings, loop_row(LOOP, stage=stage))
    for actor in (KEY, EDITOR):
        with pytest.raises(Forbidden) as refused:
            world.stops.write(actor, BOARD_ID, LOOP, ["Money"])
        assert refused.value.code == "human_action_required"
    assert world.stops.write(ADA, BOARD_ID, LOOP, ["Money"])["stops"] == ["Money"]


def test_writing_the_list_needs_loops_write_a_writable_loop_and_valid_lines(
    settings: Settings,
) -> None:
    world = stop_world(settings)
    with pytest.raises(Forbidden):
        world.stops.write(ADA.__replace__(scopes=frozenset({"loops:read"})), BOARD_ID, LOOP, [])
    with pytest.raises(ValidationFailure) as invalid:
        world.stops.write(ADA, BOARD_ID, LOOP, ["Money", "money"])
    assert invalid.value.code == "stops_invalid"
    closed = stop_world(settings, loop_row(LOOP, stage="completed", completed_at=STAMP))
    with pytest.raises(Conflict) as read_only:
        closed.stops.write(ADA, BOARD_ID, LOOP, ["Money"])
    assert read_only.value.code == "loop_read_only"
    assert world.state.loops[LOOP].stops_json is None


def test_the_update_schema_bounds_what_a_request_carries() -> None:
    with pytest.raises(ValidationError):
        StopListUpdate.model_validate({})
    with pytest.raises(ValidationError):
        StopListUpdate(stops=["x"] * 51)
    assert StopListUpdate(stops=[]).stops == []


# --- the stop a wait names -----------------------------------------------------------------------


def test_a_wait_names_its_stop_by_text_or_number_and_stores_the_line(settings: Settings) -> None:
    world = stop_world(settings)
    entry = world.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(stop=" money "))
    assert (entry["waiting_for"], entry["waiting_stop"]) == ("decision", "Money")
    (logged,) = world.state.activity
    assert logged.action == "card.wait_set"
    changes = json.loads(logged.changes_json)
    assert (changes["stop"], changes["waiting_for"], changes["reason"]) == (
        "Money",
        "decision",
        "Ship it?",
    )
    other = stop_world(settings)
    other.stops.write(ADA, BOARD_ID, LOOP, STOPS)
    numbered = other.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(stop="2"))
    assert numbered["waiting_stop"] == "Deleting data"


def test_a_wait_naming_something_not_on_the_list_is_not_a_stop(settings: Settings) -> None:
    world = stop_world(settings)
    world.stops.write(ADA, BOARD_ID, LOOP, STOPS)
    for given in ("Pick a colour", "4"):
        with pytest.raises(ValidationFailure) as refused:
            world.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(stop=given))
        assert (refused.value.status_code, refused.value.code) == (422, "not_a_stop")
        assert refused.value.message == NOT_A_STOP_MESSAGE
        assert refused.value.details == {"stops": STOPS}
    card = world.state.cards[CARD]
    assert (card.waiting_for, card.waiting_stop, card.version) == ("nothing", None, 1)
    empty = stop_world(settings)
    empty.stops.write(ADA, BOARD_ID, LOOP, [])
    with pytest.raises(ValidationFailure) as nothing_stops:
        empty.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(stop="1"))
    assert nothing_stops.value.details == {"stops": []}


def test_a_wait_without_a_stop_works_as_it_always_did(settings: Settings) -> None:
    world = stop_world(settings)
    entry = world.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait())
    assert (entry["waiting_for"], entry["waiting_reason"], entry["waiting_stop"]) == (
        "decision",
        "Ship it?",
        None,
    )
    (logged,) = world.state.activity
    assert {
        key: value for key, value in json.loads(logged.changes_json).items() if key != "before"
    } == {"waiting_for": "decision", "reason": "Ship it?"}
    # The same wait again changes nothing, an empty stop is no stop, and a key still may not
    # replace a wait.
    again = world.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(version=2, stop=""))
    assert again["version"] == 2
    with pytest.raises(Forbidden):
        world.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(version=2, reason="Other"))


def test_the_stop_is_cleared_with_the_wait(settings: Settings) -> None:
    world = stop_world(settings)
    world.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(stop="Money"))
    # The same wait without naming its stop again keeps it.
    kept = world.work.set_wait(KEY, BOARD_ID, LOOP, CARD, wait(version=2))
    assert (kept["version"], kept["waiting_stop"]) == (2, "Money")
    cleared = world.work.clear_wait(ADA, BOARD_ID, LOOP, CARD, TicketWaitClear(version=2))
    assert (cleared["waiting_for"], cleared["waiting_stop"]) == ("nothing", None)
    assert world.state.cards[CARD].waiting_stop is None


def test_the_wait_schema_bounds_the_stop() -> None:
    with pytest.raises(ValidationError):
        wait(stop="x" * 141)
    assert wait(stop="  Money  ").stop == "Money"
    assert TicketWaitSet(version=1, waiting_for="access", reason="Key").stop is None
