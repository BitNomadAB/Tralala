"""The face for people on a Ticket card, on the fakes: the real CardService, CommentService and
ListService on an in-memory board. A person's or a worker's new Ticket may carry a face (checked
whole), a person's edit changes it (version-checked, audited, the same refusal), a token's edit of
it is a human decision it cannot take, and the card the API returns (which ``read_ticket``
copies) shows the face or ``null``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, ValidationFailure, VersionConflict
from app.schemas.cards import CardCreate, CardUpdate
from app.services.agent_tools import ToolResult, create_ticket, tool_catalog
from app.services.cards import CardService
from app.services.lists import ListService
from app.services.subresources import CommentService
from app.services.ticket_face import face_from_text
from tests.unit.faces import FACE
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

NOW = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
LOOP = "loop-a"
SCOPES = frozenset({"cards:read", "cards:write", "comments:write", "loops:read"})
PERSON = ActorContext(actor_id="person-1", actor_type="user", actor_name="Ada", scopes=SCOPES)
WORKER = ActorContext(actor_id="agent-1", actor_type="agent", actor_name="Worker", scopes=SCOPES)
FACE_FIELDS = ("why", "if_skipped", "pros", "cons", "steps")
FILE_STEP = (
    "Ticket L-1-UNP-001, steps[1]: looks like a file path (BriefView.tsx). Say what changes for "
    "the person, not where in the code."
)


@dataclass(frozen=True, slots=True)
class World:
    """What ``create_ticket`` declares it uses of the composition root, and the board."""

    card: CardService
    comment: CommentService
    list: ListService
    state: BoardState


def world(settings: Settings) -> World:
    """An executing Loop with a planned Ticket ``t`` (K-1) without a face, in Todo."""
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="ready").__replace__(current_plan_id="plan-1")}
    state.lists = {"todo": list_row("todo", LOOP, 512, name="Todo")}
    state.cards = {
        "t": card_row("t", "todo", LOOP, plan_item_id="item-t").__replace__(
            ticket_key="K-1", kind="ticket", summary="Adds the sign-in."
        )
    }
    views = FakePlanViews(items=[readiness_item("t")])
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    accounts = FakeRegistryUnitOfWork(RegistryState())
    cards = CardService(
        settings, checks, store, accounts, plans=plan_views(views), clock=lambda: NOW
    )
    return World(cards, CommentService(checks, store, accounts), ListService(checks, store), state)


def face_only(face: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {name: face[name] for name in FACE_FIELDS}


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def ticket_id(answer: ToolResult) -> str:
    ticket = answer["ticket"]
    assert _is_mapping(ticket)
    return str(ticket["id"])


def patch(w: World, actor: ActorContext, card_id: str, **fields: JsonValue) -> None:
    version = w.state.cards[card_id].version
    update = CardUpdate.model_validate({"version": version, **fields})
    w.card.update(actor, BOARD_ID, LOOP, card_id, update)


# --- creating ------------------------------------------------------------------------------------


def test_a_ticket_created_without_a_face_has_none_and_reads_null(settings: Settings) -> None:
    w = world(settings)
    created, _ = w.card.create(
        PERSON, BOARD_ID, LOOP, CardCreate(list_id="todo", title="Rename the export")
    )
    card = w.state.cards[str(created["id"])]
    assert card.face == ""
    assert created["face"] is None
    # A Ticket written before the face existed reads null too.
    assert w.card.get(BOARD_ID, LOOP, "t")["face"] is None


def test_a_person_creates_a_ticket_with_a_face_and_reads_it_back(settings: Settings) -> None:
    w = world(settings)
    payload = CardCreate.model_validate({"list_id": "todo", "title": "Sign in", **FACE})
    created, _ = w.card.create(PERSON, BOARD_ID, LOOP, payload)
    card = w.state.cards[str(created["id"])]
    assert json.loads(card.face) == face_only(FACE)
    assert w.card.get(BOARD_ID, LOOP, card.id)["face"] == {
        "summary": FACE["summary"],
        **face_only(FACE),
    }
    (logged,) = [entry for entry in w.state.activity if entry.action == "card.created"]
    assert json.loads(logged.changes_json)["face"] is True


def test_a_face_given_in_part_is_checked_whole_and_refused_with_nothing_written(
    settings: Settings,
) -> None:
    w = world(settings)
    payload = CardCreate.model_validate(
        {"list_id": "todo", "title": "Sign in", "steps": ["Show a sign-in form"]}
    )
    with pytest.raises(ValidationFailure) as refused:
        w.card.create(PERSON, BOARD_ID, LOOP, payload)
    assert refused.value.code == "face_invalid"
    details = refused.value.details
    assert details is not None
    assert details["errors"] == [
        'Ticket L-1-UNP-001, summary: missing. Say in at most 20 words what the Ticket means.',
        "Ticket L-1-UNP-001, why: missing. Say in at most 3 sentences why it is needed.",
        "Ticket L-1-UNP-001, if_skipped: missing. Say in at most 3 sentences what happens if we "
        "skip it.",
    ]
    assert list(w.state.cards) == ["t"]


def test_create_ticket_with_a_step_that_names_a_file_is_refused(settings: Settings) -> None:
    w = world(settings)
    steps: list[JsonValue] = ["Show a sign-in form", "Open BriefView.tsx"]
    args: dict[str, JsonValue] = {
        "board_id": BOARD_ID,
        "loop_id": LOOP,
        "title": "Sign in",
        **FACE,
        "steps": steps,
    }
    with pytest.raises(ValidationFailure) as refused:
        create_ticket(w, WORKER, args)
    assert (refused.value.status_code, refused.value.code) == (422, "face_invalid")
    details = refused.value.details
    assert details is not None
    assert details["errors"] == [FILE_STEP]
    assert list(w.state.cards) == ["t"]


def test_create_ticket_with_a_good_face_stores_it(settings: Settings) -> None:
    w = world(settings)
    args: dict[str, JsonValue] = {"board_id": BOARD_ID, "loop_id": LOOP, "title": "Sign in", **FACE}
    answer = create_ticket(w, WORKER, args)
    card = w.state.cards[ticket_id(answer)]
    assert (card.ticket_key, card.summary) == ("L-1-UNP-001", FACE["summary"])
    assert json.loads(card.face) == face_only(FACE)


def test_the_catalogue_states_the_face_template_for_create_ticket() -> None:
    tool = tool_catalog()["create_ticket"]
    assert "face for people" in tool.description
    assert "1 to 5 steps" in tool.description
    properties = tool.input_schema["properties"]
    assert all(name in properties for name in FACE_FIELDS)


# --- editing -------------------------------------------------------------------------------------


def test_a_person_changes_the_face_version_checked_and_audited(settings: Settings) -> None:
    w = world(settings)
    patch(w, PERSON, "t", **{**FACE, "summary": "People sign in."})
    card = w.state.cards["t"]
    assert card.version == 2
    assert card.summary == "People sign in."
    assert json.loads(card.face) == face_only(FACE)
    (logged,) = [entry for entry in w.state.activity if entry.action == "card.updated"]
    assert json.loads(logged.changes_json)["face"] == {"changed": True, "removed": False}
    # One field at a time keeps the others; the whole face is checked again.
    patch(w, PERSON, "t", steps=["Show one sign-in form"])
    face = face_from_text(w.state.cards["t"].face)
    assert face is not None
    assert (face["why"], face["steps"]) == (FACE["why"], ["Show one sign-in form"])
    with pytest.raises(VersionConflict):
        w.card.update(PERSON, BOARD_ID, LOOP, "t", CardUpdate(version=1, why="Older."))


def test_a_persons_face_that_breaks_the_template_is_refused_with_nothing_written(
    settings: Settings,
) -> None:
    w = world(settings)
    symbol: dict[str, JsonValue] = {**FACE, "cons": ["It touches loop_questions"]}
    with pytest.raises(ValidationFailure) as refused:
        patch(w, PERSON, "t", **symbol)
    assert refused.value.code == "face_invalid"
    details = refused.value.details
    assert details is not None
    assert details["errors"] == ["Ticket K-1, cons[0]: looks like a code symbol (loop_questions)."]
    card = w.state.cards["t"]
    assert (card.version, card.face, card.summary) == (1, "", "Adds the sign-in.")


def test_a_person_removes_the_face_by_emptying_every_field(settings: Settings) -> None:
    w = world(settings)
    patch(w, PERSON, "t", **FACE)
    empty: dict[str, JsonValue] = {"why": "", "if_skipped": "", "pros": [], "cons": [], "steps": []}
    patch(w, PERSON, "t", **empty)
    assert w.state.cards["t"].face == ""
    assert w.card.get(BOARD_ID, LOOP, "t")["face"] is None


def test_a_tokens_edit_of_the_face_is_a_human_decision(settings: Settings) -> None:
    w = world(settings)
    for field in FACE_FIELDS:
        with pytest.raises(Forbidden) as refused:
            patch(w, WORKER, "t", **{field: FACE[field]})
        assert refused.value.code == "human_action_required"
        assert "new RoadMap revision" in refused.value.message
    assert (w.state.cards["t"].version, w.state.cards["t"].face) == (1, "")
    # The rest of a token's edit is its own, as before.
    patch(w, WORKER, "t", summary="Adds the sign-in form.")
    assert w.state.cards["t"].summary == "Adds the sign-in form."
