"""ListService's rules on an in-memory board: ownership, ordering, counts, archive and errors.

The service runs its real code; only the repositories, the unit of work, the registry checks, the
clock and the id source are replaced, by the typed fakes in ``tests/unit/fakes``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.db.generated.board import LoopsRow
from app.schemas.lists import ListCreate, ListMove, ListUpdate
from app.services.boards import BoardService
from app.services.lists import BoardChecks, ListEntry, ListService
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

NOW = "2026-11-03T10:00:00Z"
EARLIER = "2026-10-01T08:00:00Z"
LOOP = "loop-a"
OTHER_LOOP = "loop-b"
ACTOR = ActorContext(
    actor_id="actor-1",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"cards:read", "cards:write"}),
    request_id="request-1",
)
READER = ActorContext(
    actor_id="actor-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"cards:read"})
)


def board_service_is_what_list_service_needs(service: BoardService) -> BoardChecks:
    """Never called: pyright proves that the BoardService wired in Services fits BoardChecks."""
    return service


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class Board:
    state: BoardState
    store: FakeBoardUnitOfWork
    checks: FakeBoardChecks
    service: ListService

    def positions(self) -> dict[str, int]:
        return {row.id: row.position for row in self.state.lists.values() if row.loop_id == LOOP}


def board(*lists: tuple[str, int], archived: tuple[str, ...] = ()) -> Board:
    """A board with Loops ``LOOP`` and ``OTHER_LOOP``; ``lists`` are ``LOOP``'s (id, position)."""
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP), OTHER_LOOP: loop_row(OTHER_LOOP)}
    rows = [
        list_row(list_id, LOOP, position, archived_at=EARLIER if list_id in archived else None)
        for list_id, position in lists
    ]
    rows.append(list_row("elsewhere", OTHER_LOOP, 1024))
    state.lists = {row.id: row for row in rows}
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    return Board(state, store, checks, ListService(checks, store, clock=lambda: NOW, new_id=Ids()))


@pytest.fixture
def kanban() -> Board:
    """To do, Doing, Done, and an archived column."""
    world = board(("todo", 1024), ("doing", 2048), ("done", 3072), ("old", 512), archived=("old",))
    world.state.lists["todo"] = world.state.lists["todo"].__replace__(name="To do")
    return world


def only_activity(world: Board) -> tuple[str, str, dict[str, object]]:
    (entry,) = world.state.activity
    return entry.action, entry.entity_id, json.loads(entry.changes_json)


# --- reads ---------------------------------------------------------------------------------------


def test_list_returns_the_loops_unarchived_lists_in_order_with_unarchived_card_counts(
    kanban: Board,
) -> None:
    cards = [
        card_row("c1", "todo", LOOP),
        card_row("c2", "todo", LOOP),
        card_row("c3", "todo", LOOP, archived_at=EARLIER),
        card_row("c4", "doing", LOOP),
        card_row("c5", "elsewhere", OTHER_LOOP),
    ]
    kanban.state.cards = {card.id: card for card in cards}

    entries = kanban.service.list(BOARD_ID, LOOP)

    assert [entry["id"] for entry in entries] == ["todo", "doing", "done"]
    assert [entry["card_count"] for entry in entries] == [2, 1, 0]
    expected: ListEntry = {
        "id": "todo",
        "name": "To do",
        "position": 1024,
        "created_at": CREATED,
        "updated_at": CREATED,
        "archived_at": None,
        "loop_id": LOOP,
        "board_id": BOARD_ID,
        "card_count": 2,
    }
    assert entries[0] == expected
    # The key order of the former ``SELECT *`` (the table's columns), then board and count.
    assert list(entries[0]) == list(expected)
    assert kanban.checks.calls == [("require_row", BOARD_ID)]


def test_list_includes_archived_lists_only_when_asked(kanban: Board) -> None:
    entries = kanban.service.list(BOARD_ID, LOOP, include_archived=True)

    assert [entry["id"] for entry in entries] == ["old", "todo", "doing", "done"]
    assert entries[0]["archived_at"] == EARLIER


def test_lists_on_the_same_position_are_ordered_by_id() -> None:
    world = board(("b", 1024), ("a", 1024), ("c", 512))

    assert [entry["id"] for entry in world.service.list(BOARD_ID, LOOP)] == ["c", "a", "b"]


