"""``list_tickets`` and ``write_ticket_summaries`` on the fakes: the real CardService, LoopService
and ListService on an in-memory board, handed to the tools as the attributes ``TicketListing`` and
``SummaryWriting`` declare; then what ``tools/list`` and ``/llms.txt`` say about them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, NotFound, ValidationFailure
from app.services.agent_tools import (
    ToolResult,
    list_tickets,
    tool_catalog,
    write_ticket_summaries,
)
from app.services.cards import CardService
from app.services.lists import ListService
from app.services.loops import LoopService
from app.services.ticket_summaries import summary_basis
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
from tests.unit.fakes.plans import FakePlanViews, plan_views
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
READER = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Reader",
    scopes=frozenset({"cards:read", "loops:read"}),
)
WRITER = ActorContext(
    actor_id="agent-2",
    actor_type="agent",
    actor_name="Writer",
    scopes=frozenset({"cards:read", "cards:write", "loops:read"}),
)


@dataclass(frozen=True, slots=True)
class ListingWorld:
    """What both tools declare they use of the composition root, and the board."""

    card: CardService
    loop: LoopService
    list: ListService
    state: BoardState


def listing_world(settings: Settings) -> ListingWorld:
    """Loop L-1 (open): ``a`` summarised, ``b`` with only a Markdown description, ``c`` completed,
    ``d`` with a summary its description has since outgrown, all in Todo, ``e`` in Doing. Loop L-2
    (completed): ``f`` in Done."""
    state = BoardState()
    state.loops = {
        "open": loop_row("open").__replace__(key="L-1"),
        "done": loop_row("done", stage="completed", completed_at=CREATED).__replace__(
            sequence=2, key="L-2"
        ),
    }
    state.lists = {
        "todo": list_row("todo", "open", 1024, name="Todo"),
        "doing": list_row("doing", "open", 2048, name="Doing"),
        "finished": list_row("finished", "done", 1024, name="Done"),
    }

    def card(card_id: str, list_id: str, loop_id: str, position: int, title: str, text: str):
        return card_row(card_id, list_id, loop_id).__replace__(
            title=title, description=text, position=position, ticket_key=f"K-{card_id}"
        )

    state.cards = {
        "a": card("a", "todo", "open", 1, "Login", "Build the page.").__replace__(
            summary="Adds a login page.",
            summary_source="plan",
            summary_basis_sha256=summary_basis("Login", "Build the page."),
            assignee_name="Grace",
        ),
        "b": card("b", "todo", "open", 2, "Search", "## Goal\n\nMake **search** fast."),
        "c": card("c", "todo", "open", 3, "Old", "Done before.").__replace__(
            completed_at=CREATED
        ),
        "d": card("d", "todo", "open", 4, "Docs", "Rewritten.").__replace__(
            summary="Writes the guide.", summary_source="agent", summary_basis_sha256="old"
        ),
        "e": card("e", "doing", "open", 1, "Empty", ""),
        "f": card("f", "finished", "done", 1, "Archive", "Kept for history."),
    }
    views = plan_views(FakePlanViews(items=[]))
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(state)
    cards = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=views,
        clock=lambda: NOW,
    )
    return ListingWorld(
        card=cards,
        loop=LoopService(settings, checks, store, plans=views, tickets=cards, clock=lambda: NOW),
        list=ListService(checks, store),
        state=state,
    )


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_rows(value: object) -> TypeIs[list[Mapping[str, object]]]:
    return _is_list(value) and all(isinstance(row, Mapping) for row in value)


def rows(answer: ToolResult, key: str) -> list[Mapping[str, object]]:
    value = answer[key]
    assert _is_rows(value)
    return value


def ids(answer: ToolResult) -> list[object]:
    return [row.get("id", row.get("card_id")) for row in rows(answer, "tickets")]


def ask(**arguments: JsonValue) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, **arguments}


# --- list_tickets --------------------------------------------------------------------------------


def test_list_tickets_answers_a_short_row_per_open_ticket_of_the_open_loops(
    settings: Settings,
) -> None:
    world = listing_world(settings)
    answer = list_tickets(world, READER, ask())
    assert ids(answer) == ["a", "b", "d", "e"]
    first, search, docs, empty = rows(answer, "tickets")
    assert first == {
        "id": "a",
        "key": "K-a",
        "title": "Login",
        "summary": "Adds a login page.",
        "summary_kind": "written",
        "summary_stale": False,
        "loop_key": "L-1",
        "column": "Todo",
        "phase_number": None,
        "ready": True,
        "human_action_required": False,
        "assignee": "Grace",
        "completed_at": None,
    }
    assert (search["summary"], search["summary_kind"]) == ("Goal Make search fast.", "excerpt")
    assert (docs["summary"], docs["summary_kind"], docs["summary_stale"]) == (
        "Writes the guide.",
        "written",
        True,
    )
    assert (empty["summary"], empty["summary_kind"], empty["column"]) == ("", "none", "Doing")
    assert all("description" not in row for row in rows(answer, "tickets"))
    assert (answer["count"], answer["truncated"]) == (4, False)
    assert (answer["without_summary"], answer["stale_summaries"]) == (2, 1)
    assert "read_ticket" in str(answer["next_step"])
    assert "write_ticket_summaries" in str(answer["next_step"])


def test_list_tickets_narrows_to_a_loop_takes_completed_work_on_request_and_stops_at_the_limit(
    settings: Settings,
) -> None:
    world = listing_world(settings)
    assert ids(list_tickets(world, READER, ask(include_completed=True))) == [
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
    ]
    # A Loop named outright is listed even when it is completed; its open Tickets show.
    assert ids(list_tickets(world, READER, ask(loop_id="done"))) == ["f"]
    assert ids(list_tickets(world, READER, ask(loop_id="open"))) == ["a", "b", "d", "e"]
    assert ids(list_tickets(world, READER, ask(query="search"))) == ["b"]
    limited = list_tickets(world, READER, ask(limit=2))
    assert (ids(limited), limited["truncated"]) == (["a", "b"], True)
    with pytest.raises(NotFound):
        list_tickets(world, READER, ask(loop_id="missing"))
    with pytest.raises(ValidationFailure, match="limit must be between 1 and 200"):
        list_tickets(world, READER, ask(limit=500))
    with pytest.raises(Forbidden):
        list_tickets(world, WRITER.__replace__(scopes=frozenset({"cards:read"})), ask())


# --- write_ticket_summaries ----------------------------------------------------------------------


def test_write_ticket_summaries_writes_each_as_a_versioned_edit_and_reports_each_refusal(
    settings: Settings,
) -> None:
    world = listing_world(settings)
    answer = write_ticket_summaries(
        world,
        WRITER,
        ask(
            summaries=[
                {"card_id": "b", "summary": "Makes  search\nfast."},
                {"card_id": "d", "summary": "Writes the rewritten guide."},
                {"card_id": "missing", "summary": "Nothing."},
                {"card_id": "f", "summary": "Too late."},
                {"card_id": "e", "summary": "x" * 401},
            ]
        ),
    )
    assert (answer["written"], answer["refused"]) == (2, 3)
    results = rows(answer, "results")
    assert results[0] == {"card_id": "b", "key": "K-b", "status": "written", "version": 2}
    assert [result["status"] for result in results] == [
        "written",
        "written",
        "refused",
        "refused",
        "refused",
    ]
    assert [result.get("code") for result in results[2:]] == [
        "not_found",
        "loop_read_only",
        "validation_failed",
    ]
    search = world.state.cards["b"]
    assert (search.summary, search.summary_source, search.version) == (
        "Makes search fast.",
        "agent",
        2,
    )
    listed = {row["id"]: row for row in rows(list_tickets(world, READER, ask()), "tickets")}
    assert (listed["d"]["summary"], listed["d"]["summary_stale"]) == (
        "Writes the rewritten guide.",
        False,
    )
    assert world.state.cards["f"].summary == ""


def test_write_ticket_summaries_refuses_a_malformed_request_as_a_whole(settings: Settings) -> None:
    world = listing_world(settings)
    malformed: list[JsonValue] = [[], [{"card_id": "b"}], [{"summary": "x"}], "b", [1]]
    for summaries in malformed:
        with pytest.raises(ValidationFailure, match="summaries"):
            write_ticket_summaries(world, WRITER, ask(summaries=summaries))
    with pytest.raises(ValidationFailure, match="At most 100"):
        too_many: list[JsonValue] = [{"card_id": "b", "summary": "x"}] * 101
        write_ticket_summaries(world, WRITER, ask(summaries=too_many))
    with pytest.raises(Forbidden):
        write_ticket_summaries(world, READER, ask(summaries=[{"card_id": "b", "summary": "x"}]))
    assert world.state.cards["b"].summary == ""


# --- the catalogue -------------------------------------------------------------------------------


def test_both_tools_are_offered_and_documented_with_their_scopes(settings: Settings) -> None:
    catalogue = tool_catalog()
    assert catalogue["list_tickets"].scopes == ("cards:read", "loops:read")
    assert catalogue["write_ticket_summaries"].scopes == ("cards:write",)
    offered = {tool["name"] for tool in tool_list(READER)}
    assert "list_tickets" in offered
    assert "write_ticket_summaries" not in offered
    text = render_bootstrap(settings)
    assert "### list_tickets (requires `cards:read`, `loops:read`)" in text
    assert "### write_ticket_summaries (requires `cards:write`)" in text
    assert "summary" in str(catalogue["create_ticket"].input_schema["properties"])
