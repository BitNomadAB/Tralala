"""SearchService on in-memory boards: which engine a search uses (FTS5 when the board has the index,
``LIKE`` when it does not), the filters, the order and paging, what a hit carries (its Loop and its
planned readiness), and the App-wide search over the active boards' open Loops.

The service runs its real code; the repositories, both units of work, the registry checks, the plan
views, the full-text index and the clock are the typed fakes in ``tests/unit/fakes``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import pytest

from app.core.errors import NotFound, ValidationFailure
from app.db.generated.board import (
    CardLabelsRow,
    ChecklistItemsRow,
    ChecklistsRow,
    CommentsRow,
    LabelsRow,
)
from app.repositories.search import FullTextIndex
from app.services.search import SearchService, fts_query, search_engine
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
from tests.unit.fakes.board_files import FakeBoardDatabases
from tests.unit.fakes.plans import BLOCKER, FakePlanViews, readiness_item
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState, board_row

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
LOOP = "loop-a"
PLANNED = "loop-p"


class Filters(TypedDict, total=False):
    q: str
    priority: str
    label: str
    completed: bool
    overdue: bool
    list_id: str
    include_archived: bool


@dataclass(slots=True)
class FakeIndex:
    """Which boards have the FTS5 index; records every question."""

    boards: set[str] = field(default_factory=set[str])
    asked: list[str] = field(default_factory=list[str])

    def fts_available(self, board_id: str) -> bool:
        self.asked.append(board_id)
        return board_id in self.boards


@dataclass(slots=True)
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    checks: FakeBoardChecks
    index: FakeIndex
    views: FakePlanViews
    service: SearchService


def world(*, fts: bool = True) -> World:
    """Loop ``LOOP``: cards by title and update time; ``PLANNED`` has a plan."""
    state = BoardState()
    state.loops = {
        LOOP: loop_row(LOOP),
        PLANNED: loop_row(PLANNED).__replace__(
            current_plan_id="plan-1", key="P-2", name="Planned", sequence=2
        ),
    }
    state.lists = {"todo": list_row("todo", LOOP, 1024), "doing": list_row("doing", LOOP, 2048)}
    rows = [
        card_row("c1", "todo", LOOP).__replace__(
            title="Write docs",
            description="about the bug-tracker",
            priority="high",
            due_at="2026-10-01T00:00:00Z",
            updated_at="2026-11-02T00:00:00Z",
        ),
        card_row("c2", "doing", LOOP).__replace__(
            title="Review 100% of it",
            priority="low",
            due_at="2026-12-01T00:00:00Z",
            updated_at="2026-11-03T00:00:00Z",
        ),
        card_row("c3", "todo", LOOP).__replace__(
            title="Ship", completed_at=CREATED, due_at="2026-10-01T00:00:00Z"
        ),
        card_row("c4", "todo", LOOP, archived_at=CREATED).__replace__(title="Old docs"),
        card_row("c0", "todo", LOOP).__replace__(title="Tie docs"),
        card_row("p1", "todo", PLANNED).__replace__(title="Planned docs"),
        card_row("p2", "todo", PLANNED).__replace__(title="Unplanned docs"),
    ]
    state.cards = {row.id: row for row in rows}
    state.labels = {
        "bug": LabelsRow(id="bug", name="Bug", color="#ff0000"),
        "idea": LabelsRow(id="idea", name="Idea", color="#00ff00"),
    }
    state.card_labels = [
        CardLabelsRow(card_id="c1", label_id="idea"),
        CardLabelsRow(card_id="c1", label_id="bug"),
        CardLabelsRow(card_id="c2", label_id="idea"),
    ]
    state.checklists = {"k": ChecklistsRow(id="k", card_id="c1", title="k", position=1)}
    state.checklist_items = {
        "i": ChecklistItemsRow(id="i", checklist_id="k", text="i", completed=1, position=1),
        "j": ChecklistItemsRow(id="j", checklist_id="k", text="j", completed=0, position=2),
    }
    state.comments = {
        "m": CommentsRow(
            id="m", card_id="c1", actor_id="a", content="", created_at=CREATED, updated_at=CREATED
        )
    }
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    index = FakeIndex({BOARD_ID} if fts else set())
    views = FakePlanViews()
    service = SearchService(
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=views,
        index=as_index(index),
        clock=lambda: NOW,
    )
    return World(state, store, checks, index, views, service)


def as_index(index: FakeIndex) -> FullTextIndex:
    """The fake as the Protocol the service takes; pyright proves the contract."""
    return index


def found(w: World, filters: Filters) -> list[str]:
    page = w.service.board(BOARD_ID, LOOP, **filters)
    return [hit["id"] for hit in page["items"]]


# --- the engine -----------------------------------------------------------------------------------


def test_a_query_is_quoted_and_prefix_matched_token_by_token() -> None:
    assert fts_query("doc bug") == '"doc"* AND "bug"*'
    assert fts_query('  say "hi"  ') == '"say"* AND " hi "*'
    assert fts_query("   ") == ""


def test_a_board_with_the_index_matches_words_by_prefix() -> None:
    w = world()
    page = w.service.board(BOARD_ID, LOOP, q="DOC bug")
    assert [hit["id"] for hit in page["items"]] == ["c1"]
    assert page["engine"] == "fts5"
    assert w.index.asked == [BOARD_ID]


def test_a_board_without_the_index_matches_text_with_like() -> None:
    w = world(fts=False)
    page = w.service.board(BOARD_ID, LOOP, q="100%")
    assert [hit["id"] for hit in page["items"]] == ["c2"]
    assert page["engine"] == "like"
    # LIKE's wildcards stay wildcards, as they always did.
    assert found(w, {"q": "_"}) == ["c2", "c1", "c0", "c3"]
    assert found(w, {"q": "doc bug"}) == []


def test_without_text_the_index_is_not_asked() -> None:
    w = world()
    page = w.service.board(BOARD_ID, LOOP, q="")
    assert page["engine"] == "like"
    assert [hit["id"] for hit in page["items"]] == ["c2", "c1", "c0", "c3"]
    assert w.index.asked == []


@pytest.mark.parametrize("fts", [True, False])
def test_blank_text_is_no_text_filter_on_either_engine(fts: bool) -> None:
    # Was a 500 with the index: the blank text became an empty MATCH, which FTS5 refuses.
    w = world(fts=fts)
    for blank in ("   ", " \t\n "):
        page = w.service.board(BOARD_ID, LOOP, q=blank)
        assert [hit["id"] for hit in page["items"]] == ["c2", "c1", "c0", "c3"]
        assert page["engine"] == "like"
    assert w.index.asked == []
    # Spaces around the words are not part of them, for LIKE as for the index.
    assert found(w, {"q": "  Review  "}) == ["c2"]


# --- the filters, the order and the page ----------------------------------------------------------


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (Filters(priority="high"), ["c1"]),
        (Filters(priority=""), ["c2", "c1", "c0", "c3"]),
        (Filters(label="Idea"), ["c2", "c1"]),
        (Filters(label="bug"), ["c1"]),
        (Filters(label="Bug"), ["c1"]),
        (Filters(label=""), ["c2", "c1", "c0", "c3"]),
        (Filters(completed=True), ["c3"]),
        (Filters(completed=False), ["c2", "c1", "c0"]),
        (Filters(overdue=True), ["c1"]),
        (Filters(list_id="doing"), ["c2"]),
        (Filters(list_id=""), ["c2", "c1", "c0", "c3"]),
        (Filters(include_archived=True), ["c2", "c1", "c0", "c3", "c4"]),
        (Filters(include_archived=True, q="docs"), ["c1", "c0", "c4"]),
        (Filters(label="Idea", q="docs"), ["c1"]),
    ],
)
def test_every_filter_narrows_the_loops_tickets(filters: Filters, expected: list[str]) -> None:
    assert found(world(), filters) == expected
    assert found(world(fts=False), filters) == expected


def test_hits_are_newest_first_then_by_id_one_page_at_a_time() -> None:
    w = world()
    page = w.service.board(BOARD_ID, LOOP, limit=2, offset=1)
    assert [hit["id"] for hit in page["items"]] == ["c1", "c0"]
    assert (page["total"], page["limit"], page["offset"], page["has_more"]) == (4, 2, 1, True)
    page = w.service.board(BOARD_ID, LOOP, limit=2, offset=2)
    assert (len(page["items"]), page["has_more"]) == (2, False)


def test_a_hit_carries_its_card_its_loop_its_labels_and_its_counts() -> None:
    w = world()
    (hit,) = w.service.board(BOARD_ID, LOOP, q="write")["items"]
    assert list(hit)[:8] == [
        "id",
        "list_id",
        "title",
        "description",
        "summary",
        "summary_source",
        "summary_stale",
        "face",
    ]
    assert list(hit)[33:] == [
        "workplace",
        "waiting_for",
        "waiting_reason",
        "waiting_set_at",
        "waiting_set_by",
        "board_id",
        "labels",
        "checklist_total",
        "checklist_completed",
        "comment_count",
        "loop_key",
        "loop_name",
        "ready",
        "human_action_required",
        "blockers",
    ]
    assert (hit["board_id"], hit["loop_id"], hit["loop_key"], hit["loop_name"]) == (
        BOARD_ID,
        LOOP,
        "L-1",
        f"Loop {LOOP}",
    )
    assert hit["labels"] == [
        {"id": "bug", "name": "Bug", "color": "#ff0000"},
        {"id": "idea", "name": "Idea", "color": "#00ff00"},
    ]
    assert (hit["checklist_total"], hit["checklist_completed"], hit["comment_count"]) == (2, 1, 1)
    assert (hit["ready"], hit["human_action_required"], hit["blockers"]) == (True, False, [])
    assert "board_name" not in hit
    assert w.views.calls == []


def test_a_planned_ticket_carries_its_readiness() -> None:
    w = world()
    w.views.items = [
        readiness_item("p1", ready=False, blockers=(BLOCKER,), human=True),
        readiness_item(None),
    ]
    hits = {hit["id"]: hit for hit in w.service.board(BOARD_ID, PLANNED)["items"]}
    assert (hits["p1"]["ready"], hits["p1"]["human_action_required"]) == (False, True)
    assert hits["p1"]["blockers"] == [BLOCKER]
    assert (hits["p2"]["ready"], hits["p2"]["human_action_required"]) == (True, False)
    assert hits["p2"]["blockers"] == []
    assert w.views.calls == [("readiness", PLANNED, "implementation")]


def test_the_board_the_database_and_the_loop_must_exist() -> None:
    w = world()
    w.checks.unregistered = frozenset({BOARD_ID})
    with pytest.raises(NotFound, match="Board not found"):
        w.service.board(BOARD_ID, LOOP)
    w = world()
    w.store.databases = set()
    with pytest.raises(NotFound, match="Board database not found"):
        w.service.board(BOARD_ID, LOOP, q="docs")
    assert w.index.asked == []
    with pytest.raises(NotFound) as raised:
        world().service.board(BOARD_ID, "nope")
    assert raised.value.code == "loop_not_found"


# --- the App-wide search --------------------------------------------------------------------------

FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
THIRD = "33333333-3333-4333-8333-333333333333"
GONE = "44444444-4444-4444-8444-444444444444"
SHELVED = "55555555-5555-4555-8555-555555555555"


def board_state(*loops: tuple[str, str | None, str | None]) -> BoardState:
    """A board whose Loops are ``(id, completed_at, archived_at)``, each with one "docs" card."""
    state = BoardState()
    for number, (loop_id, completed_at, archived_at) in enumerate(loops, 1):
        state.loops[loop_id] = loop_row(
            loop_id, completed_at=completed_at, archived_at=archived_at
        ).__replace__(sequence=number, key=f"L-{number}")
        state.cards[f"{loop_id}-card"] = card_row(f"{loop_id}-card", "todo", loop_id).__replace__(
            title=f"docs of {loop_id}"
        )
    return state


def test_the_app_wide_search_reads_the_open_loops_of_the_newest_active_boards(
    tmp_path: Path,
) -> None:
    databases = FakeBoardDatabases(tmp_path)
    for board_id in (FIRST, SECOND, THIRD, SHELVED):
        databases.create_database(board_id, "")
    databases.states[FIRST] = board_state(("b", None, None), ("a", None, None))
    databases.states[FIRST].cards["b-2"] = card_row("b-2", "todo", "b").__replace__(title="docs")
    databases.states[SECOND] = board_state(
        ("open", None, None), ("done", CREATED, None), ("shelf", None, CREATED)
    )
    databases.states[THIRD] = board_state(("third", None, None))
    registry = RegistryState()
    registry.boards = {
        SECOND: board_row(SECOND, name="Second").__replace__(updated_at="2026-11-02T00:00:00Z"),
        GONE: board_row(GONE, name="Gone").__replace__(updated_at="2026-11-04T00:00:00Z"),
        FIRST: board_row(FIRST, name="First").__replace__(updated_at="2026-11-03T00:00:00Z"),
        THIRD: board_row(THIRD, name="Third").__replace__(updated_at="2026-11-01T00:00:00Z"),
        SHELVED: board_row(SHELVED, status="archived"),
    }
    index = FakeIndex({FIRST})
    service = SearchService(
        FakeBoardChecks(),
        databases,
        FakeRegistryUnitOfWork(registry),
        plans=FakePlanViews(),
        index=as_index(index),
        clock=lambda: NOW,
    )
    result = service.global_search(q="docs", max_boards=3)
    assert [(hit.get("board_name"), hit["loop_id"]) for hit in result["items"]] == [
        ("First", "b"),
        ("First", "b"),
        ("First", "a"),
        ("Second", "open"),
    ]
    assert (result["board_count"], result["loop_count"], result["query"]) == (3, 3, "docs")
    # First has the index and Second does not, so the answer came from both engines.
    assert result["engine"] == "mixed"
    assert index.asked == [FIRST, FIRST, SECOND]
    everything = service.global_search(q="docs", max_boards=25)
    assert [hit["loop_id"] for hit in everything["items"]][-1] == "third"
    assert (everything["board_count"], everything["loop_count"]) == (4, 4)
    assert len(everything["items"]) == 5
    assert everything["engine"] == "mixed"


def test_the_engine_of_several_searches_is_one_word() -> None:
    assert search_engine([]) == "like"
    assert search_engine(["like", "like"]) == "like"
    assert search_engine(["fts5", "fts5"]) == "fts5"
    assert search_engine(["fts5", "like"]) == "mixed"


def test_the_app_wide_search_refuses_blank_text_before_it_reads_a_board(tmp_path: Path) -> None:
    databases = FakeBoardDatabases(tmp_path)
    databases.create_database(FIRST, "")
    databases.states[FIRST] = board_state(("a", None, None))
    registry = RegistryState()
    registry.boards = {FIRST: board_row(FIRST, name="First")}
    index = FakeIndex({FIRST})
    service = SearchService(
        FakeBoardChecks(),
        databases,
        FakeRegistryUnitOfWork(registry),
        plans=FakePlanViews(),
        index=as_index(index),
    )
    for blank in ("", "   ", "\t\n"):
        with pytest.raises(ValidationFailure, match="Search text must not be blank") as raised:
            service.global_search(q=blank)
        assert (raised.value.status_code, raised.value.code) == (422, "validation_failed")
    assert index.asked == []
    assert [hit["id"] for hit in service.global_search(q=" docs ")["items"]] == ["a-card"]


def test_the_app_wide_search_takes_at_most_its_limit_from_each_loop(tmp_path: Path) -> None:
    databases = FakeBoardDatabases(tmp_path)
    databases.create_database(FIRST, "")
    state = board_state(("a", None, None))
    state.cards["a-2"] = card_row("a-2", "todo", "a").__replace__(title="more docs")
    databases.states[FIRST] = state
    registry = RegistryState()
    registry.boards = {FIRST: board_row(FIRST, name="First")}
    service = SearchService(
        FakeBoardChecks(),
        databases,
        FakeRegistryUnitOfWork(registry),
        plans=FakePlanViews(),
        index=as_index(FakeIndex()),
    )
    result = service.global_search(q="docs", limit_per_loop=1)
    assert [hit["id"] for hit in result["items"]] == ["a-2"]
    assert result["items"][0]["board_id"] == FIRST
    assert result["engine"] == "like"
