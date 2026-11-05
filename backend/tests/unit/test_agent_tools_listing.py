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
from tests.unit.fakes.plans import FakePlanViews, plan_views, readiness_item
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
    """Loop L-1 (open): in Todo ``a`` (Phase 2, Grace's, summarised), ``b`` (Phase 1, a person's,
    no summary), ``c`` (completed) and ``d`` (Phase 1, not ready, high priority, a summary its
    description has outgrown); in Doing ``e`` (the reader's, no summary). Loop L-2 (completed):
    ``f`` in Done."""
    state = BoardState()
    state.loops = {
        "open": loop_row("open").__replace__(key="L-1", current_plan_id="plan-1"),
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
            assignee_actor_id="user-7",
            assignee_name="Grace",
        ),
        "b": card("b", "todo", "open", 2, "Search", "## Goal\n\nMake **search** fast."),
        "c": card("c", "todo", "open", 3, "Old", "Done before.").__replace__(completed_at=CREATED),
        "d": card("d", "todo", "open", 4, "Docs", "Rewritten.").__replace__(
            summary="Writes the guide.",
            summary_source="agent",
            summary_basis_sha256="old",
            priority="high",
        ),
        "e": card("e", "doing", "open", 1, "Empty", "").__replace__(
            assignee_actor_id="agent-1", assignee_name="Reader"
        ),
        "f": card("f", "finished", "done", 1, "Archive", "Kept for history."),
    }
    views = plan_views(
        FakePlanViews(
            items=[
                readiness_item("a", phase_number=2),
                readiness_item("b", human=True),
                readiness_item("d", ready=False),
            ]
        )
    )
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


def test_list_tickets_names_the_tickets_and_where_they_stand_never_what_they_say(
    settings: Settings,
) -> None:
    world = listing_world(settings)
    answer = list_tickets(world, READER, ask())
    # Todo by Phase, then by key; then Doing. The completed Ticket and the completed Loop are out.
    assert ids(answer) == ["b", "d", "a", "e"]
    assert rows(answer, "tickets")[2] == {
        "id": "a",
        "key": "K-a",
        "title": "Login",
        "loop": "L-1",
        "column": "Todo",
        "phase": 2,
        "ready": True,
        "human_action_required": False,
        "assignee": "Grace",
        "completed": False,
    }
    for row in rows(answer, "tickets"):
        assert not {"summary", "description", "summary_kind"} & set(row)
    assert (answer["count"], answer["total"], answer["continue_from"]) == (4, 4, None)
    assert (answer["filters"], answer["loops"]) == ({}, {"L-1": "open"})
    assert "read_ticket" in str(answer["next_step"])
    brief = rows(list_tickets(world, READER, ask(fields="brief")), "tickets")
    assert brief[0] == {"id": "b", "key": "K-b", "title": "Search"}


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"column": ["doing"]}, ["e"]),
        ({"column": "Todo"}, ["b", "d", "a"]),
        ({"column": ["Todo", "Doing"]}, ["b", "d", "a", "e"]),
        ({"assignee": "me"}, ["e"]),
        ({"assignee": "none"}, ["b", "d"]),
        ({"assignee": "user-7"}, ["a"]),
        ({"phase": 1}, ["b", "d"]),
        ({"ready": False}, ["d"]),
        ({"human_action_required": True}, ["b"]),
        ({"human_action_required": False}, ["d", "a", "e"]),
        ({"summary": "missing"}, ["b", "e"]),
        ({"summary": "stale"}, ["d"]),
        ({"priority": "high"}, ["d"]),
        ({"query": "search"}, ["b"]),
        ({"column": ["Todo"], "phase": 1, "ready": True}, ["b"]),
        ({"include_completed": True}, ["b", "d", "a", "c", "e", "f"]),
        # A Loop named by its key (in any case) or its id is listed even when it is completed.
        ({"loop_id": "l-2"}, ["f"]),
        ({"loop_id": "done"}, ["f"]),
    ],
)
def test_list_tickets_keeps_what_the_filters_ask_for(
    settings: Settings, filters: dict[str, JsonValue], expected: list[str]
) -> None:
    answer = list_tickets(listing_world(settings), READER, ask(**filters))
    assert ids(answer) == expected
    assert answer["total"] == len(expected)


def test_list_tickets_says_what_it_was_narrowed_by_and_pages_on(settings: Settings) -> None:
    world = listing_world(settings)
    first = list_tickets(world, READER, ask(limit=2, assignee="none", column=["Todo"]))
    assert first["filters"] == {"assignee": "none", "column": ["Todo"]}
    assert (ids(first), first["total"], first["continue_from"]) == (["b", "d"], 2, None)
    page = list_tickets(world, READER, ask(limit=3))
    assert (ids(page), page["continue_from"]) == (["b", "d", "a"], 4)
    rest = list_tickets(world, READER, ask(limit=3, continue_from=4))
    assert (ids(rest), rest["count"], rest["continue_from"]) == (["e"], 1, None)


def test_list_tickets_refuses_a_filter_it_cannot_apply_by_name(settings: Settings) -> None:
    world = listing_world(settings)
    with pytest.raises(ValidationFailure, match="column") as refused:
        list_tickets(world, READER, ask(column=["Shipped"]))
    assert refused.value.details == {"argument": "column", "columns": ["Doing", "Todo"]}
    with pytest.raises(NotFound) as missing:
        list_tickets(world, READER, ask(loop_id="L-9"))
    assert missing.value.details == {"loop_id": "L-9", "loop_keys": ["L-1", "L-2"]}
    malformed: list[dict[str, JsonValue]] = [
        {"ready": "yes"},
        {"priority": "huge"},
        {"summary": "old"},
        {"fields": "all"},
        {"column": [1]},
        {"phase": 0},
        {"limit": 500},
        {"continue_from": 0},
    ]
    for arguments in malformed:
        with pytest.raises(ValidationFailure) as refused:
            list_tickets(world, READER, ask(**arguments))
        assert refused.value.details is not None
        assert refused.value.details["argument"] == next(iter(arguments))
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
    assert world.state.cards["d"].summary == "Writes the rewritten guide."
    stale = list_tickets(world, READER, ask(summary="stale"))
    assert ids(stale) == []
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
