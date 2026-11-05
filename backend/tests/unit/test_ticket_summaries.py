"""A Ticket's summary: the excerpt a list shows without one, the hash that marks it stale, the
schema bound, and CardService writing it on create and update with the source of the actor."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.context import ActorContext
from app.schemas.cards import CardCreate, CardUpdate
from app.services.cards import CardService
from app.services.ticket_summaries import excerpt, summary_basis, summary_source, summary_stale
from tests.unit.fakes.board import (
    BOARD_ID,
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
LOOP = "loop-a"
AGENT = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Worker", scopes=frozenset({"cards:write"})
)
SENTENCE = "A first sentence long enough to end the excerpt. "  # 49 characters
PERSON = ActorContext(
    actor_id="user-1", actor_type="user", actor_name="Ada", scopes=frozenset({"cards:write"})
)


# --- the pure rules ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("", ""),
        ("Make search fast.", "Make search fast."),
        (
            "## Goal\n\n- Make **search** fast, see [the notes](https://example.com).\n- `x` too",
            "Goal Make search fast, see the notes. x too",
        ),
        (SENTENCE * 3, (SENTENCE * 3).strip()),
        (SENTENCE * 5, (SENTENCE * 4).strip()),  # 196 characters: the last whole sentence
        ("Short. " + "word " * 60, "Short. " + ("word " * 38).strip() + "…"),
        ("word " * 60, ("word " * 40).strip() + "…"),
    ],
)
def test_an_excerpt_is_the_plain_start_of_the_description(description: str, expected: str) -> None:
    assert excerpt(description) == expected
    assert len(excerpt(description)) <= 200


def test_a_summary_is_stale_once_the_title_or_description_it_was_written_from_changes() -> None:
    row = card_row("c", "todo", LOOP).__replace__(
        title="Login",
        description="Build it.",
        summary="Adds a login page.",
        summary_basis_sha256=summary_basis("Login", "Build it."),
    )
    assert summary_stale(row) is False
    assert summary_stale(row.__replace__(description="Build it twice.")) is True
    assert summary_stale(row.__replace__(title="Sign-in")) is True
    assert summary_stale(row.__replace__(summary="", description="Changed")) is False
    assert summary_basis("a", "b") != summary_basis("a\nb", "")


def test_the_source_is_the_kind_of_actor() -> None:
    assert (summary_source(PERSON), summary_source(AGENT)) == ("person", "agent")


def test_a_summary_is_one_paragraph_of_at_most_400_characters() -> None:
    spread = CardUpdate(version=1, summary="  Adds\n\na   login  page. ")
    assert spread.summary == "Adds a login page."
    assert CardCreate(list_id="todo", title="T").summary == ""
    CardUpdate(version=1, summary="x" * 400)
    with pytest.raises(ValidationError, match="at most 400 characters"):
        CardUpdate(version=1, summary="x" * 401)


# --- CardService ---------------------------------------------------------------------------------


class Ids:
    """``new`` for the first id (the created card), then id-2, id-3, ... (activity entries)."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return "new" if self.issued == 1 else f"id-{self.issued}"


def world(settings: Settings) -> tuple[CardService, BoardState]:
    """An executing Loop with a planned Ticket ``t`` and a manual one ``m`` in Todo."""
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="ready").__replace__(current_plan_id="plan-1")}
    state.lists = {"todo": list_row("todo", LOOP, 512, name="Todo")}
    state.cards = {
        "t": card_row("t", "todo", LOOP, plan_item_id="t").__replace__(
            title="Planned", description="Approved instructions.", ticket_key="K-1"
        ),
        "m": card_row("m", "todo", LOOP).__replace__(title="Manual", description="Notes."),
    }
    views = plan_views(FakePlanViews(items=[readiness_item("t")]))
    service = CardService(
        settings,
        FakeBoardChecks(),
        FakeBoardUnitOfWork(state),
        FakeRegistryUnitOfWork(RegistryState()),
        plans=views,
        clock=lambda: NOW,
        new_id=Ids(),
    )
    return service, state


def test_creating_a_ticket_stores_its_summary_as_the_actors(settings: Settings) -> None:
    service, state = world(settings)
    payload = CardCreate(list_id="todo", title="Follow-up", description="Do it.", summary="Fix.")
    created, _ = service.create(AGENT, BOARD_ID, LOOP, payload)
    row = state.cards["new"]
    assert (row.summary, row.summary_source) == ("Fix.", "agent")
    assert row.summary_basis_sha256 == summary_basis("Follow-up", "Do it.")
    assert (created["summary"], created["summary_stale"]) == ("Fix.", False)


def test_a_ticket_created_without_a_summary_has_none(settings: Settings) -> None:
    service, state = world(settings)
    service.create(PERSON, BOARD_ID, LOOP, CardCreate(list_id="todo", title="Bare"))
    row = state.cards["new"]
    assert (row.summary, row.summary_source, row.summary_basis_sha256) == ("", "", "")


def test_a_planned_tickets_summary_is_editable_because_it_is_not_the_work_definition(
    settings: Settings,
) -> None:
    service, state = world(settings)
    answer = service.update(
        PERSON, BOARD_ID, LOOP, "t", CardUpdate(version=1, summary="Adds the columns.")
    )
    row = state.cards["t"]
    assert (row.summary, row.summary_source, row.version) == ("Adds the columns.", "person", 2)
    assert row.summary_basis_sha256 == summary_basis("Planned", "Approved instructions.")
    assert (answer["summary_source"], answer["summary_stale"]) == ("person", False)


def test_an_edited_description_makes_the_summary_stale_until_it_is_written_again(
    settings: Settings,
) -> None:
    service, state = world(settings)
    service.update(AGENT, BOARD_ID, LOOP, "m", CardUpdate(version=1, summary="Keeps notes."))
    edited = service.update(AGENT, BOARD_ID, LOOP, "m", CardUpdate(version=2, description="New."))
    assert (edited["summary"], edited["summary_stale"]) == ("Keeps notes.", True)
    confirmed = service.update(
        AGENT, BOARD_ID, LOOP, "m", CardUpdate(version=3, summary="Keeps notes.")
    )
    assert (confirmed["summary_stale"], confirmed["version"]) == (False, 4)
    unchanged = service.update(
        AGENT, BOARD_ID, LOOP, "m", CardUpdate(version=4, summary="Keeps notes.")
    )
    assert unchanged["version"] == 4  # the same summary on an unchanged Ticket writes nothing
    removed = service.update(PERSON, BOARD_ID, LOOP, "m", CardUpdate(version=4, summary=""))
    assert (removed["summary"], removed["summary_source"], removed["version"]) == ("", "", 5)
    assert state.cards["m"].summary_basis_sha256 == ""
