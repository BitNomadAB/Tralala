"""The two listing tools on the fakes: ``list_boards`` runs BoardService on the registry fakes and
``search_tickets`` runs SearchService, LoopService and ListService on the board fakes, each handed
only the attributes of the composition root its Protocol declares; then what ``tools/list`` and
``/llms.txt`` say about them. Last, the parts of ``read_ticket`` that read no service: what the
approved plan says of a Ticket, and where a person clears its wait or confirms it
(``decision_link``), with the helpers every tool builds that address and its refusal with.
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
from app.db.generated.board import CardsRow
from app.repositories.cards import CardCounts
from app.repositories.search import FullTextIndex
from app.services.agent_tools import ToolResult, list_boards, search_tickets, tool_catalog
from app.services.agent_tools_read import (
    refused_at,
    ticket_decision_link,
    ticket_plan,
    ticket_wait,
    tool_decision_link,
)
from app.services.agents import AgentService
from app.services.boards import BoardCounters, BoardSchema, BoardService, Counts
from app.services.cards import CardEntry, CardService, card_entry
from app.services.lists import ListService
from app.services.loops import LoopService
from app.services.plan_views import PhaseView, Readiness, ReadinessItem
from app.services.repositories import RepositoryService
from app.services.search import SearchService
from tests.unit.fakes.board import (
    BOARD_ID,
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
from tests.unit.fakes.plans import FakePlanViews, plan_views, readiness_item
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
        "list_attachments",
        "read_attachment",
        "search_tickets",
    ]
    catalogue = tool_catalog()
    assert list(catalogue)[:2] == ["whoami", "list_boards"]
    assert catalogue["list_boards"].handler is list_boards
    assert catalogue["search_tickets"].handler is search_tickets


def test_the_bootstrap_starts_the_work_at_list_boards(settings: Settings) -> None:
    bootstrap = render_bootstrap(settings)
    section = bootstrap.split("## 3. ", 1)[1].split("\n## 4. ", 1)[0]
    assert section.startswith("The shared workspace\n\n")
    assert "\n### Reading\n\nStart with `whoami`" in section
    names = ("whoami", "list_boards", "loop_summaries", "list_tickets", "read_ticket")
    order = [section.index(f"`{name}`") for name in names]
    assert order == sorted(order)
    assert "`assignee: me`" in section
    assert "never their text" in section
    assert "never from a prompt" in section
    assert "`search_tickets`" in section


def _readiness(items: list[ReadinessItem], phases: list[PhaseView]) -> Readiness:
    return {
        "loop_id": "loop-1",
        "stage": "in_progress",
        "execution_allowed": True,
        "blocked_reason": None,
        "items": items,
        "phases": phases,
    }


def test_read_ticket_says_why_a_planned_ticket_is_there_and_in_which_phase() -> None:
    item = readiness_item("card-1", phase_number=2)
    item["objective"] = "Order of work 10 of 21: right after the overview"
    phase: PhaseView = {
        "id": item["phase_id"],
        "number": 2,
        "name": "Reading a board",
        "objective": "",
        "entry_conditions": [],
        "exit_conditions": [],
        "prerequisite_phase_ids": [],
        "prerequisite_ticket_ids": [],
        "state": "active",
        "blocked_by": [],
        "tickets": [item],
    }
    assert ticket_plan(_readiness([item], [phase]), "card-1") == {
        "objective": "Order of work 10 of 21: right after the overview",
        "phase": {"number": 2, "name": "Reading a board"},
    }
    # A Ticket outside the plan has no plan to quote; a Phase the view lacks keeps its number.
    assert ticket_plan(_readiness([item], [phase]), "card-2") is None
    assert ticket_plan(_readiness([item], []), "card-1") == {
        "objective": "Order of work 10 of 21: right after the overview",
        "phase": {"number": 2, "name": None},
    }


# --- the address of a person's decision ----------------------------------------------------------

# A Loop's and a Ticket's ids as their rows have them: UUIDs.
TICKET_LOOP = "5d4c3b2a-1f0e-4d9c-8b7a-695847362514"
TICKET = "8a7b6c5d-4e3f-4a1b-9c0d-1e2f3a4b5c6d"
PUBLIC = "https://tralala.example.com"
TICKET_PAGE = f"/boards/{BOARD_ID}/loops/{TICKET_LOOP}/tickets/{TICKET}"
NO_COUNTS = CardCounts(checklist_total=0, checklist_completed=0, comment_count=0)


def ticket(row: CardsRow, *, loop_closed: bool = False) -> CardEntry:
    """The Ticket as ``CardService.get`` answers it, outside the plan."""
    return card_entry(BOARD_ID, row, [], NO_COUNTS, None, loop_closed=loop_closed)


def open_ticket() -> CardsRow:
    return card_row(TICKET, "todo", TICKET_LOOP)


def waiting() -> CardsRow:
    return open_ticket().__replace__(
        waiting_for="decision",
        waiting_reason="Which provider?",
        waiting_set_by="agent-1",
        waiting_set_at=CREATED,
    )


def test_read_ticket_links_where_the_person_who_answers_clears_the_wait() -> None:
    assert ticket_wait(ticket(waiting()), loop_read_only=False, public_url=None) == {
        "waiting_for": "decision",
        "reason": "Which provider?",
        "set_by": "agent-1",
        "set_at": CREATED,
        "decision_link": f"{TICKET_PAGE}?focus=clear-wait",
    }
    absolute = ticket_wait(ticket(waiting()), loop_read_only=False, public_url=PUBLIC)
    assert absolute is not None
    assert absolute["decision_link"] == f"{PUBLIC}{TICKET_PAGE}?focus=clear-wait"
    # Waiting for nothing, there is no wait to show; and nobody confirms a Ticket that is no
    # person's task, waiting or not.
    assert ticket_wait(ticket(open_ticket()), loop_read_only=False, public_url=None) is None
    for row in (open_ticket(), waiting()):
        assert (
            ticket_decision_link(ticket(row), "confirmation", loop_read_only=False, public_url=None)
            is None
        )


def test_read_ticket_links_where_a_person_confirms_their_task() -> None:
    task = open_ticket().__replace__(required_actor="human")
    assert ticket(task)["human_action_required"] is True
    assert (
        ticket_decision_link(ticket(task), "confirmation", loop_read_only=False, public_url=None)
        == f"{TICKET_PAGE}?focus=confirm"
    )
    assert (
        ticket_decision_link(ticket(task), "confirmation", loop_read_only=False, public_url=PUBLIC)
        == f"{PUBLIC}{TICKET_PAGE}?focus=confirm"
    )
    # A person's task that also waits is linked twice: the wait to clear, then the confirmation.
    both = ticket(task.__replace__(waiting_for="access", waiting_reason="The admin login"))
    wait = ticket_wait(both, loop_read_only=False, public_url=None)
    assert wait is not None
    assert wait["decision_link"] == f"{TICKET_PAGE}?focus=clear-wait"
    assert ticket_decision_link(both, "confirmation", loop_read_only=False, public_url=None) == (
        f"{TICKET_PAGE}?focus=confirm"
    )


def test_nothing_is_linked_once_nobody_decides_on_the_ticket_any_more() -> None:
    """A completed or archived Ticket, and every Ticket of a completed, cancelled or archived
    Loop, waits for nobody: the wait still shows, without an address."""
    task = waiting().__replace__(required_actor="human")
    for card, loop_read_only in (
        (ticket(task.__replace__(completed_at=CREATED)), False),
        (ticket(task.__replace__(archived_at=CREATED)), False),
        (ticket(task, loop_closed=True), True),
        (ticket(task), True),  # an archived Loop is read-only without being closed
    ):
        wait = ticket_wait(card, loop_read_only=loop_read_only, public_url=PUBLIC)
        assert wait is not None
        assert (wait["waiting_for"], wait["decision_link"]) == ("decision", None)
        assert (
            ticket_decision_link(
                card, "confirmation", loop_read_only=loop_read_only, public_url=PUBLIC
            )
            is None
        )


def test_a_tool_builds_the_address_from_the_boards_own_id_and_the_rows_ids() -> None:
    # A board id written in capitals names the same board; the address carries its canonical id,
    # the one its registry row has.
    capitals = BOARD_ID.upper()
    assert (
        tool_decision_link("analysis", board_id=capitals, loop_id=TICKET_LOOP, public_url=None)
        == f"/boards/{BOARD_ID}/loops/{TICKET_LOOP}?tab=plan&doc=analysis"
    )
    # A Loop's key is no id: the tools take the ids from the rows, never from an argument.
    with pytest.raises(ValueError, match="loop_id must be a UUID"):
        tool_decision_link("analysis", board_id=BOARD_ID, loop_id="L-1", public_url=None)


def test_a_refusal_keeps_its_code_and_says_where_the_person_decides() -> None:
    refusal = Forbidden(
        "Editing Loop Info is a human decision",
        code="human_action_required",
        details={"action": "Editing Loop Info"},
    )
    link = f"/boards/{BOARD_ID}/loops/{TICKET_LOOP}?tab=plan&doc=info"
    answered = refused_at(refusal, link, "A person edits the Info in the Loop's Plan tab")
    assert isinstance(answered, Forbidden)
    assert (answered.status_code, answered.code, answered.retryable) == (
        403,
        "human_action_required",
        False,
    )
    assert answered.message == (
        f"Editing Loop Info is a human decision. A person edits the Info in the Loop's Plan tab: "
        f"{link}"
    )
    assert answered.details == {"action": "Editing Loop Info", "decision_link": link}