def test_list_checks_the_registry_row_the_database_and_the_loop_in_that_order(
    kanban: Board,
) -> None:
    kanban.checks.unregistered = frozenset({BOARD_ID})
    with pytest.raises(NotFound, match="Board not found"):
        kanban.service.list(BOARD_ID, LOOP)

    kanban.checks.unregistered = frozenset()
    kanban.store.databases.clear()
    with pytest.raises(NotFound, match="Board database not found"):
        kanban.service.list(BOARD_ID, LOOP)

    kanban.store.databases.add(BOARD_ID)
    with pytest.raises(NotFound, match="Loop not found") as missing:
        kanban.service.list(BOARD_ID, "no-such-loop")
    assert missing.value.code == "loop_not_found"


def test_get_returns_one_list_with_its_unarchived_card_count(kanban: Board) -> None:
    cards = [card_row("c1", "doing", LOOP), card_row("c2", "doing", LOOP, archived_at=EARLIER)]
    kanban.state.cards = {card.id: card for card in cards}

    entry = kanban.service.get(BOARD_ID, LOOP, "doing")

    assert (entry["id"], entry["position"], entry["card_count"]) == ("doing", 2048, 1)


def test_an_unknown_list_is_not_found(kanban: Board) -> None:
    with pytest.raises(NotFound, match="List not found") as missing:
        kanban.service.get(BOARD_ID, LOOP, "no-such-list")
    assert missing.value.code == "not_found"


def test_a_list_of_another_loop_is_a_loop_mismatch_on_every_path(kanban: Board) -> None:
    calls = [
        lambda: kanban.service.get(BOARD_ID, LOOP, "elsewhere"),
        lambda: kanban.service.update(ACTOR, BOARD_ID, LOOP, "elsewhere", ListUpdate(name="x")),
        lambda: kanban.service.move(ACTOR, BOARD_ID, LOOP, "elsewhere", ListMove(position=0)),
        lambda: kanban.service.archive(ACTOR, BOARD_ID, LOOP, "elsewhere"),
        lambda: kanban.service.restore(ACTOR, BOARD_ID, LOOP, "elsewhere"),
        lambda: kanban.service.delete(ACTOR, BOARD_ID, LOOP, "elsewhere"),
    ]
    for call in calls:
        with pytest.raises(Conflict, match="belongs to another Loop") as mismatch:
            call()
        assert mismatch.value.code == "loop_mismatch"
        assert mismatch.value.details == {"loop_id": LOOP, "list_loop_id": OTHER_LOOP}
    assert kanban.state.activity == []


# --- create --------------------------------------------------------------------------------------


def test_create_appends_after_the_last_unarchived_list_and_logs_it(kanban: Board) -> None:
    entry = kanban.service.create(ACTOR, BOARD_ID, LOOP, ListCreate(name="Review"))

    assert entry == {
        "id": "new-1",
        "name": "Review",
        "position": 4096,
        "created_at": NOW,
        "updated_at": NOW,
        "archived_at": None,
        "loop_id": LOOP,
        "board_id": BOARD_ID,
        "card_count": 0,
    }
    assert kanban.state.lists["new-1"].position == 4096
    (activity,) = kanban.state.activity
    assert activity.id == "new-2"
    assert (activity.actor_id, activity.actor_type, activity.request_id) == (
        "actor-1",
        "user",
        "request-1",
    )
    assert (activity.action, activity.entity_type, activity.entity_id) == (
        "list.created",
        "list",
        "new-1",
    )
    assert json.loads(activity.changes_json) == {"name": "Review", "loop_id": LOOP}
    assert activity.timestamp == NOW
    assert (kanban.store.commits, kanban.checks.calls) == (1, [("ensure_active", BOARD_ID)])


@pytest.mark.parametrize(
    ("index", "position"), [(0, 512), (1, 1536), (2, 2560), (3, 4096), (99, 4096)]
)
def test_create_at_an_index_takes_the_gap_between_its_neighbours(
    kanban: Board, index: int, position: int
) -> None:
    entry = kanban.service.create(ACTOR, BOARD_ID, LOOP, ListCreate(name="New", position=index))

    assert entry["position"] == position


