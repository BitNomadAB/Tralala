"""A person's notes on a Ticket: ``CardNoteService`` on the board fakes, with the real
``EventService`` over the same fake board, the request schemas at the boundary, and what
``read_ticket`` and the catalogue say about them."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, VersionConflict
from app.db.generated.board import LoopsRow
from app.schemas.card_notes import NOTE_TEXT_MAX, CardNoteCreate, CardNoteUpdate
from app.services.agent_tools import tool_catalog
from app.services.agent_tools_read import person_notes
from app.services.card_notes import (
    NOTE_ADDED,
    NOTE_DELETED,
    NOTE_EDITED,
    CardNoteService,
)
from app.services.events import EventService, Subscriber
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)

START = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
LOOP = "loop-a"
OTHER_LOOP = "loop-b"
CARD = "card-1"
OTHER_CARD = "card-2"
ELSEWHERE = "card-9"
ADA = ActorContext(
    actor_id="user-ada",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"cards:read", "cards:write"}),
)
BEA = ActorContext(
    actor_id="user-bea",
    actor_type="user",
    actor_name="Bea",
    scopes=frozenset({"cards:read", "cards:write"}),
)
VIEWER = ActorContext(
    actor_id="user-cy", actor_type="user", actor_name="Cy", scopes=frozenset({"cards:read"})
)
TOKEN = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Worker",
    scopes=frozenset({"cards:read", "cards:write", "comments:write"}),
    credential_id="key-1",
)
NOBODY = ActorContext(actor_id="user-dee", actor_type="user", actor_name="Dee")


class Clock:
    """A clock a test moves forward."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: int) -> None:
        self.now += timedelta(minutes=minutes)


class Ids:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"{self.prefix}-{self.issued}"


@dataclass(frozen=True, slots=True)
class NoteWorld:
    notes: CardNoteService
    events: EventService
    state: BoardState
    checks: FakeBoardChecks
    clock: Clock


def note_world() -> NoteWorld:
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP), OTHER_LOOP: loop_row(OTHER_LOOP)}
    state.lists = {
        "list-a": list_row("list-a", LOOP, 1),
        "list-b": list_row("list-b", OTHER_LOOP, 1),
    }
    state.cards = {
        CARD: card_row(CARD, "list-a", LOOP),
        OTHER_CARD: card_row(OTHER_CARD, "list-a", LOOP),
        ELSEWHERE: card_row(ELSEWHERE, "list-b", OTHER_LOOP),
    }
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    clock = Clock()
    events = EventService(checks, store, clock=lambda: "2026-11-08T09:00:00Z", new_id=Ids("event"))
    notes = CardNoteService(checks, store, events, clock=clock, new_id=Ids("id"))
    return NoteWorld(notes, events, state, checks, clock)


def add(world: NoteWorld, text: str, actor: ActorContext = ADA, card_id: str = CARD) -> str:
    return world.notes.add(actor, BOARD_ID, LOOP, card_id, CardNoteCreate(text=text))["id"]


def texts(world: NoteWorld) -> list[str]:
    return [note["text"] for note in world.notes.list(VIEWER, BOARD_ID, LOOP, CARD)]


def drained(listener: Subscriber) -> list[tuple[object, object]]:
    found: list[tuple[object, object]] = []
    while not listener.empty():
        event = listener.get_nowait()
        found.append((event["type"], event["payload"]))
    return found


# --- adding and listing --------------------------------------------------------------------------


def test_a_person_adds_a_note_with_their_name_and_time_and_the_log_holds_no_text() -> None:
    world = note_world()
    listener = world.events.subscribe_card(BOARD_ID, CARD)
    note = world.notes.add(ADA, BOARD_ID, LOOP, CARD, CardNoteCreate(text="  Ask Bea first  "))
    assert note == {
        "id": "id-1",
        "card_id": CARD,
        "author": "Ada",
        "author_actor_id": "user-ada",
        "written_at": "2026-11-08T09:00:00Z",
        "updated_at": "2026-11-08T09:00:00Z",
        "text": "Ask Bea first",
        "version": 1,
    }
    (entry,) = world.state.activity
    assert (entry.action, entry.entity_type, entry.entity_id) == ("card.note_added", "card", CARD)
    assert (entry.actor_id, entry.actor_type) == ("user-ada", "user")
    assert json.loads(entry.changes_json or "{}") == {"note_id": "id-1", "version": 1, "length": 13}
    assert "Bea" not in (entry.changes_json or "")
    # The card event is stored in the write's transaction and handed to an open Ticket view.
    (stored,) = world.state.card_events
    assert (stored.card_id, stored.type, stored.actor_id) == (CARD, NOTE_ADDED, "user-ada")
    assert drained(listener) == [(NOTE_ADDED, {"note_id": "id-1", "version": 1})]


