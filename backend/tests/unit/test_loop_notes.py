"""A Loop's notes on the fakes: LoopNoteService adds and pages them, and ``write_note`` and
``read_notes`` run it as the one attribute ``NoteKeeping`` declares.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, ValidationFailure
from app.services.agent_tools import read_notes, tool_catalog, write_note
from app.services.loop_notes import NOTE_DEDUPE_SECONDS, LoopNoteService
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    loop_row,
)

START = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
LOOP = "loop-a"
WORKER = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Worker",
    scopes=frozenset({"loops:read", "loops:write"}),
)
READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"loops:read"})
)


class Clock:
    """A clock a test moves forward."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


class Ids:
    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"id-{self.issued}"


@dataclass(frozen=True, slots=True)
class NoteWorld:
    """What the note tools declare they use of the composition root, and the board."""

    loop_notes: LoopNoteService
    state: BoardState
    clock: Clock


def note_world() -> NoteWorld:
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="in_progress")}
    clock = Clock()
    service = LoopNoteService(
        FakeBoardChecks(), FakeBoardUnitOfWork(state), clock=clock, new_id=Ids()
    )
    return NoteWorld(service, state, clock)


def contents(world: NoteWorld) -> list[str]:
    return [note.content for note in world.state.notes]


def at(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


def test_a_note_is_stored_with_its_author_and_logged_without_its_text() -> None:
    world = note_world()
    note, deduplicated = world.loop_notes.add(WORKER, BOARD_ID, LOOP, "  Baseline: master 3d99  ")
    assert deduplicated is False
    assert note == {
        "id": "id-1",
        "loop_id": LOOP,
        "author_actor_id": "agent-1",
        "author_actor_type": "agent",
        "author_name": "Worker",
        "content": "Baseline: master 3d99",
        "created_at": "2026-11-03T10:00:00Z",
    }
    (entry,) = world.state.activity
    assert (entry.action, entry.entity_id) == ("loop.note_added", LOOP)
    assert json.loads(entry.changes_json or "{}") == {"note_id": "id-1", "length": 21}
    assert "Baseline" not in (entry.changes_json or "")


def test_the_same_note_a_moment_later_answers_the_first_and_later_is_a_new_one() -> None:
    world = note_world()
    first, _ = world.loop_notes.add(WORKER, BOARD_ID, LOOP, "Gates passed")
    world.clock.now = START + timedelta(seconds=NOTE_DEDUPE_SECONDS - 1)
    again, deduplicated = world.loop_notes.add(WORKER, BOARD_ID, LOOP, "Gates passed")
    assert (again, deduplicated) == (first, True)
    world.clock.now = START + timedelta(seconds=NOTE_DEDUPE_SECONDS)
    _, later = world.loop_notes.add(WORKER, BOARD_ID, LOOP, "Gates passed")
    assert later is False
    assert contents(world) == ["Gates passed", "Gates passed"]


def test_a_note_is_refused_on_a_read_only_loop_when_empty_or_without_the_scope() -> None:
    world = note_world()
    with pytest.raises(ValidationFailure):
        world.loop_notes.add(WORKER, BOARD_ID, LOOP, "   ")
    with pytest.raises(ValidationFailure):
        world.loop_notes.add(WORKER, BOARD_ID, LOOP, "x" * 20_001)
    with pytest.raises(Forbidden):
        world.loop_notes.add(READER, BOARD_ID, LOOP, "Hello")
    world.state.loops[LOOP] = loop_row(LOOP, stage="completed", completed_at=CREATED)
    with pytest.raises(Conflict) as closed:
        world.loop_notes.add(WORKER, BOARD_ID, LOOP, "Hello")
    assert closed.value.code == "loop_read_only"
    assert contents(world) == []


def test_notes_page_oldest_first_from_the_newest_and_before_a_note() -> None:
    world = note_world()
    for number in range(5):
        world.clock.now = at(number)
        world.loop_notes.add(WORKER, BOARD_ID, LOOP, f"note {number}")
    newest = world.loop_notes.list(READER, BOARD_ID, LOOP, limit=2)
    assert [note["content"] for note in newest["notes"]] == ["note 3", "note 4"]
    assert newest["count"] == 5
    first_id = newest["notes"][0]["id"]
    older = world.loop_notes.list(READER, BOARD_ID, LOOP, limit=2, before=first_id)
    assert [note["content"] for note in older["notes"]] == ["note 1", "note 2"]
    with pytest.raises(ValidationFailure):
        world.loop_notes.list(READER, BOARD_ID, LOOP, limit=201)


def test_write_note_and_read_notes_run_the_service() -> None:
    world = note_world()
    deployed = {"board_id": BOARD_ID, "loop_id": LOOP, "content": "Deployed"}
    written = write_note(world, WORKER, deployed)
    assert written == {"note": world.loop_notes.list(READER, BOARD_ID, LOOP)["notes"][0]}
    assert write_note(world, WORKER, deployed) == written | {"deduplicated": True}
    world.clock.now = at(1)
    write_note(world, WORKER, {"board_id": BOARD_ID, "loop_id": LOOP, "content": "Open: docs"})
    page = read_notes(world, READER, {"board_id": BOARD_ID, "loop_id": LOOP, "limit": 1})
    assert (page["count"], page["older"]) == (2, "id-3")
    older = read_notes(world, READER, {"board_id": BOARD_ID, "loop_id": LOOP, "before": "id-3"})
    assert (older["count"], older["older"]) == (2, None)
    with pytest.raises(Forbidden):
        write_note(world, READER, deployed)
    assert tool_catalog()["write_note"].scopes == ("loops:write",)
    assert tool_catalog()["read_notes"].scopes == ("loops:read",)