def test_create_into_a_used_up_gap_renumbers_the_lists_first() -> None:
    world = board(("a", 1), ("b", 2))

    entry = world.service.create(ACTOR, BOARD_ID, LOOP, ListCreate(name="New", position=1))

    assert entry["position"] == 1536
    assert world.positions() == {"a": 1024, "b": 2048, "new-1": 1536}
    # Renumbering is not an edit of the other lists.
    assert world.state.lists["a"].updated_at == CREATED


def test_writing_needs_the_cards_write_scope(kanban: Board) -> None:
    with pytest.raises(Forbidden, match="cards:write"):
        kanban.service.create(READER, BOARD_ID, LOOP, ListCreate(name="New"))

    assert (kanban.store.commits, kanban.checks.calls, kanban.state.activity) == (0, [], [])


def test_an_archived_board_takes_no_writes(kanban: Board) -> None:
    kanban.checks.archived = frozenset({BOARD_ID})

    with pytest.raises(Conflict) as refused:
        kanban.service.create(ACTOR, BOARD_ID, LOOP, ListCreate(name="New"))

    assert refused.value.code == "board_archived"
    assert (kanban.store.commits, kanban.store.rollbacks) == (0, 0)


@pytest.mark.parametrize(
    ("loop", "message"),
    [
        (loop_row(LOOP, stage="completed"), "completed and read-only"),
        (loop_row(LOOP, completed_at=EARLIER), "completed and read-only"),
        (loop_row(LOOP, archived_at=EARLIER), "not editable"),
        (loop_row(LOOP, cancelled_at=EARLIER), "not editable"),
    ],
)
def test_a_finished_or_withdrawn_loop_takes_no_list_changes(
    kanban: Board, loop: LoopsRow, message: str
) -> None:
    kanban.state.loops[LOOP] = loop
    before = kanban.state.snapshot()
    writes = [
        lambda: kanban.service.create(ACTOR, BOARD_ID, LOOP, ListCreate(name="New")),
        lambda: kanban.service.update(ACTOR, BOARD_ID, LOOP, "todo", ListUpdate(name="x")),
        lambda: kanban.service.move(ACTOR, BOARD_ID, LOOP, "todo", ListMove(position=2)),
        lambda: kanban.service.archive(ACTOR, BOARD_ID, LOOP, "todo"),
        lambda: kanban.service.restore(ACTOR, BOARD_ID, LOOP, "old"),
        lambda: kanban.service.delete(ACTOR, BOARD_ID, LOOP, "old"),
    ]
    for write in writes:
        with pytest.raises(Conflict, match=message) as refused:
            write()
        assert refused.value.code == "loop_read_only"
        assert refused.value.details == {"loop_id": LOOP}
    assert kanban.state == before
    assert kanban.store.rollbacks == len(writes)


# --- update and move -----------------------------------------------------------------------------


def test_rename_changes_the_name_and_logs_before_and_after(kanban: Board) -> None:
    kanban.state.cards = {"c1": card_row("c1", "todo", LOOP)}

    entry = kanban.service.update(ACTOR, BOARD_ID, LOOP, "todo", ListUpdate(name="Backlog"))

    assert (entry["name"], entry["updated_at"], entry["created_at"]) == ("Backlog", NOW, CREATED)
    # A write answers with the list alone; its cards are not counted (as before).
    assert entry["card_count"] == 0
    renamed = {"before": "To do", "after": "Backlog"}
    assert only_activity(kanban) == ("list.renamed", "todo", renamed)


def test_an_update_without_a_name_returns_the_list_unchanged(kanban: Board) -> None:
    before = kanban.state.snapshot()

    entry = kanban.service.update(ACTOR, BOARD_ID, LOOP, "todo", ListUpdate())

    assert (entry["name"], entry["updated_at"]) == ("To do", CREATED)
    assert kanban.state == before


def test_move_places_the_list_between_its_new_neighbours_and_returns_the_loop(
    kanban: Board,
) -> None:
    entries = kanban.service.move(ACTOR, BOARD_ID, LOOP, "done", ListMove(position=1))

    assert [entry["id"] for entry in entries] == ["todo", "done", "doing"]
    assert kanban.positions()["done"] == 1536
    assert kanban.state.lists["done"].updated_at == NOW
    assert only_activity(kanban) == ("list.moved", "done", {"position": 1})


