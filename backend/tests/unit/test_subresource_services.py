"""LabelService, ChecklistService and CommentService on an in-memory board: scopes, the board's
state, a Ticket's read-only Loop, ordering, who wrote a comment, the mention hook and the activity
each write leaves.

The services run their real code; the repositories, both units of work, the registry checks, the
clock and the id source are the typed fakes in ``tests/unit/fakes``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound
from app.db.generated.board import (
    CardLabelsRow,
    ChecklistItemsRow,
    ChecklistsRow,
    CommentsRow,
    LabelsRow,
)
from app.schemas.subresources import (
    ChecklistCreate,
    ChecklistItemCreate,
    ChecklistItemUpdate,
    ChecklistUpdate,
    CommentCreate,
    LabelCreate,
    LabelUpdate,
)
from app.services.boards import BoardService
from app.services.lists import BoardChecks
from app.services.loops import ensure_ticket_writable
from app.services.mentions import MentionService
from app.services.subresources import (
    ChecklistService,
    CommentService,
    LabelService,
    MentionQueue,
)
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardRepositories,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import (
    FakeRegistryUnitOfWork,
    RegistryState,
    actor_row,
    agent_row,
)

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
OPEN = "loop-open"
WRITE = frozenset({"cards:read", "cards:write", "comments:write"})
PERSON = ActorContext(
    actor_id="person", actor_type="user", actor_name="Grace", scopes=WRITE, request_id="req-1"
)
WORKER = ActorContext(actor_id="token-actor", actor_type="agent", actor_name="worker", scopes=WRITE)
READER = ActorContext(
    actor_id="reader", actor_type="user", actor_name="Reader", scopes=frozenset({"cards:read"})
)
# A card per way a Loop stops taking writes, and one whose Loop row is gone.
READ_ONLY_CARDS = ("done-card", "staged-card", "archived-card", "cancelled-card")


def board_service_fits(service: BoardService) -> BoardChecks:
    """Never called: pyright proves that the BoardService wired in Services fits BoardChecks."""
    return service


def mention_service_fits(service: MentionService) -> MentionQueue:
    """Never called: pyright proves that MentionService is the queue a comment hands itself to."""
    return service


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class Queue:
    """Records the mentions a comment hands over; raises when ``failure`` is set."""

    calls: list[tuple[str, str, str, str, str]] = field(
        default_factory=list[tuple[str, str, str, str, str]]
    )
    failure: Exception | None = None

    def queue(
        self, actor: ActorContext, board_id: str, card_id: str, comment_id: str, content: str
    ) -> object:
        self.calls.append((actor.actor_id, board_id, card_id, comment_id, content))
        if self.failure is not None:
            raise self.failure
        return ["job-1"]


@dataclass(slots=True)
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    checks: FakeBoardChecks
    registry: RegistryState
    labels: LabelService
    checklists: ChecklistService
    comments: CommentService
    queue: Queue

    def actions(self) -> list[tuple[str, str, str, dict[str, object]]]:
        return [
            (entry.action, entry.entity_type, entry.entity_id, json.loads(entry.changes_json))
            for entry in self.state.activity
        ]


def world() -> World:
    state = BoardState()
    state.loops = {
        OPEN: loop_row(OPEN),
        "done": loop_row("done", completed_at=CREATED),
        "staged": loop_row("staged", stage="completed"),
        "archived": loop_row("archived", archived_at=CREATED),
        "cancelled": loop_row("cancelled", stage="cancelled", cancelled_at=CREATED),
    }
    state.lists = {"todo": list_row("todo", OPEN, 1024)}
    cards = [
        card_row("c1", "todo", OPEN),
        card_row("c2", "todo", OPEN),
        card_row("done-card", "todo", "done"),
        card_row("staged-card", "todo", "staged"),
        card_row("archived-card", "todo", "archived"),
        card_row("cancelled-card", "todo", "cancelled"),
        card_row("orphan", "todo", "no-such-loop"),
    ]
    state.cards = {card.id: card for card in cards}
    state.labels = {
        "bug": LabelsRow(id="bug", name="Bug", color="#ff0000"),
        "idea": LabelsRow(id="idea", name="Idea", color="#00ff00"),
    }
    state.card_labels = [
        CardLabelsRow(card_id="c1", label_id="bug"),
        CardLabelsRow(card_id="c2", label_id="bug"),
        CardLabelsRow(card_id="c1", label_id="idea"),
    ]
    registry = RegistryState()
    registry.actors = {
        "person": actor_row("person", name="Grace"),
        "token-actor": actor_row("token-actor", type_="agent", name="worker"),
        "gone": actor_row("gone", name="Gone", disabled_at=CREATED),
    }
    registry.agents = {"helper": agent_row("helper", name="Helper")}
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    accounts = FakeRegistryUnitOfWork(registry)
    ids = Ids()
    queue = Queue()
    comments = CommentService(checks, store, accounts, clock=lambda: NOW, new_id=ids)
    comments.mentions = queue
    return World(
        state=state,
        store=store,
        checks=checks,
        registry=registry,
        labels=LabelService(checks, store, clock=lambda: NOW, new_id=ids),
        checklists=ChecklistService(checks, store, clock=lambda: NOW, new_id=ids),
        comments=comments,
        queue=queue,
    )


def checklist(checklist_id: str, card_id: str, position: int, title: str = "") -> ChecklistsRow:
    return ChecklistsRow(
        id=checklist_id, card_id=card_id, title=title or checklist_id, position=position
    )


def item(
    item_id: str, checklist_id: str, position: int, *, completed: int = 0
) -> ChecklistItemsRow:
    return ChecklistItemsRow(
        id=item_id, checklist_id=checklist_id, text=item_id, completed=completed, position=position
    )


def comment(comment_id: str, card_id: str, actor_id: str, created_at: str) -> CommentsRow:
    return CommentsRow(
        id=comment_id,
        card_id=card_id,
        actor_id=actor_id,
        content=f"text of {comment_id}",
        created_at=created_at,
        updated_at=created_at,
    )


def refused_as_read_only(raised: pytest.ExceptionInfo[Conflict], card_id: str) -> None:
    assert raised.value.code == "loop_read_only"
    assert raised.value.message == "This Loop is read-only"
    assert raised.value.details == {"card_id": card_id}


# --- a Ticket's Loop decides whether its subresources take writes ---------------------------------


@pytest.mark.parametrize("card_id", READ_ONLY_CARDS)
def test_a_finished_or_stopped_loop_refuses_writes_to_its_tickets(card_id: str) -> None:
    state = world().state
    with pytest.raises(Conflict) as raised:
        ensure_ticket_writable(FakeBoardRepositories(state), card_id)
    refused_as_read_only(raised, card_id)


@pytest.mark.parametrize("card_id", ["c1", "no-such-card", "orphan"])
def test_an_open_loop_or_a_missing_ticket_or_loop_passes(card_id: str) -> None:
    ensure_ticket_writable(FakeBoardRepositories(world().state), card_id)


# --- labels -------------------------------------------------------------------------------------


def test_labels_are_listed_by_name_after_the_board_check() -> None:
    w = world()
    w.state.labels["aaa"] = LabelsRow(id="aaa", name="Zebra", color="#000000")
    assert w.labels.list(BOARD_ID) == [
        {"id": "bug", "name": "Bug", "color": "#ff0000"},
        {"id": "idea", "name": "Idea", "color": "#00ff00"},
        {"id": "aaa", "name": "Zebra", "color": "#000000"},
    ]
    assert w.checks.calls == [("require_row", BOARD_ID)]


def test_listing_labels_of_an_unregistered_board_is_not_found() -> None:
    w = world()
    w.checks.unregistered = frozenset({BOARD_ID})
    with pytest.raises(NotFound):
        w.labels.list(BOARD_ID)


def test_a_new_label_is_stored_and_logged() -> None:
    w = world()
    entry = w.labels.create(PERSON, BOARD_ID, LabelCreate(name="Urgent", color="#123456"))
    assert entry == {"id": "new-1", "name": "Urgent", "color": "#123456"}
    assert w.state.labels["new-1"] == LabelsRow(id="new-1", name="Urgent", color="#123456")
    assert w.actions() == [
        ("label.created", "label", "new-1", {"name": "Urgent", "color": "#123456"})
    ]
    (logged,) = w.state.activity
    assert (logged.id, logged.timestamp, logged.request_id) == ("new-2", STAMP, "req-1")
    assert w.checks.calls == [("ensure_active", BOARD_ID)]


def name_taken(raised: pytest.ExceptionInfo[Conflict], name: str) -> None:
    assert (raised.value.status_code, raised.value.code) == (409, "label_name_taken")
    assert raised.value.message == "A label with this name already exists"
    assert raised.value.details == {"name": name}


def test_a_label_name_is_unique_but_may_equal_another_labels_id() -> None:
    w = world()
    with pytest.raises(Conflict) as raised:
        w.labels.create(PERSON, BOARD_ID, LabelCreate(name="Bug"))
    name_taken(raised, "Bug")
    assert w.store.rollbacks == 1
    assert set(w.state.labels) == {"bug", "idea"}
    entry = w.labels.create(PERSON, BOARD_ID, LabelCreate(name="bug"))
    assert entry == {"id": "new-2", "name": "bug", "color": "#64748b"}


def test_a_label_renamed_to_a_taken_name_is_refused_and_keeps_its_own() -> None:
    # Was the database's unique refusal unmapped: a 500.
    w = world()
    with pytest.raises(Conflict) as raised:
        w.labels.update(PERSON, BOARD_ID, "bug", LabelUpdate(name="Idea", color="#0000ff"))
    name_taken(raised, "Idea")
    assert w.store.rollbacks == 1
    assert w.state.labels["bug"] == LabelsRow(id="bug", name="Bug", color="#ff0000")
    assert w.state.activity == []
    # Its own name is not taken by itself, and a name differing only in case is another name.
    assert w.labels.update(PERSON, BOARD_ID, "bug", LabelUpdate(name="Bug"))["name"] == "Bug"
    assert w.labels.update(PERSON, BOARD_ID, "bug", LabelUpdate(name="idea"))["name"] == "idea"


def test_writing_labels_needs_the_card_scope_and_a_board_that_takes_writes() -> None:
    w = world()
    with pytest.raises(Forbidden):
        w.labels.create(READER, BOARD_ID, LabelCreate(name="X"))
    with pytest.raises(Forbidden):
        w.labels.update(READER, BOARD_ID, "bug", LabelUpdate(name="X"))
    with pytest.raises(Forbidden):
        w.labels.delete(READER, BOARD_ID, "bug")
    w.checks.archived = frozenset({BOARD_ID})
    for write in (
        lambda: w.labels.create(PERSON, BOARD_ID, LabelCreate(name="X")),
        lambda: w.labels.update(PERSON, BOARD_ID, "bug", LabelUpdate(name="X")),
        lambda: w.labels.delete(PERSON, BOARD_ID, "bug"),
    ):
        with pytest.raises(Conflict, match="archived"):
            write()
    assert w.state.labels["bug"].name == "Bug"
    assert w.state.activity == []


@pytest.mark.parametrize(
    ("payload", "after", "changes"),
    [
        (LabelUpdate(name="Defect"), ("Defect", "#ff0000"), {"name": "Defect"}),
        (LabelUpdate(color="#0000ff"), ("Bug", "#0000ff"), {"color": "#0000ff"}),
        (
            LabelUpdate(color="#0000ff", name="Defect"),
            ("Defect", "#0000ff"),
            {"name": "Defect", "color": "#0000ff"},
        ),
    ],
)
def test_a_label_edit_writes_and_logs_only_what_is_given(
    payload: LabelUpdate, after: tuple[str, str], changes: dict[str, str]
) -> None:
    w = world()
    entry = w.labels.update(PERSON, BOARD_ID, "bug", payload)
    assert entry == {"id": "bug", "name": after[0], "color": after[1]}
    assert w.state.labels["bug"] == LabelsRow(id="bug", name=after[0], color=after[1])
    before = {"id": "bug", "name": "Bug", "color": "#ff0000"}
    assert w.actions() == [
        ("label.updated", "label", "bug", {"before": before, "after": changes})
    ]
    assert list(json.loads(w.state.activity[0].changes_json)["after"]) == list(changes)


def test_an_empty_label_edit_writes_nothing_and_answers_the_label() -> None:
    w = world()
    entry = w.labels.update(PERSON, BOARD_ID, "bug", LabelUpdate())
    assert entry == {"id": "bug", "name": "Bug", "color": "#ff0000"}
    assert w.state.activity == []


def test_an_unknown_label_is_not_found() -> None:
    w = world()
    with pytest.raises(NotFound, match="Label not found"):
        w.labels.update(PERSON, BOARD_ID, "nope", LabelUpdate(name="X"))
    with pytest.raises(NotFound, match="Label not found"):
        w.labels.update(PERSON, BOARD_ID, "nope", LabelUpdate())
    with pytest.raises(NotFound, match="Label not found"):
        w.labels.delete(PERSON, BOARD_ID, "nope")


def test_a_deleted_label_leaves_every_card_that_carried_it() -> None:
    w = world()
    w.labels.delete(PERSON, BOARD_ID, "bug")
    assert set(w.state.labels) == {"idea"}
    assert w.state.card_labels == [CardLabelsRow(card_id="c1", label_id="idea")]
    assert w.actions() == [("label.deleted", "label", "bug", {"name": "Bug"})]


# --- checklists ---------------------------------------------------------------------------------


def test_checklists_are_listed_in_order_with_their_own_items_in_order() -> None:
    w = world()
    w.state.checklists = {
        row.id: row
        for row in (
            checklist("b", "c1", 2048),
            checklist("a", "c1", 2048),
            checklist("first", "c1", 1024),
            checklist("other-card", "c2", 512),
        )
    }
    w.state.checklist_items = {
        row.id: row
        for row in (
            item("i2", "a", 2048),
            item("i1", "a", 1024, completed=1),
            item("i0", "a", 1024),
            item("j1", "first", 512),
            item("x1", "other-card", 1),
        )
    }
    listed = w.checklists.list(BOARD_ID, "c1")
    assert [entry["id"] for entry in listed] == ["first", "a", "b"]
    assert listed[1] == {
        "id": "a",
        "card_id": "c1",
        "title": "a",
        "position": 2048,
        "items": [
            {"id": "i0", "checklist_id": "a", "text": "i0", "completed": False, "position": 1024},
            {"id": "i1", "checklist_id": "a", "text": "i1", "completed": True, "position": 1024},
            {"id": "i2", "checklist_id": "a", "text": "i2", "completed": False, "position": 2048},
        ],
    }
    assert [i["id"] for i in listed[0]["items"]] == ["j1"]
    assert listed[2]["items"] == []
    assert w.checks.calls == [("require_row", BOARD_ID)]


def test_checklists_of_an_unknown_card_are_not_found() -> None:
    with pytest.raises(NotFound, match="Card not found"):
        world().checklists.list(BOARD_ID, "nope")


def test_a_new_checklist_goes_after_the_cards_others() -> None:
    w = world()
    w.state.checklists = {"a": checklist("a", "c1", 3000), "z": checklist("z", "c2", 9000)}
    entry = w.checklists.create(PERSON, BOARD_ID, "c1", ChecklistCreate(title="Steps"))
    assert entry == {
        "id": "new-1",
        "card_id": "c1",
        "title": "Steps",
        "position": 3000 + 1024,
        "items": [],
    }
    assert w.state.checklists["new-1"] == checklist("new-1", "c1", 4024, "Steps")
    assert w.actions() == [
        ("checklist.created", "checklist", "new-1", {"card_id": "c1", "title": "Steps"})
    ]


def test_the_first_checklist_of_a_card_takes_the_first_gap() -> None:
    w = world()
    entry = w.checklists.create(PERSON, BOARD_ID, "c2", ChecklistCreate(title="Steps"))
    assert entry["position"] == 1024


def test_a_checklist_needs_a_ticket_whose_loop_takes_writes() -> None:
    w = world()
    with pytest.raises(NotFound, match="Card not found"):
        w.checklists.create(PERSON, BOARD_ID, "nope", ChecklistCreate(title="X"))
    for card_id in READ_ONLY_CARDS:
        with pytest.raises(Conflict) as raised:
            w.checklists.create(PERSON, BOARD_ID, card_id, ChecklistCreate(title="X"))
        refused_as_read_only(raised, card_id)
    with pytest.raises(Forbidden):
        w.checklists.create(READER, BOARD_ID, "c1", ChecklistCreate(title="X"))
    assert w.state.checklists == {}
    assert w.state.activity == []


def test_renaming_a_checklist_logs_the_titles_and_answers_its_items() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024, "Old"), "o": checklist("o", "c1", 9)}
    w.state.checklist_items = {
        "i2": item("i2", "k", 2048),
        "i1": item("i1", "k", 1024, completed=1),
        "x": item("x", "o", 1),
    }
    entry = w.checklists.update(PERSON, BOARD_ID, "k", ChecklistUpdate(title="New"))
    assert entry["title"] == "New"
    assert [(i["id"], i["completed"]) for i in entry["items"]] == [("i1", True), ("i2", False)]
    assert w.state.checklists["k"].title == "New"
    assert w.actions() == [
        ("checklist.updated", "checklist", "k", {"before": "Old", "after": "New"})
    ]


@pytest.mark.parametrize("title", [None, "Same"])
def test_a_checklist_edit_without_a_new_title_writes_nothing(title: str | None) -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024, "Same")}
    entry = w.checklists.update(PERSON, BOARD_ID, "k", ChecklistUpdate(title=title))
    assert entry == {"id": "k", "card_id": "c1", "title": "Same", "position": 1024, "items": []}
    assert w.state.activity == []


def test_a_deleted_checklist_takes_its_items_with_it() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024), "o": checklist("o", "c1", 2048)}
    w.state.checklist_items = {"i": item("i", "k", 1), "j": item("j", "o", 1)}
    w.checklists.delete(PERSON, BOARD_ID, "k")
    assert set(w.state.checklists) == {"o"}
    assert set(w.state.checklist_items) == {"j"}
    assert w.actions() == [("checklist.deleted", "checklist", "k", {"card_id": "c1"})]


def test_an_unknown_checklist_is_not_found() -> None:
    w = world()
    with pytest.raises(NotFound, match="Checklist not found"):
        w.checklists.update(PERSON, BOARD_ID, "nope", ChecklistUpdate(title="X"))
    with pytest.raises(NotFound, match="Checklist not found"):
        w.checklists.delete(PERSON, BOARD_ID, "nope")
    with pytest.raises(NotFound, match="Checklist not found"):
        w.checklists.add_item(PERSON, BOARD_ID, "nope", ChecklistItemCreate(text="X"))


def test_a_checklist_on_a_read_only_loop_takes_no_writes() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "done-card", 1024, "Same")}
    w.state.checklist_items = {"i": item("i", "k", 1024)}
    writes = (
        lambda: w.checklists.update(PERSON, BOARD_ID, "k", ChecklistUpdate(title="New")),
        lambda: w.checklists.update(PERSON, BOARD_ID, "k", ChecklistUpdate()),
        lambda: w.checklists.delete(PERSON, BOARD_ID, "k"),
        lambda: w.checklists.add_item(PERSON, BOARD_ID, "k", ChecklistItemCreate(text="X")),
        lambda: w.checklists.update_item(PERSON, BOARD_ID, "i", ChecklistItemUpdate(text="X")),
        lambda: w.checklists.update_item(PERSON, BOARD_ID, "i", ChecklistItemUpdate()),
        lambda: w.checklists.delete_item(PERSON, BOARD_ID, "i"),
    )
    for write in writes:
        with pytest.raises(Conflict) as raised:
            write()
        refused_as_read_only(raised, "done-card")
    assert w.state.checklists["k"].title == "Same"
    assert set(w.state.checklist_items) == {"i"}
    assert w.state.activity == []


def test_checklist_writes_need_the_card_scope_and_a_board_that_takes_writes() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024)}
    w.state.checklist_items = {"i": item("i", "k", 1024)}
    writes: tuple[Callable[[ActorContext], object], ...] = (
        lambda actor: w.checklists.update(actor, BOARD_ID, "k", ChecklistUpdate(title="New")),
        lambda actor: w.checklists.delete(actor, BOARD_ID, "k"),
        lambda actor: w.checklists.add_item(actor, BOARD_ID, "k", ChecklistItemCreate(text="X")),
        lambda actor: w.checklists.update_item(
            actor, BOARD_ID, "i", ChecklistItemUpdate(text="X")
        ),
        lambda actor: w.checklists.delete_item(actor, BOARD_ID, "i"),
    )
    for write in writes:
        with pytest.raises(Forbidden):
            write(READER)
    w.checks.archived = frozenset({BOARD_ID})
    for write in writes:
        with pytest.raises(Conflict, match="archived"):
            write(PERSON)
    with pytest.raises(Conflict, match="archived"):
        w.checklists.create(PERSON, BOARD_ID, "c1", ChecklistCreate(title="X"))
    assert set(w.state.checklists) == {"k"}
    assert w.state.activity == []


@pytest.mark.parametrize(
    ("position", "expected"),
    [(None, 3072), (99, 3072), (0, 512), (1, 1536), (2, 3072)],
)
def test_a_new_item_takes_its_place_among_the_checklists_items(
    position: int | None, expected: int
) -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024), "o": checklist("o", "c1", 2048)}
    w.state.checklist_items = {
        "a": item("a", "k", 1024),
        "b": item("b", "k", 2048),
        "elsewhere": item("elsewhere", "o", 1),
    }
    entry = w.checklists.add_item(
        PERSON, BOARD_ID, "k", ChecklistItemCreate(text="new", position=position)
    )
    assert entry == {
        "id": "new-1",
        "checklist_id": "k",
        "text": "new",
        "completed": False,
        "position": expected,
    }
    assert w.state.checklist_items["new-1"].completed == 0
    assert w.state.checklist_items["elsewhere"].position == 1
    assert w.actions() == [
        ("checklist.item_added", "checklist_item", "new-1", {"checklist_id": "k", "text": "new"})
    ]


def test_an_item_with_no_room_renumbers_its_siblings_first() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024)}
    w.state.checklist_items = {"a": item("a", "k", 1), "b": item("b", "k", 2)}
    entry = w.checklists.add_item(
        PERSON, BOARD_ID, "k", ChecklistItemCreate(text="mid", position=1)
    )
    assert entry["position"] == 1536
    assert (w.state.checklist_items["a"].position, w.state.checklist_items["b"].position) == (
        1024,
        2048,
    )


def test_an_item_edit_writes_and_logs_text_completion_and_place() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024)}
    w.state.checklist_items = {
        "a": item("a", "k", 1024),
        "b": item("b", "k", 2048),
        "c": item("c", "k", 3072),
    }
    entry = w.checklists.update_item(
        PERSON, BOARD_ID, "c", ChecklistItemUpdate(position=0, completed=True, text="first")
    )
    assert entry == {
        "id": "c",
        "checklist_id": "k",
        "text": "first",
        "completed": True,
        "position": 512,
    }
    assert w.state.checklist_items["c"] == item("c", "k", 512, completed=1).__replace__(
        text="first"
    )
    assert w.actions() == [
        (
            "checklist.item_updated",
            "checklist_item",
            "c",
            {"text": "first", "completed": 1, "position": 512},
        )
    ]
    assert list(json.loads(w.state.activity[0].changes_json)) == ["text", "completed", "position"]


def test_an_item_moves_among_its_siblings_without_itself() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024)}
    w.state.checklist_items = {
        "a": item("a", "k", 1024),
        "b": item("b", "k", 2048),
        "c": item("c", "k", 3072),
    }
    entry = w.checklists.update_item(PERSON, BOARD_ID, "a", ChecklistItemUpdate(position=1))
    assert entry["position"] == 2560
    entry = w.checklists.update_item(PERSON, BOARD_ID, "a", ChecklistItemUpdate(position=5))
    assert entry["position"] == 3072 + 1024


def test_reopening_an_item_stores_zero() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024)}
    w.state.checklist_items = {"a": item("a", "k", 1024, completed=1)}
    entry = w.checklists.update_item(PERSON, BOARD_ID, "a", ChecklistItemUpdate(completed=False))
    assert entry["completed"] is False
    assert w.state.checklist_items["a"].completed == 0
    assert w.actions()[0][3] == {"completed": 0}


def test_an_empty_item_edit_writes_nothing_and_answers_the_item() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024)}
    w.state.checklist_items = {"a": item("a", "k", 1024, completed=1)}
    entry = w.checklists.update_item(PERSON, BOARD_ID, "a", ChecklistItemUpdate())
    assert entry == {
        "id": "a",
        "checklist_id": "k",
        "text": "a",
        "completed": True,
        "position": 1024,
    }
    assert w.state.activity == []


def test_a_deleted_item_is_logged_with_its_text() -> None:
    w = world()
    w.state.checklists = {"k": checklist("k", "c1", 1024)}
    w.state.checklist_items = {"a": item("a", "k", 1024), "b": item("b", "k", 2048)}
    w.checklists.delete_item(PERSON, BOARD_ID, "a")
    assert set(w.state.checklist_items) == {"b"}
    assert w.actions() == [
        ("checklist.item_deleted", "checklist_item", "a", {"checklist_id": "k", "text": "a"})
    ]


def test_an_unknown_item_is_not_found() -> None:
    w = world()
    with pytest.raises(NotFound, match="Checklist item not found"):
        w.checklists.update_item(PERSON, BOARD_ID, "nope", ChecklistItemUpdate(text="X"))
    with pytest.raises(NotFound, match="Checklist item not found"):
        w.checklists.delete_item(PERSON, BOARD_ID, "nope")


def test_an_item_whose_checklist_row_is_gone_is_still_writable() -> None:
    # Only a hand-edited database has one (the foreign key cascades); the old join found no card.
    w = world()
    w.state.checklist_items = {"a": item("a", "gone", 1024)}
    entry = w.checklists.update_item(PERSON, BOARD_ID, "a", ChecklistItemUpdate(text="still"))
    assert entry["text"] == "still"


# --- comments -----------------------------------------------------------------------------------


def test_comments_are_listed_oldest_first_with_their_authors() -> None:
    w = world()
    rows = (
        comment("late", "c1", "person", "2026-11-03T09:00:00Z"),
        comment("tie-2", "c1", "token-actor", "2026-11-02T09:00:00Z"),
        comment("tie-1", "c1", "helper", "2026-11-02T09:00:00Z"),
        comment("ghost", "c1", "nobody", "2026-11-01T09:00:00Z"),
        comment("disabled", "c1", "gone", "2026-11-03T09:30:00Z"),
        comment("other", "c2", "person", "2026-11-01T00:00:00Z"),
    )
    w.state.comments = {row.id: row for row in rows}
    listed = w.comments.list(BOARD_ID, "c1")
    authors = [(entry["id"], entry["actor_name"], entry["actor_type"]) for entry in listed]
    assert authors == [
        ("ghost", None, None),
        ("tie-2", "worker", "agent"),
        ("tie-1", "Helper", "agent"),
        ("late", "Grace", "user"),
        ("disabled", "Gone", "user"),
    ]
    assert listed[3] == {
        "id": "late",
        "card_id": "c1",
        "actor_id": "person",
        "content": "text of late",
        "created_at": "2026-11-03T09:00:00Z",
        "updated_at": "2026-11-03T09:00:00Z",
        "actor_name": "Grace",
        "actor_type": "user",
    }
    assert w.checks.calls == [("require_row", BOARD_ID)]


def test_an_actor_row_wins_over_an_agent_profile_with_the_same_id() -> None:
    w = world()
    w.registry.agents["person"] = w.registry.agents["helper"].__replace__(id="person")
    w.state.comments = {"m": comment("m", "c1", "person", CREATED)}
    (entry,) = w.comments.list(BOARD_ID, "c1")
    assert (entry["actor_name"], entry["actor_type"]) == ("Grace", "user")


def test_a_ticket_without_comments_lists_none() -> None:
    assert world().comments.list(BOARD_ID, "c1") == []


def test_a_new_comment_is_stored_logged_and_answered_with_its_author() -> None:
    w = world()
    entry = w.comments.create(WORKER, BOARD_ID, "c1", CommentCreate(content="Done here"))
    assert entry == {
        "id": "new-1",
        "card_id": "c1",
        "actor_id": "token-actor",
        "content": "Done here",
        "created_at": STAMP,
        "updated_at": STAMP,
        "actor_name": "worker",
        "actor_type": "agent",
    }
    assert w.state.comments["new-1"] == CommentsRow(
        id="new-1",
        card_id="c1",
        actor_id="token-actor",
        content="Done here",
        created_at=STAMP,
        updated_at=STAMP,
    )
    assert w.actions() == [("comment.created", "comment", "new-1", {"card_id": "c1"})]
    assert w.queue.calls == []
    assert w.checks.calls == [("ensure_active", BOARD_ID)]


def test_a_comment_that_mentions_someone_is_handed_to_the_queue() -> None:
    w = world()
    w.comments.create(PERSON, BOARD_ID, "c1", CommentCreate(content="@Helper look"))
    assert w.queue.calls == [("person", BOARD_ID, "c1", "new-1", "@Helper look")]


def test_a_failing_mention_queue_leaves_the_comment_saved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = world()
    w.queue.failure = RuntimeError("queue is down")
    with caplog.at_level(logging.ERROR, logger="app.services.subresources"):
        entry = w.comments.create(PERSON, BOARD_ID, "c1", CommentCreate(content="@Helper"))
    assert entry["id"] == "new-1"
    assert "new-1" in w.state.comments
    assert [record.getMessage() for record in caplog.records] == [
        "Could not queue mentions for comment new-1"
    ]


def test_without_a_mention_queue_a_mention_is_only_a_comment() -> None:
    w = world()
    w.comments.mentions = None
    entry = w.comments.create(PERSON, BOARD_ID, "c1", CommentCreate(content="@Helper"))
    assert entry["content"] == "@Helper"


def test_a_comment_needs_its_scope_a_ticket_and_a_loop_that_takes_writes() -> None:
    w = world()
    no_comments = ActorContext(
        actor_id="person", actor_type="user", actor_name="Grace", scopes=frozenset({"cards:write"})
    )
    with pytest.raises(Forbidden):
        w.comments.create(no_comments, BOARD_ID, "c1", CommentCreate(content="x"))
    with pytest.raises(NotFound, match="Card not found"):
        w.comments.create(PERSON, BOARD_ID, "nope", CommentCreate(content="x"))
    for card_id in READ_ONLY_CARDS:
        with pytest.raises(Conflict) as raised:
            w.comments.create(PERSON, BOARD_ID, card_id, CommentCreate(content="@Helper"))
        refused_as_read_only(raised, card_id)
    w.checks.archived = frozenset({BOARD_ID})
    with pytest.raises(Conflict, match="archived"):
        w.comments.create(PERSON, BOARD_ID, "c1", CommentCreate(content="x"))
    assert w.state.comments == {}
    assert w.state.activity == []
    assert w.queue.calls == []


def test_a_person_edits_any_comment_and_an_agent_only_its_own() -> None:
    w = world()
    w.state.comments = {
        "mine": comment("mine", "c1", "token-actor", CREATED),
        "theirs": comment("theirs", "c1", "person", CREATED),
    }
    with pytest.raises(Forbidden, match="Agents may only modify their own comments"):
        w.comments.update(WORKER, BOARD_ID, "theirs", CommentCreate(content="x"))
    with pytest.raises(Forbidden, match="Agents may only modify their own comments"):
        w.comments.delete(WORKER, BOARD_ID, "theirs")
    entry = w.comments.update(WORKER, BOARD_ID, "mine", CommentCreate(content="edited"))
    assert (entry["content"], entry["created_at"], entry["updated_at"]) == (
        "edited",
        CREATED,
        STAMP,
    )
    assert (entry["actor_name"], entry["actor_type"]) == ("worker", "agent")
    assert w.state.comments["mine"].content == "edited"
    assert w.state.comments["mine"].updated_at == STAMP
    entry = w.comments.update(PERSON, BOARD_ID, "mine", CommentCreate(content="by a person"))
    assert entry["actor_id"] == "token-actor"
    assert w.actions() == [
        ("comment.updated", "comment", "mine", {"card_id": "c1"}),
        ("comment.updated", "comment", "mine", {"card_id": "c1"}),
    ]
    w.comments.delete(PERSON, BOARD_ID, "theirs")
    w.comments.delete(WORKER, BOARD_ID, "mine")
    assert w.state.comments == {}
    assert w.actions()[2:] == [
        ("comment.deleted", "comment", "theirs", {"card_id": "c1"}),
        ("comment.deleted", "comment", "mine", {"card_id": "c1"}),
    ]


def test_a_comment_on_a_read_only_loop_is_not_changed_after_the_owner_check() -> None:
    w = world()
    w.state.comments = {"old": comment("old", "done-card", "person", CREATED)}
    for write in (
        lambda: w.comments.update(PERSON, BOARD_ID, "old", CommentCreate(content="x")),
        lambda: w.comments.delete(PERSON, BOARD_ID, "old"),
    ):
        with pytest.raises(Conflict) as raised:
            write()
        refused_as_read_only(raised, "done-card")
    with pytest.raises(Forbidden):
        w.comments.update(WORKER, BOARD_ID, "old", CommentCreate(content="x"))
    assert w.state.comments["old"].content == "text of old"
    assert w.state.activity == []


def test_an_unknown_comment_is_not_found_and_writes_need_the_scope() -> None:
    w = world()
    with pytest.raises(NotFound, match="Comment not found"):
        w.comments.update(PERSON, BOARD_ID, "nope", CommentCreate(content="x"))
    with pytest.raises(NotFound, match="Comment not found"):
        w.comments.delete(PERSON, BOARD_ID, "nope")
    w.state.comments = {"m": comment("m", "c1", "reader", CREATED)}
    with pytest.raises(Forbidden):
        w.comments.update(READER, BOARD_ID, "m", CommentCreate(content="x"))
    with pytest.raises(Forbidden):
        w.comments.delete(READER, BOARD_ID, "m")
    w.checks.archived = frozenset({BOARD_ID})
    with pytest.raises(Conflict, match="archived"):
        w.comments.update(PERSON, BOARD_ID, "m", CommentCreate(content="x"))
    with pytest.raises(Conflict, match="archived"):
        w.comments.delete(PERSON, BOARD_ID, "m")
