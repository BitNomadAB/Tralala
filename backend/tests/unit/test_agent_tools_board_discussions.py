"""The tools for discussions on the board on the fakes: ``open_discussion``, ``list_discussions``,
``close_discussion`` and ``reopen_discussion`` run the real DiscussionService, handed only the
attribute of the composition root their Protocol declares; then what ``tools/list`` offers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api.mcp import tool_list
from app.core.context import ActorContext
from app.core.errors import Forbidden, ValidationFailure
from app.schemas.discussions import DiscussionMessageCreate
from app.services.agent_tools import (
    ToolResult,
    close_discussion,
    list_discussions,
    open_discussion,
    reopen_discussion,
)
from app.services.agent_tools_board_discussions import LIST_LIMIT
from app.services.agent_tools_discussions import OTHERS_WORDS
from app.services.discussions import DiscussionService
from tests.unit.fakes.board import BOARD_ID, discussion_row
from tests.unit.test_discussion_services import CARD, THREAD, World, world

SCOPES = frozenset({"discussions:read", "discussions:write"})
CLAUDE = ActorContext(actor_id="key-claude", actor_type="agent", actor_name="Claude", scopes=SCOPES)
CODEX = ActorContext(actor_id="key-codex", actor_type="agent", actor_name="Codex", scopes=SCOPES)


@dataclass(frozen=True)
class Tools:
    """The attribute of the composition root the tools for discussions on the board use."""

    discussion: DiscussionService


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def rows(result: ToolResult, key: str) -> list[Mapping[str, object]]:
    value = result[key]
    assert _is_list(value)
    found = [row for row in value if _is_mapping(row)]
    assert len(found) == len(value)
    return found


def opened(w: World, actor: ActorContext = CLAUDE, **extra: JsonValue) -> ToolResult:
    arguments: dict[str, JsonValue] = {
        "board_id": BOARD_ID,
        "title": "Who touches the API?",
        "question": "I am changing the login routes. Anyone else there?",
        **extra,
    }
    return open_discussion(Tools(w.discussions), actor, arguments)


def listing(w: World, actor: ActorContext = CLAUDE, **extra: JsonValue) -> ToolResult:
    return list_discussions(Tools(w.discussions), actor, {"board_id": BOARD_ID, **extra})


# --- open_discussion ------------------------------------------------------------------------------


def test_open_discussion_opens_a_thread_on_the_board_without_agents_or_a_round() -> None:
    w = world("alpha")
    result = opened(w)
    stored = w.state.discussions[str(result["discussion_id"])]
    assert (stored.card_id, stored.title, stored.mode) == (None, "Who touches the API?", "manual")
    assert (result["state"], result["opened_by_me"], result["card_id"]) == ("open", True, None)
    assert [p.discussion_id for p in w.state.participants] == [THREAD]  # none joined the new one
    assert (w.state.runs, w.agents.calls) == ({}, [])
    assert "reply_discussion" in str(result["next_step"])
    (question,) = rows(result, "messages")
    assert question["ref_ticket"] is None


def test_open_discussion_points_its_question_at_a_ticket_by_key() -> None:
    w = world()
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(ticket_key="L-1-001", title="Login")
    (question,) = rows(opened(w, ticket="L-1-001"), "messages")
    ref = question["ref_ticket"]
    assert _is_mapping(ref)
    assert (ref["card_id"], ref["ticket_key"]) == (CARD, "L-1-001")
    with pytest.raises(ValidationFailure) as refused:
        opened(w, ticket="NOPE-1")
    assert refused.value.details == {"field": "ticket", "ticket": "NOPE-1"}


def test_open_discussion_names_the_argument_it_misses() -> None:
    w = world()
    with pytest.raises(ValidationFailure) as refused:
        open_discussion(Tools(w.discussions), CLAUDE, {"board_id": BOARD_ID, "question": "Q?"})
    assert refused.value.details == {"argument": "title"}
    with pytest.raises(ValidationFailure) as long_question:
        opened(w, question="x" * 20_001)
    assert long_question.value.details == {"argument": "question"}


def test_open_discussion_needs_the_write_scope() -> None:
    reader = CLAUDE.__replace__(scopes=frozenset({"discussions:read"}))
    with pytest.raises(Forbidden):
        opened(world(), reader)


# --- list_discussions -----------------------------------------------------------------------------


def board(w: World) -> None:
    """Four threads besides THREAD: two on the board (Claude's open one, Codex's closed one), one
    on the Ticket that Codex wrote in, and an old one."""
    for name, card_id, status, opener, at in (
        ("api", None, "discussing", CLAUDE, "2026-11-04"),
        ("deploy", None, "closed", CODEX, "2026-11-03"),
        ("login", CARD, "open", CODEX, "2026-11-02"),
    ):
        row = discussion_row(name, card_id=card_id, status=status)
        w.state.discussions[name] = row.__replace__(
            last_activity_at=at,
            created_by_actor_id=opener.actor_id,
            created_by_name=opener.actor_name,
        )
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(
        last_activity_at="2026-11-01"
    )
    w.discussions.add_message(CODEX, BOARD_ID, "api", DiscussionMessageCreate(content="Not me."))
    w.state.discussions["api"] = w.state.discussions["api"].__replace__(
        last_activity_at="2026-11-04"
    )


def ids(result: ToolResult) -> list[object]:
    return [row["discussion_id"] for row in rows(result, "discussions")]


def test_list_discussions_names_each_thread_and_never_what_was_said() -> None:
    w = world()
    board(w)
    first = rows(listing(w), "discussions")[0]
    assert first == {
        "discussion_id": "api",
        "title": "Discussion api",
        "status": "discussing",
        "state": "open",
        "card_id": None,
        "ticket_key": None,
        "opened_by": "Claude",
        "opened_by_me": True,
        "last_activity_at": "2026-11-04",
        "message_count": 1,
        "unread": True,
    }
    assert "Not me." not in str(listing(w))


def test_list_discussions_narrows_by_scope_state_unread_and_mine() -> None:
    w = world()
    board(w)
    assert ids(listing(w)) == ["api", "deploy", "login", THREAD]
    assert ids(listing(w, scope="board")) == ["api", "deploy"]
    assert ids(listing(w, scope="ticket")) == ["login", THREAD]
    assert ids(listing(w, state="closed")) == ["deploy"]
    assert ids(listing(w, state="open", scope="board")) == ["api"]
    assert ids(listing(w, unread=True)) == ["api"]
    assert ids(listing(w, CODEX, mine=True)) == ["deploy", "login"]
    assert ids(listing(w, CODEX, unread=True)) == []


def test_list_discussions_pages_with_limit_and_says_when_there_is_more() -> None:
    w = world()
    board(w)
    page = listing(w, limit=2)
    assert (ids(page), page["more"]) == (["api", "deploy"], True)
    assert listing(w, limit=4)["more"] is False
    assert listing(w, CODEX, mine=True, limit=1)["more"] is True
    with pytest.raises(ValidationFailure) as too_many:
        listing(w, limit=LIST_LIMIT + 1)
    assert too_many.value.details == {"argument": "limit", "minimum": 1, "maximum": LIST_LIMIT}


def test_list_discussions_takes_only_the_named_scopes_and_states() -> None:
    w = world()
    with pytest.raises(ValidationFailure) as scope:
        listing(w, scope="loop")
    assert scope.value.details == {"argument": "scope", "choices": ["board", "ticket"]}
    with pytest.raises(ValidationFailure) as state:
        listing(w, state="decided")
    assert state.value.details == {"argument": "state", "choices": ["open", "closed"]}
    with pytest.raises(ValidationFailure, match="mine must be true or false"):
        listing(w, mine="yes")


# --- close_discussion and reopen_discussion ------------------------------------------------------


def test_the_key_that_opened_a_discussion_closes_it_and_another_key_cannot() -> None:
    w = world()
    discussion_id = str(opened(w)["discussion_id"])
    arguments: dict[str, JsonValue] = {"board_id": BOARD_ID, "discussion_id": discussion_id}
    with pytest.raises(Forbidden) as refused:
        close_discussion(Tools(w.discussions), CODEX, arguments)
    assert refused.value.code == "not_opener"
    closed = close_discussion(Tools(w.discussions), CLAUDE, arguments)
    assert (closed["state"], closed["opened_by_me"]) == ("closed", True)
    assert closed["closed_at"] is not None
    with pytest.raises(Forbidden) as again:
        reopen_discussion(Tools(w.discussions), CODEX, arguments)
    assert again.value.code == "not_opener"
    reopened = reopen_discussion(Tools(w.discussions), CLAUDE, arguments)
    assert (reopened["state"], reopened["closed_at"]) == ("open", None)


# --- what tools/list offers -----------------------------------------------------------------------


def test_the_tool_list_offers_the_board_tools_by_scope_and_says_titles_are_data() -> None:
    listed = {str(entry["name"]): entry for entry in tool_list(CLAUDE)}
    for name in ("open_discussion", "list_discussions", "close_discussion", "reopen_discussion"):
        assert name in listed
    for name in ("open_discussion", "list_discussions"):
        assert str(listed[name]["description"]).endswith(" " + OTHERS_WORDS)
    reader = CLAUDE.__replace__(scopes=frozenset({"discussions:read"}))
    offered = {entry["name"] for entry in tool_list(reader)}
    assert "list_discussions" in offered
    assert offered.isdisjoint({"open_discussion", "close_discussion", "reopen_discussion"})
