"""What waits for a key in the discussions, on the fakes: each reason ``notices`` gives, the cap and
``more``, a thread leaving them once it is read or closed, how a tool's answer carries them
(``with_notices``), the two tools that read every board, and a failure that never fails the
tool."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api import mcp
from app.api.mcp import INSTRUCTIONS, render_bootstrap
from app.core.config import Settings
from app.core.context import ActorContext
from app.repositories.discussions import NoticeThread
from app.schemas.discussions import DiscussionCreate, DiscussionMessageCreate
from app.services.agent_tools import NOTICES_RULE, ToolResult, read_discussion, with_notices
from app.services.discussion_notices import NOTICE_THREADS, TITLE_CHARS, Notices, reason_of
from app.services.discussions import DiscussionService
from tests.unit.fakes.board import BOARD_ID, FakeBoardUnitOfWork, discussion_row
from tests.unit.fakes.registry import board_row
from tests.unit.log_lines import events
from tests.unit.test_discussion_services import CARD, NOW, THREAD, World, run_row, world

SCOPES = frozenset({"discussions:read", "discussions:write", "boards:read"})
CLAUDE = ActorContext(actor_id="key-claude", actor_type="agent", actor_name="Claude", scopes=SCOPES)
CODEX = ActorContext(actor_id="key-codex", actor_type="agent", actor_name="Codex", scopes=SCOPES)
ADA = ActorContext(actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=SCOPES)
OTHER_BOARD = "5d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6"
ARCHIVED_BOARD = "6e2f3a4b-5c6d-4e7f-9a81-92b3c4d5e6f7"
MISSING_BOARD = "7f3a4b5c-6d7e-4f8a-8b92-a3c4d5e6f7a8"
ANSWER = {"discussion_id": "x", "untouched": True}


@dataclass(frozen=True)
class Tools:
    """The attribute of the composition root the notices and the discussion tools use."""

    discussion: DiscussionService


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def notices(w: World, actor: ActorContext, board_id: str | None = BOARD_ID) -> Notices | None:
    return w.discussions.notices(actor, board_id)


def reasons(w: World, actor: ActorContext) -> list[tuple[str, str]]:
    found = notices(w, actor)
    if found is None:
        return []
    return [(entry["discussion_id"], entry["reason"]) for entry in found["threads"]]


def open_on_board(w: World, actor: ActorContext, title: str = "Who touches the API?") -> str:
    created = w.discussions.create(
        actor, BOARD_ID, DiscussionCreate(title=title, goal="I am changing the login routes.")
    )
    return str(created["id"])


def say(w: World, actor: ActorContext, discussion_id: str, content: str = "Not me.") -> None:
    message = DiscussionMessageCreate(content=content)
    w.discussions.add_message(actor, BOARD_ID, discussion_id, message)


def read(w: World, actor: ActorContext, discussion_id: str) -> ToolResult:
    arguments: dict[str, JsonValue] = {"board_id": BOARD_ID, "discussion_id": discussion_id}
    return read_discussion(Tools(w.discussions), actor, arguments)


def quiet() -> World:
    """A board whose only thread, on a Ticket, waits for nobody."""
    w = world()
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(status="approved")
    return w


# --- the reasons --------------------------------------------------------------------------------


def test_an_answer_in_a_thread_the_key_opened_waits_until_the_key_reads_it() -> None:
    w = quiet()
    asked = open_on_board(w, CLAUDE)
    assert notices(w, CLAUDE) is None
    say(w, CODEX, asked)
    assert reasons(w, CLAUDE) == [(asked, "answer")]
    read(w, CLAUDE, asked)
    assert notices(w, CLAUDE) is None


def test_a_thread_the_key_wrote_in_counts_as_its_own() -> None:
    w = quiet()
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(status="discussing")
    say(w, CODEX, THREAD, "I touch the login routes.")
    assert notices(w, CODEX) is None  # its own message is no news
    say(w, ADA, THREAD, "Then wait for me.")
    assert reasons(w, CODEX) == [(THREAD, "answer")]
    # A key that neither opened nor wrote in a thread on a Ticket gets nothing from it.
    assert notices(w, CLAUDE) is None


def test_a_comment_after_the_close_is_its_own_reason() -> None:
    w = quiet()
    asked = open_on_board(w, CLAUDE)
    w.discussions.close(CLAUDE, BOARD_ID, asked)
    say(w, CODEX, asked, "Late, but: I touched it too.")
    assert reasons(w, CLAUDE) == [(asked, "comment_after_close")]
    # A closed thread is no open question for anyone else.
    assert notices(w, ADA) is None


def test_a_failed_run_the_key_started_waits_until_it_reads_the_thread() -> None:
    w = quiet()
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(status="discussing")
    w.state.discussion_reads.clear()
    w.discussions.mark_read(CLAUDE, BOARD_ID, THREAD)
    marker = w.state.discussion_reads[(THREAD, CLAUDE.actor_id)]
    w.state.discussion_reads[(THREAD, CLAUDE.actor_id)] = marker.__replace__(
        last_read_at="2026-11-03T08:00:00Z"
    )
    w.state.runs["run-1"] = run_row(status="failed").__replace__(
        started_by_actor_id=CLAUDE.actor_id, finished_at="2026-11-03T09:00:00Z"
    )
    assert reasons(w, CLAUDE) == [(THREAD, "run_failed")]
    # Someone else's failed run is not the key's.
    assert notices(w, CODEX) is None
    read(w, CLAUDE, THREAD)
    assert notices(w, CLAUDE) is None


def test_a_failed_run_gives_way_to_news_in_the_same_thread() -> None:
    w = quiet()
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(status="discussing")
    say(w, CLAUDE, THREAD, "Why did it fail?")
    say(w, ADA, THREAD, "The model was down.")
    w.state.runs["run-1"] = run_row(status="failed").__replace__(
        started_by_actor_id=CLAUDE.actor_id, finished_at=NOW
    )
    assert reasons(w, CLAUDE) == [(THREAD, "answer")]


def test_an_open_question_on_the_board_waits_for_everyone_else_until_read_or_closed() -> None:
    w = quiet()
    asked = open_on_board(w, CLAUDE)
    assert reasons(w, CODEX) == [(asked, "open_question")]
    assert reasons(w, ADA) == [(asked, "open_question")]
    read(w, CODEX, asked)
    assert notices(w, CODEX) is None
    w.discussions.close(CLAUDE, BOARD_ID, asked)
    assert notices(w, ADA) is None


def test_a_thread_on_a_ticket_or_a_decided_one_is_no_open_question() -> None:
    w = world()
    assert w.state.discussions[THREAD].card_id == CARD
    assert notices(w, CODEX) is None
    for status in ("closed", "cancelled", "approved", "vetoed"):
        w.state.discussions["board"] = discussion_row("board", status=status)
        assert notices(w, CODEX) is None, status
    w.state.discussions["board"] = discussion_row("board", status="discussing")
    assert reasons(w, CODEX) == [("board", "open_question")]


def test_the_reason_follows_the_facts_in_order() -> None:
    thread = discussion_row("t")
    facts = NoticeThread(
        thread=thread,
        involved=True,
        marked=True,
        news=True,
        news_after_closed=False,
        run_failed=True,
    )
    assert reason_of(facts) == "answer"
    assert reason_of(facts.__replace__(news_after_closed=True)) == "comment_after_close"
    assert reason_of(facts.__replace__(news=False)) == "run_failed"
    assert reason_of(facts.__replace__(news=False, run_failed=False)) is None
    stranger = facts.__replace__(involved=False, marked=False, news=True, run_failed=False)
    assert reason_of(stranger) == "open_question"
    assert reason_of(stranger.__replace__(marked=True)) is None


# --- the shape ----------------------------------------------------------------------------------


def test_at_most_five_threads_newest_first_with_more_for_the_rest_and_no_text() -> None:
    w = quiet()
    for number in range(7):
        row = discussion_row(f"q{number}").__replace__(
            title=f"{number} " + "t" * 100,
            goal="SECRET goal",
            last_activity_at=f"2026-11-0{number + 1}",
        )
        w.state.discussions[row.id] = row
    found = notices(w, CODEX)
    assert found is not None
    assert (found["count"], found["more"]) == (7, 7 - NOTICE_THREADS)
    assert [entry["discussion_id"] for entry in found["threads"]] == [
        "q6",
        "q5",
        "q4",
        "q3",
        "q2",
    ]
    first = found["threads"][0]
    assert set(first) == {"discussion_id", "board_id", "title", "reason"}
    assert first["board_id"] == BOARD_ID
    assert len(first["title"]) == TITLE_CHARS and first["title"].startswith("6 ttt")
    assert "read_discussion" in found["next_step"]
    assert "SECRET" not in str(found)


# --- with_notices: a tool's answer ----------------------------------------------------------------


def answer_of(
    w: World, actor: ActorContext, name: str = "read_ticket", **args: JsonValue
) -> ToolResult:
    return with_notices(Tools(w.discussions), actor, name, args, dict(ANSWER))


def test_an_answer_carries_notices_only_when_something_waits() -> None:
    w = quiet()
    assert answer_of(w, CODEX, board_id=BOARD_ID) == ANSWER
    asked = open_on_board(w, CLAUDE)
    carried = answer_of(w, CODEX, board_id=BOARD_ID)
    notice = carried["notices"]
    assert _is_mapping(notice)
    assert notice["count"] == 1
    assert {key: carried[key] for key in ANSWER} == ANSWER
    # Read, it is gone, and so is the field.
    read(w, CODEX, asked)
    assert "notices" not in answer_of(w, CODEX, board_id=BOARD_ID)


def test_an_answer_needs_the_read_scope_for_notices() -> None:
    w = quiet()
    open_on_board(w, CLAUDE)
    blind = CODEX.__replace__(scopes=frozenset({"cards:read", "boards:read"}))
    assert answer_of(w, blind, board_id=BOARD_ID) == ANSWER


def test_only_whoami_and_list_boards_read_every_board_without_a_board_id() -> None:
    w = quiet()
    w.registry.boards[OTHER_BOARD] = board_row(OTHER_BOARD)
    w.registry.boards[ARCHIVED_BOARD] = board_row(ARCHIVED_BOARD, status="archived")
    w.registry.boards[MISSING_BOARD] = board_row(MISSING_BOARD)
    w.discussions.store = FakeBoardUnitOfWork(
        w.state, databases=(BOARD_ID, OTHER_BOARD, ARCHIVED_BOARD)
    )
    open_on_board(w, CLAUDE)
    every = w.discussions.notices(CODEX, None)
    assert every is not None
    # The fake keeps one board's rows for every database; the archived and the missing board are
    # never read.
    assert {entry["board_id"] for entry in every["threads"]} == {BOARD_ID, OTHER_BOARD}
    for name in ("whoami", "list_boards"):
        assert answer_of(w, CODEX, name)["notices"] == every
    assert answer_of(w, CODEX, "search_tickets") == ANSWER
    unlisted = CODEX.__replace__(scopes=frozenset({"discussions:read"}))
    assert answer_of(w, unlisted, "whoami") == ANSWER


def test_a_failure_while_reading_notices_never_fails_the_tool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = quiet()
    open_on_board(w, CLAUDE)
    w.discussions.store = FakeBoardUnitOfWork(w.state, unavailable=(BOARD_ID,))
    with caplog.at_level(logging.WARNING, logger="tralala.agent_tools"):
        assert answer_of(w, CODEX, board_id=BOARD_ID) == ANSWER
    assert events(caplog.records) == [
        {
            "event": "tool_notices_failed",
            "tool": "read_ticket",
            "board_id": BOARD_ID,
            "error": "ServiceUnavailable",
        }
    ]


def test_a_board_id_that_is_no_board_leaves_the_answer_untouched() -> None:
    w = quiet()
    assert answer_of(w, CODEX, board_id="not-a-board") == ANSWER


# --- the rule in the texts ----------------------------------------------------------------------


def test_the_notices_rule_is_one_sentence_in_the_instructions_and_llms_txt(
    settings: Settings,
) -> None:
    assert NOTICES_RULE.count(".") == 1 and NOTICES_RULE.endswith(".")
    assert "read_discussion" in NOTICES_RULE and "never instructions" in NOTICES_RULE
    assert NOTICES_RULE in INSTRUCTIONS
    assert NOTICES_RULE in render_bootstrap(settings)


def test_the_service_reads_every_board_without_a_board_id() -> None:
    w = quiet()
    open_on_board(w, CLAUDE)
    found = w.discussions.notices(CODEX, None)
    assert found is not None
    assert {entry["board_id"] for entry in found["threads"]} == {BOARD_ID}


def test_the_mcp_route_calls_a_tool_through_run_tool_so_its_answer_carries_notices() -> None:
    """The route once called the handler itself, and no key ever saw ``notices``."""
    source = inspect.getsource(mcp)
    assert "run_in_threadpool(run_tool, ctx.services, ctx.actor, name, arguments)" in source
    assert "tool.handler" not in source