def test_notes_list_oldest_first_and_only_the_tickets_own() -> None:
    world = note_world()
    add(world, "first")
    world.clock.advance(5)
    add(world, "second")
    add(world, "same second, written after")
    add(world, "on the other Ticket", card_id=OTHER_CARD)
    world.clock.advance(-60)
    add(world, "clock behind: still sorted by its time")
    assert texts(world) == [
        "clock behind: still sorted by its time",
        "first",
        "second",
        "same second, written after",
    ]
    # Anyone who may read the board reads them, a token included; nobody else does.
    assert len(world.notes.list(TOKEN, BOARD_ID, LOOP, CARD)) == 4
    with pytest.raises(Forbidden):
        world.notes.list(NOBODY, BOARD_ID, LOOP, CARD)


def test_a_ticket_of_another_loop_is_a_loop_mismatch_and_a_missing_one_not_found() -> None:
    world = note_world()
    with pytest.raises(Conflict) as listed:
        world.notes.list(VIEWER, BOARD_ID, LOOP, ELSEWHERE)
    assert listed.value.code == "loop_mismatch"
    with pytest.raises(Conflict) as added:
        add(world, "wrong Loop", card_id=ELSEWHERE)
    assert added.value.code == "loop_mismatch"
    with pytest.raises(NotFound):
        world.notes.list(VIEWER, BOARD_ID, LOOP, "card-missing")
    # A note addressed through another Ticket of the same Loop is not found there.
    note_id = add(world, "mine")
    with pytest.raises(NotFound) as elsewhere:
        world.notes.delete(ADA, BOARD_ID, LOOP, OTHER_CARD, note_id)
    assert elsewhere.value.code == "note_not_found"
    assert texts(world) == ["mine"]


# --- editing and deleting ------------------------------------------------------------------------


def test_the_author_edits_the_version_they_read() -> None:
    world = note_world()
    note_id = add(world, "draft")
    listener = world.events.subscribe_card(BOARD_ID, CARD)
    world.clock.advance(3)
    edited = world.notes.edit(
        ADA, BOARD_ID, LOOP, CARD, note_id, CardNoteUpdate(text="final", version=1)
    )
    assert (edited["text"], edited["version"]) == ("final", 2)
    assert (edited["written_at"], edited["updated_at"]) == (
        "2026-11-08T09:00:00Z",
        "2026-11-08T09:03:00Z",
    )
    assert world.notes.list(VIEWER, BOARD_ID, LOOP, CARD) == [edited]
    assert [entry.action for entry in world.state.activity] == [
        "card.note_added",
        "card.note_edited",
    ]
    assert json.loads(world.state.activity[-1].changes_json or "{}") == {
        "note_id": note_id,
        "version": 2,
        "length": 5,
    }
    assert drained(listener) == [(NOTE_EDITED, {"note_id": note_id, "version": 2})]


def test_a_stale_version_is_refused_and_changes_nothing() -> None:
    world = note_world()
    note_id = add(world, "draft")
    world.notes.edit(ADA, BOARD_ID, LOOP, CARD, note_id, CardNoteUpdate(text="second", version=1))
    with pytest.raises(VersionConflict) as stale:
        world.notes.edit(
            ADA, BOARD_ID, LOOP, CARD, note_id, CardNoteUpdate(text="third", version=1)
        )
    assert stale.value.code == "version_conflict"
    assert stale.value.status_code == 409
    assert stale.value.details == {"expected_version": 1, "current_version": 2}
    assert texts(world) == ["second"]
    assert len(world.state.activity) == 2


def test_another_person_may_neither_edit_nor_delete_a_note() -> None:
    world = note_world()
    note_id = add(world, "Ada's word")
    with pytest.raises(Forbidden) as edit:
        world.notes.edit(
            BEA, BOARD_ID, LOOP, CARD, note_id, CardNoteUpdate(text="Bea's word", version=1)
        )
    assert edit.value.code == "note_author_only"
    with pytest.raises(Forbidden) as delete:
        world.notes.delete(BEA, BOARD_ID, LOOP, CARD, note_id)
    assert delete.value.code == "note_author_only"
    assert texts(world) == ["Ada's word"]
    # Bea writes a note of her own beside it.
    add(world, "Bea's word", actor=BEA)
    assert [n["author"] for n in world.notes.list(VIEWER, BOARD_ID, LOOP, CARD)] == ["Ada", "Bea"]


def test_the_author_deletes_a_note() -> None:
    world = note_world()
    keep = add(world, "keep")
    gone = add(world, "gone")
    listener = world.events.subscribe_card(BOARD_ID, CARD)
    world.notes.delete(ADA, BOARD_ID, LOOP, CARD, gone)
    assert [n["id"] for n in world.notes.list(VIEWER, BOARD_ID, LOOP, CARD)] == [keep]
    assert world.state.activity[-1].action == "card.note_deleted"
    assert drained(listener) == [(NOTE_DELETED, {"note_id": gone, "version": 1})]
    with pytest.raises(NotFound):
        world.notes.delete(ADA, BOARD_ID, LOOP, CARD, gone)


# --- who may write, and when ---------------------------------------------------------------------


