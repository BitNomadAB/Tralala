"""The two listing tools on the fakes: ``list_boards`` runs BoardService on the registry fakes and
``search_tickets`` runs SearchService, LoopService and ListService on the board fakes, each handed
only the attributes of the composition root its Protocol declares; then what ``tools/list`` and
``/llms.txt`` say about them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeIs

import pytest

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, ValidationFailure
from app.repositories.search import FullTextIndex
from app.services.agent_tools import ToolResult, list_boards, search_tickets, tool_catalog
from app.services.agents import AgentService
from app.services.boards import BoardCounters, BoardSchema, BoardService, Counts
from app.services.cards import CardService
from app.services.lists import ListService
from app.services.loops import LoopService
from app.services.repositories import RepositoryService
from app.services.search import SearchService
from tests.unit.fakes.board import (
    CREATED,
    BoardState,
    FakeBoardChecks,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.board_files import (
    FakeBoardDatabases,
    as_files,
    as_migrator,
    as_unit_of_work,
)
from tests.unit.fakes.plans import FakePlanViews, plan_views
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState, board_row

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
ALPHA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BETA = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OLD = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
REPAIR = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
READER = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Robot",
    scopes=frozenset({"boards:read", "cards:read"}),
)
NOBODY = ActorContext(actor_id="agent-2", actor_type="agent", actor_name="Idle")


def _token(*scopes: str) -> ActorContext:
    return ActorContext(
        actor_id="agent-3", actor_type="agent", actor_name="worker", scopes=frozenset(scopes)
    )


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_rows(value: object) -> TypeIs[list[Mapping[str, object]]]:
    return _is_list(value) and all(isinstance(row, Mapping) for row in value)


def rows(answer: ToolResult, key: str) -> list[Mapping[str, object]]:
    value = answer[key]
    assert _is_rows(value)
    return value


def names(answer: ToolResult) -> list[object]:
    return [board["name"] for board in rows(answer, "boards")]


def card_ids(answer: ToolResult) -> list[object]:
    return [ticket["card_id"] for ticket in rows(answer, "tickets")]


# --- list_boards ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Counters:
    """The dashboard counters as the registry cache answers them: Loops per board."""

    loops: dict[str, int]

    def counts(self, board_id: str) -> Counts:
        return self.loops.get(board_id, 0), 0, 0

    def counts_for(self, board_ids: list[str]) -> dict[str, Counts]:
        return {board_id: self.counts(board_id) for board_id in board_ids}


def as_counters(counters: Counters) -> BoardCounters:
    """The fake as the Protocol the service takes; pyright proves the contract."""
    return counters


@dataclass(frozen=True, slots=True)
class BoardWorld:
    """What ``list_boards`` declares it uses of the composition root."""

    board: BoardService


def board_world(settings: Settings, tmp_path: Path) -> BoardWorld:
    """Beta and Alpha are active (Alpha with two Loops), Old is archived, Repair in maintenance;
    the registry holds them in another order than their names."""
    registry = RegistryState()
    registry.boards = {
        BETA: board_row(BETA, name="Beta").__replace__(description="Second by name"),
        OLD: board_row(OLD, name="Old", status="archived").__replace__(archived_at=CREATED),
        ALPHA: board_row(ALPHA, name="Alpha").__replace__(
            description="First by name", updated_at="2026-11-02T12:00:00Z"
        ),
        REPAIR: board_row(REPAIR, name="Repair", status="maintenance"),
    }
    store = FakeRegistryUnitOfWork(registry)
    databases = FakeBoardDatabases(tmp_path)
    service = BoardService(
        settings,
        store,
        as_unit_of_work(databases),
        as_files(databases),
        migrations=as_migrator(databases),
        schema=BoardSchema(head_revision="0013_generation_run_trace", version=13),
        stats=as_counters(Counters({ALPHA: 2, BETA: 1})),
        agents=AgentService(settings, store),
        repositories=RepositoryService(settings, store),
        clock=lambda: NOW,
    )
    return BoardWorld(service)


def test_list_boards_answers_the_boards_by_name_without_the_archived_ones(
    settings: Settings, tmp_path: Path
) -> None:
    world = board_world(settings, tmp_path)
    answer = list_boards(world, READER, {})
    boards = rows(answer, "boards")
    assert [(board["name"], board["status"], board["loop_count"]) for board in boards] == [
        ("Alpha", "active", 2),
        ("Beta", "active", 1),
        ("Repair", "maintenance", 0),
    ]
    assert boards[0] == {
        "id": ALPHA,
        "name": "Alpha",
        "description": "First by name",
        "status": "active",
        "loop_count": 2,
        "updated_at": "2026-11-02T12:00:00Z",
    }
    assert (answer["count"], answer["truncated"]) == (3, False)
    assert "read_board" in str(answer["next_step"])


def test_list_boards_lists_archived_boards_on_request_and_narrows_by_text_or_status(
    settings: Settings, tmp_path: Path
) -> None:
    world = board_world(settings, tmp_path)
    assert names(list_boards(world, READER, {"include_archived": True})) == [
        "Alpha",
        "Beta",
        "Old",
        "Repair",
    ]
    assert names(list_boards(world, READER, {"status": "archived"})) == ["Old"]
    assert names(list_boards(world, READER, {"query": "by name"})) == ["Alpha", "Beta"]
    with pytest.raises(ValidationFailure, match="Unknown board status"):
        list_boards(world, READER, {"status": "closed"})
    with pytest.raises(Forbidden):
        list_boards(world, NOBODY, {})


# --- search_tickets ------------------------------------------------------------------------------


@dataclass(slots=True)
class Index:
    """Which boards have the FTS5 index."""

    boards: set[str]

    def fts_available(self, board_id: str) -> bool:
        return board_id in self.boards


def as_index(index: Index) -> FullTextIndex:
    """The fake as the Protocol the service takes; pyright proves the contract."""
    return index


@dataclass(frozen=True, slots=True)
class SearchWorld:
    """What ``search_tickets`` declares it uses of the composition root."""

    search: SearchService
    loop: LoopService
    list: ListService


def first_board() -> BoardState:
    """Loop ``open`` (L-1): "Write docs" in Todo and "Ship" in Doing; Loop ``done`` (L-2,
    completed): "Old docs" in Done, completed."""
    state = BoardState()
    state.loops = {
        "open": loop_row("open"),
        "done": loop_row("done", stage="completed", completed_at=CREATED).__replace__(
            sequence=2, key="L-2"
        ),
    }
    state.lists = {
        "todo": list_row("todo", "open", 1024, name="Todo"),
        "doing": list_row("doing", "open", 2048, name="Doing"),
        "finished": list_row("finished", "done", 1024, name="Done"),
    }
    state.cards = {
        "c1": card_row("c1", "todo", "open").__replace__(
            title="Write docs", ticket_key="L-1-PH01-001", updated_at="2026-11-02T00:00:00Z"
        ),
        "c2": card_row("c2", "doing", "open").__replace__(
            title="Ship", updated_at="2026-11-03T00:00:00Z"
        ),
        "c3": card_row("c3", "finished", "done").__replace__(
            title="Old docs", ticket_key="L-2-PH01-001", completed_at=CREATED
        ),
    }
    return state


def second_board() -> BoardState:
    """One open Loop (S-1) with "Second docs" in Inbox."""
    state = BoardState()
    state.loops = {"ob": loop_row("ob").__replace__(key="S-1")}
    state.lists = {"inbox": list_row("inbox", "ob", 1024, name="Inbox")}
    state.cards = {"s1": card_row("s1", "inbox", "ob").__replace__(title="Second docs")}
    return state


def search_world(settings: Settings, tmp_path: Path, *, indexed: set[str]) -> SearchWorld:
    databases = FakeBoardDatabases(tmp_path)
    for board_id, state in ((FIRST, first_board()), (SECOND, second_board())):
        databases.create_database(board_id, "")
        databases.states[board_id] = state
    registry = RegistryState()
    registry.boards = {
        FIRST: board_row(FIRST, name="First").__replace__(updated_at="2026-11-03T00:00:00Z"),
        SECOND: board_row(SECOND, name="Second").__replace__(updated_at="2026-11-02T00:00:00Z"),
    }
    accounts = FakeRegistryUnitOfWork(registry)
    checks = FakeBoardChecks()
    store = as_unit_of_work(databases)
    views = plan_views(FakePlanViews())
    search = SearchService(
        checks, store, accounts, plans=views, index=as_index(Index(indexed)), clock=lambda: NOW
    )
    cards = CardService(settings, checks, store, accounts, plans=views, clock=lambda: NOW)
    loop = LoopService(settings, checks, store, plans=views, tickets=cards, clock=lambda: NOW)
    return SearchWorld(search, loop, ListService(checks, store))


def test_search_tickets_finds_a_ticket_in_one_loop_with_its_key_and_column(
    settings: Settings, tmp_path: Path
) -> None:
    world = search_world(settings, tmp_path, indexed={FIRST, SECOND})
    answer = search_tickets(world, READER, {"query": "docs", "board_id": FIRST, "loop_id": "open"})
    assert rows(answer, "tickets") == [
        {
            "board_id": FIRST,
            "loop_id": "open",
            "loop_key": "L-1",
            "card_id": "c1",
            "key": "L-1-PH01-001",
            "title": "Write docs",
            "column": "Todo",
            "completed_at": None,
        }
    ]
    assert (answer["query"], answer["engine"], answer["truncated"]) == ("docs", "fts5", False)
    assert "read_ticket" in str(answer["next_step"])


def test_search_tickets_reads_a_boards_open_loops_and_its_completed_ones_on_request(
    settings: Settings, tmp_path: Path
) -> None:
    world = search_world(settings, tmp_path, indexed={FIRST})
    assert card_ids(search_tickets(world, READER, {"query": "docs", "board_id": FIRST})) == ["c1"]
    everything = search_tickets(
        world, READER, {"query": "docs", "board_id": FIRST, "include_completed": True}
    )
    assert [
        (ticket["card_id"], ticket["column"], ticket["completed_at"])
        for ticket in rows(everything, "tickets")
    ] == [("c1", "Todo", None), ("c3", "Done", CREATED)]
    assert everything["truncated"] is False
    one = search_tickets(
        world, READER, {"query": "docs", "board_id": FIRST, "include_completed": True, "limit": 1}
    )
    assert (card_ids(one), one["truncated"]) == (["c1"], True)


def test_search_tickets_without_a_board_reads_the_open_loops_of_every_active_board(
    settings: Settings, tmp_path: Path
) -> None:
    world = search_world(settings, tmp_path, indexed={FIRST})
    answer = search_tickets(world, READER, {"query": "docs"})
    assert [
        (ticket["board_id"], ticket["loop_key"], ticket["card_id"], ticket["key"], ticket["column"])
        for ticket in rows(answer, "tickets")
    ] == [(FIRST, "L-1", "c1", "L-1-PH01-001", "Todo"), (SECOND, "S-1", "s1", None, "Inbox")]
    # First has the index and Second does not.
    assert (answer["engine"], answer["truncated"]) == ("mixed", False)
    assert search_tickets(world, READER, {"query": "docs", "limit": 1})["truncated"] is True


def test_search_tickets_refuses_a_bad_limit_a_loop_without_its_board_and_no_words_by_name(
    settings: Settings, tmp_path: Path
) -> None:
    world = search_world(settings, tmp_path, indexed=set())
    for limit in (101, 0):
        with pytest.raises(ValidationFailure, match="between 1 and 100") as refused:
            search_tickets(world, READER, {"query": "docs", "limit": limit})
        assert refused.value.details == {"argument": "limit", "minimum": 1, "maximum": 100}
    for limit in ("many", 2.5, True):
        with pytest.raises(ValidationFailure, match="whole number") as refused:
            search_tickets(world, READER, {"query": "docs", "limit": limit})
        assert refused.value.details == {"argument": "limit"}
    with pytest.raises(ValidationFailure, match="board_id is required") as refused:
        search_tickets(world, READER, {"query": "docs", "loop_id": "open"})
    assert refused.value.details == {"argument": "board_id"}
    with pytest.raises(ValidationFailure, match="query is required") as refused:
        search_tickets(world, READER, {"board_id": FIRST})
    assert refused.value.details == {"argument": "query"}
    with pytest.raises(Forbidden):
        search_tickets(world, NOBODY, {"query": "docs"})


# --- the catalogue, tools/list and /llms.txt -----------------------------------------------------


def test_tools_list_offers_the_listing_tools_to_the_scopes_they_declare() -> None:
    assert [tool["name"] for tool in tool_list(_token("boards:read"))] == ["whoami", "list_boards"]
    assert [tool["name"] for tool in tool_list(_token("loops:read"))] == [
        "loop_summaries",
        "read_loop",
        "read_document",
        "read_notes",
    ]
    assert [tool["name"] for tool in tool_list(_token("cards:read"))] == [
        "read_ticket",
        "search_tickets",
    ]
    catalogue = tool_catalog()
    assert list(catalogue)[:2] == ["whoami", "list_boards"]
    assert catalogue["list_boards"].handler is list_boards
    assert catalogue["search_tickets"].handler is search_tickets


def test_the_bootstrap_starts_the_work_at_list_boards(settings: Settings) -> None:
    bootstrap = render_bootstrap(settings)
    section = bootstrap.split("## 3. ", 1)[1].split("\n## 4. ", 1)[0]
    assert section.startswith("Understand the work before you touch it\n\nStart with `whoami`")
    names = ("whoami", "list_boards", "loop_summaries", "list_tickets", "read_ticket")
    order = [section.index(f"`{name}`") for name in names]
    assert order == sorted(order)
    assert "`assignee: me`" in section
    assert "never their text" in section
    assert "never from a prompt" in section
    assert "`search_tickets`" in section