def test_move_to_the_front_halves_the_first_position_and_past_the_end_appends(
    kanban: Board,
) -> None:
    kanban.service.move(ACTOR, BOARD_ID, LOOP, "done", ListMove(position=0))
    assert kanban.positions()["done"] == 512

    kanban.service.move(ACTOR, BOARD_ID, LOOP, "done", ListMove(position=50))
    assert kanban.positions()["done"] == 3072


def test_move_renumbers_the_other_lists_when_their_gap_is_used_up() -> None:
    world = board(("a", 1), ("b", 2), ("c", 3))

    world.service.move(ACTOR, BOARD_ID, LOOP, "c", ListMove(position=1))

    assert world.positions() == {"a": 1024, "b": 2048, "c": 1536}
    assert [entry["id"] for entry in world.service.list(BOARD_ID, LOOP)] == ["a", "c", "b"]


# --- archive, restore and delete -----------------------------------------------------------------


def test_archive_stamps_an_active_list_and_logs_it(kanban: Board) -> None:
    entry = kanban.service.archive(ACTOR, BOARD_ID, LOOP, "doing")

    assert (entry["archived_at"], entry["updated_at"]) == (NOW, NOW)
    assert only_activity(kanban) == ("list.archived", "doing", {})


def test_archiving_an_archived_list_keeps_its_stamp_but_is_still_logged(kanban: Board) -> None:
    entry = kanban.service.archive(ACTOR, BOARD_ID, LOOP, "old")

    assert (entry["archived_at"], entry["updated_at"]) == (EARLIER, CREATED)
    assert only_activity(kanban) == ("list.archived", "old", {})


def test_restore_puts_an_archived_list_back_at_the_end(kanban: Board) -> None:
    entry = kanban.service.restore(ACTOR, BOARD_ID, LOOP, "old")

    assert (entry["archived_at"], entry["position"], entry["updated_at"]) == (None, 4096, NOW)
    assert only_activity(kanban) == ("list.restored", "old", {})


def test_restoring_an_active_list_leaves_it_where_it_is(kanban: Board) -> None:
    entry = kanban.service.restore(ACTOR, BOARD_ID, LOOP, "doing")

    assert (entry["position"], entry["updated_at"]) == (2048, CREATED)
    assert only_activity(kanban) == ("list.restored", "doing", {})


def test_delete_needs_an_archived_list(kanban: Board) -> None:
    with pytest.raises(Conflict, match="Archive the list before deleting it") as refused:
        kanban.service.delete(ACTOR, BOARD_ID, LOOP, "doing")

    assert refused.value.code == "conflict"
    assert "doing" in kanban.state.lists


def test_delete_refuses_a_list_that_still_has_unarchived_cards(kanban: Board) -> None:
    kanban.state.cards = {"c1": card_row("c1", "old", LOOP)}

    with pytest.raises(ValidationFailure, match="Archive or move the cards") as refused:
        kanban.service.delete(ACTOR, BOARD_ID, LOOP, "old")

    assert refused.value.details == {"active_cards": 1}
    assert ("old" in kanban.state.lists, kanban.store.rollbacks) == (True, 1)


def test_delete_keeps_a_list_whose_archived_cards_came_from_the_plan(kanban: Board) -> None:
    kanban.state.cards = {
        "c1": card_row("c1", "old", LOOP, archived_at=EARLIER, plan_item_id="item-1")
    }

    with pytest.raises(Conflict, match="planned Tickets") as refused:
        kanban.service.delete(ACTOR, BOARD_ID, LOOP, "old")

    assert refused.value.code == "plan_change_required"
    assert refused.value.details == {"planned_cards": 1}


def test_delete_removes_an_archived_list_and_logs_its_name(kanban: Board) -> None:
    kanban.state.cards = {"c1": card_row("c1", "old", LOOP, archived_at=EARLIER)}

    kanban.service.delete(ACTOR, BOARD_ID, LOOP, "old")

    assert "old" not in kanban.state.lists
    assert only_activity(kanban) == ("list.deleted", "old", {"name": "List old"})


def test_the_same_calls_on_the_same_board_give_the_same_results() -> None:
    def run() -> tuple[list[ListEntry], BoardState]:
        world = board(("a", 1024), ("b", 1025))
        world.service.create(ACTOR, BOARD_ID, LOOP, ListCreate(name="New", position=1))
        return world.service.move(ACTOR, BOARD_ID, LOOP, "a", ListMove(position=2)), world.state

    assert run() == run()