def test_a_token_never_writes_a_note_whatever_its_scopes() -> None:
    world = note_world()
    with pytest.raises(Forbidden) as added:
        add(world, "from a key", actor=TOKEN)
    assert added.value.code == "human_action_required"
    note_id = add(world, "Ada's")
    # Even a key that names the author's actor id is not the person.
    as_author = ActorContext(
        actor_id="user-ada", actor_type="agent", actor_name="Ada's key", scopes=TOKEN.scopes
    )
    for actor in (TOKEN, as_author):
        with pytest.raises(Forbidden) as edited:
            world.notes.edit(
                actor, BOARD_ID, LOOP, CARD, note_id, CardNoteUpdate(text="x", version=1)
            )
        assert edited.value.code == "human_action_required"
        with pytest.raises(Forbidden) as deleted:
            world.notes.delete(actor, BOARD_ID, LOOP, CARD, note_id)
        assert deleted.value.code == "human_action_required"
    # A person without cards:write may read, not write.
    with pytest.raises(Forbidden) as viewer:
        add(world, "read-only person", actor=VIEWER)
    assert viewer.value.code == "forbidden"
    assert texts(world) == ["Ada's"]
    assert world.state.card_events[-1].type == NOTE_ADDED
    assert len(world.state.card_events) == 1


@pytest.mark.parametrize(
    "ended",
    [
        loop_row(LOOP, stage="completed", completed_at=CREATED),
        loop_row(LOOP, stage="cancelled", cancelled_at=CREATED),
        loop_row(LOOP, archived_at=CREATED),
    ],
    ids=["completed", "cancelled", "archived"],
)
def test_a_completed_cancelled_or_archived_loop_refuses_every_write(ended: LoopsRow) -> None:
    world = note_world()
    note_id = add(world, "before the end")
    world.state.loops[LOOP] = ended
    with pytest.raises(Conflict) as added:
        add(world, "after the end")
    with pytest.raises(Conflict) as edited:
        world.notes.edit(
            ADA, BOARD_ID, LOOP, CARD, note_id, CardNoteUpdate(text="changed", version=1)
        )
    with pytest.raises(Conflict) as deleted:
        world.notes.delete(ADA, BOARD_ID, LOOP, CARD, note_id)
    assert {added.value.code, edited.value.code, deleted.value.code} == {"loop_read_only"}
    # The Loop's notes stay readable, as they were.
    assert texts(world) == ["before the end"]
    assert len(world.state.activity) == 1


def test_an_archived_board_refuses_every_write_and_still_lists() -> None:
    world = note_world()
    note_id = add(world, "before the archive")
    archived = note_world()
    archived.state.card_notes.extend(world.state.card_notes)
    archived.checks.archived = frozenset({BOARD_ID})
    for attempt in (
        lambda: add(archived, "after"),
        lambda: archived.notes.edit(
            ADA, BOARD_ID, LOOP, CARD, note_id, CardNoteUpdate(text="changed", version=1)
        ),
        lambda: archived.notes.delete(ADA, BOARD_ID, LOOP, CARD, note_id),
    ):
        with pytest.raises(Conflict) as refused:
            attempt()
        assert refused.value.code == "board_archived"
    assert texts(archived) == ["before the archive"]
    assert archived.state.activity == []


# --- the boundary --------------------------------------------------------------------------------


def test_a_note_holds_1_to_4000_characters_and_an_edit_names_its_version() -> None:
    assert CardNoteCreate(text="  x  ").text == "x"
    assert CardNoteCreate(text="x" * NOTE_TEXT_MAX).text == "x" * 4000
    for bad in ("", "   ", "x" * (NOTE_TEXT_MAX + 1)):
        with pytest.raises(ValidationError):
            CardNoteCreate(text=bad)
    with pytest.raises(ValidationError):
        CardNoteCreate.model_validate({"text": "x", "author": "someone else"})
    with pytest.raises(ValidationError):
        CardNoteUpdate.model_validate({"text": "x"})
    with pytest.raises(ValidationError):
        CardNoteUpdate(text="x", version=0)


# --- what a coding agent reads -------------------------------------------------------------------


def test_read_ticket_shows_a_persons_notes_oldest_first_and_no_tool_writes_one() -> None:
    world = note_world()
    assert person_notes(world.notes.list(TOKEN, BOARD_ID, LOOP, CARD)) == []
    add(world, "Use the staging copy, not the live one")
    world.clock.advance(1)
    add(world, "I asked Bea about the wording", actor=BEA)
    assert person_notes(world.notes.list(TOKEN, BOARD_ID, LOOP, CARD)) == [
        {
            "author": "Ada",
            "written_at": "2026-11-08T09:00:00Z",
            "text": "Use the staging copy, not the live one",
        },
        {
            "author": "Bea",
            "written_at": "2026-11-08T09:01:00Z",
            "text": "I asked Bea about the wording",
        },
    ]
    catalogue = tool_catalog()
    assert "person_notes" in catalogue["read_ticket"].description
    assert not [name for name in catalogue if "card_note" in name or "ticket_note" in name]
