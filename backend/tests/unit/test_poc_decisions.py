"""POC decisions and what is missing from a person: ``PocDecisionService`` on the board fakes with
the real ``CardService``, the request schemas at the boundary, and the counts the Loop summary
reads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.context import DECIDE_SCOPE, ActorContext, EditorDecision
from app.core.errors import Conflict, Forbidden, NotFound
from app.db.generated.board import LoopsRow
from app.repositories.board import BoardRepositories
from app.schemas.loops import LOOP_STAGES
from app.schemas.poc_decisions import PocDecisionAnswerCreate, PocDecisionCreate
from app.services.cards import CardService
from app.services.plan_views import PhaseView, PlanView, Readiness, ReadinessItem
from app.services.poc_decision_rules import PocDecisionRefusal
from app.services.poc_decisions import PocDecisionService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import FakePlanViews, readiness_item
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
STAMP = "2026-11-26T09:00:00Z"
LOOP = "loop-a"
OTHER_LOOP = "loop-b"
CARD = "card-1"
ELSEWHERE = "card-9"
WRITE = frozenset({"cards:read", "cards:write", "loops:read"})
KEY = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Worker",
    scopes=WRITE,
    credential_id="key-1",
)
ADA = ActorContext(actor_id="user-ada", actor_type="user", actor_name="Ada", scopes=WRITE)
# The owner's context for an answer carried by a key with the right to decide in the editor: it
# passes ``require_person_or_editor_decision`` and is still refused here.
EDITOR = ActorContext(
    actor_id="user-ada",
    actor_type="user",
    actor_name="Ada",
    scopes=WRITE | {DECIDE_SCOPE},
    credential_id="key-9",
    editor_decision=EditorDecision(credential_id="key-9", key_name="Editor"),
)
VIEWER = ActorContext(
    actor_id="user-cy", actor_type="user", actor_name="Cy", scopes=frozenset({"cards:read"})
)


def decision(**changes: str) -> PocDecisionCreate:
    fields: dict[str, str] = {
        "title": "Store the list in the browser",
        "chosen": "The list lives in the browser for now.",
        "reason": "It is the quickest way to show the page.",
        "alternative": "Keep it on the server.",
        "change_path": "Move the list to the server later.",
        **changes,
    }
    return PocDecisionCreate.model_validate({"kind": "decision", **fields})


def missing(**changes: str) -> PocDecisionCreate:
    fields: dict[str, str] = {
        "title": "No mail account",
        "missing": "An account for the mail service.",
        "reason": "The invitation mail needs it.",
        "chosen": "Invitations are shown as a link to copy.",
        "change_path": "Send the mail once the account is there.",
        **changes,
    }
    return PocDecisionCreate.model_validate({"kind": "missing", **fields})


class Ids:
    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"id-{self.issued}"


@dataclass(slots=True)
class PhasedPlanViews:
    """Plan views whose readiness holds the items and Phases a test sets."""

    items: list[ReadinessItem]
    phases: list[PhaseView]

    def plan_view(self, repos: BoardRepositories, loop: LoopsRow) -> PlanView:
        return FakePlanViews().plan_view(repos, loop)

    def readiness(self, repos: BoardRepositories, loop: LoopsRow) -> Readiness:
        del repos
        return {
            "loop_id": loop.id,
            "stage": loop.stage,
            "execution_allowed": True,
            "blocked_reason": None,
            "items": list(self.items),
            "phases": list(self.phases),
        }


@dataclass(frozen=True, slots=True)
class PocWorld:
    service: PocDecisionService
    state: BoardState


def poc_world(
    settings: Settings,
    *,
    loop: LoopsRow | None = None,
    items: list[ReadinessItem] | None = None,
    phases: list[PhaseView] | None = None,
) -> PocWorld:
    """Loop WE012 (``LOOP``, no plan, in progress) with a Todo and a Doing column and one Ticket
    added by hand (``CARD``, WE012-UNP-001, in Doing); another Loop holds ``ELSEWHERE``."""
    state = BoardState()
    state.loops = {
        LOOP: loop or loop_row(LOOP, stage="in_progress").__replace__(key="WE012"),
        OTHER_LOOP: loop_row(OTHER_LOOP).__replace__(sequence=2, key="OT002"),
    }
    state.lists = {
        "todo": list_row("todo", LOOP, 512, name="Todo"),
        "doing": list_row("doing", LOOP, 1024, name="Doing"),
        "b": list_row("b", OTHER_LOOP, 512),
    }
    state.cards = {
        CARD: card_row(CARD, "doing", LOOP).__replace__(
            kind="manual", ticket_key="WE012-UNP-001", title="Show the list"
        ),
        ELSEWHERE: card_row(ELSEWHERE, "b", OTHER_LOOP),
    }
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(state)
    views = PhasedPlanViews(items or [], phases or [])
    ids = Ids()
    cards = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=views,
        clock=lambda: NOW,
        new_id=ids,
    )
    service = PocDecisionService(
        checks, store, cards, plans=views, clock=lambda: NOW, new_id=ids
    )
    return PocWorld(service, state)


def actions(world: PocWorld) -> list[str]:
    return [entry.action for entry in world.state.activity]


# --- recording -----------------------------------------------------------------------------------


def test_a_key_records_a_decision_keyed_in_its_loop_and_the_log_says_so(
    settings: Settings,
) -> None:
    world = poc_world(settings)
    recorded = world.service.record(KEY, BOARD_ID, LOOP, decision(card_id=CARD))
    assert recorded == {
        "id": "id-1",
        "key": "WE012-POC-001",
        "loop_id": LOOP,
        "card_id": CARD,
        "ticket_key": "WE012-UNP-001",
        "ticket_title": "Show the list",
        "phase_number": None,
        "phase_complete": None,
        "kind": "decision",
        "title": "Store the list in the browser",
        "chosen": "The list lives in the browser for now.",
        "reason": "It is the quickest way to show the page.",
        "alternative": "Keep it on the server.",
        "change_path": "Move the list to the server later.",
        "missing": "",
        "builds_on": "",
        "built_on": False,
        "details": "",
        "status": "open",
        "feedback": "",
        "feedback_ticket": None,
        "due": False,
        "created_at": STAMP,
        "created_by": {"name": "Worker", "type": "agent"},
        "answered_at": None,
        "answered_by_name": None,
        "deduplicated": False,
    }
    (entry,) = world.state.activity
    assert (entry.action, entry.entity_type, entry.entity_id, entry.actor_id) == (
        "loop.poc_decision_recorded",
        "loop",
        LOOP,
        "agent-1",
    )
    assert json.loads(entry.changes_json) == {
        "decision_id": "id-1",
        "key": "WE012-POC-001",
        "kind": "decision",
        "card_id": CARD,
        "built_on": False,
    }


def test_the_keys_follow_each_other_and_a_record_needs_no_ticket(settings: Settings) -> None:
    world = poc_world(settings)
    first = world.service.record(KEY, BOARD_ID, LOOP, decision())
    second = world.service.record(ADA, BOARD_ID, LOOP, missing(alternative="Ask for one."))
    third = world.service.record(KEY, BOARD_ID, LOOP, decision(title="Another choice"))
    assert [first["key"], second["key"], third["key"]] == [
        "WE012-POC-001",
        "WE012-POC-002",
        "WE012-POC-003",
    ]
    assert (first["card_id"], first["ticket_key"]) == (None, None)
    assert second["created_by"] == {"name": "Ada", "type": "user"}
    assert (second["missing"], second["alternative"]) == (
        "An account for the mail service.",
        "Ask for one.",
    )


def test_the_same_open_record_again_answers_the_first_one(settings: Settings) -> None:
    world = poc_world(settings)
    first = world.service.record(KEY, BOARD_ID, LOOP, decision())
    again = world.service.record(
        KEY, BOARD_ID, LOOP, decision(title="store the list  in the browser")
    )
    assert (again["id"], again["key"], again["deduplicated"]) == (first["id"], first["key"], True)
    assert len(world.state.poc_decisions) == 1
    assert actions(world) == ["loop.poc_decision_recorded"]
    # Once it is answered, the same words are a new record.
    world.service.answer(ADA, BOARD_ID, LOOP, first["id"], PocDecisionAnswerCreate(answer="ok"))
    later = world.service.record(KEY, BOARD_ID, LOOP, decision())
    assert (later["key"], later["deduplicated"]) == ("WE012-POC-002", False)


def test_a_record_breaking_the_rules_is_refused_whole_and_nothing_is_stored(
    settings: Settings,
) -> None:
    world = poc_world(settings)
    with pytest.raises(PocDecisionRefusal) as caught:
        world.service.record(KEY, BOARD_ID, LOOP, decision(alternative="", reason="See `x`."))
    assert caught.value.code == "poc_decision_invalid"
    assert caught.value.details is not None
    assert caught.value.details["fields"] == [
        {"field": "reason", "rule": "code_span"},
        {"field": "alternative", "rule": "missing"},
    ]
    assert world.state.poc_decisions == [] and world.state.activity == []


def test_recording_needs_cards_write_a_writable_loop_and_a_ticket_of_that_loop(
    settings: Settings,
) -> None:
    world = poc_world(settings)
    with pytest.raises(Forbidden):
        world.service.record(VIEWER, BOARD_ID, LOOP, decision())
    with pytest.raises(Conflict) as mismatch:
        world.service.record(KEY, BOARD_ID, LOOP, decision(card_id=ELSEWHERE))
    assert mismatch.value.code == "loop_mismatch"
    with pytest.raises(NotFound):
        world.service.record(KEY, BOARD_ID, LOOP, decision(card_id="no-such-card"))
    for closed in (
        loop_row(LOOP, stage="completed", completed_at=STAMP),
        loop_row(LOOP, stage="cancelled", cancelled_at=STAMP),
        loop_row(LOOP, archived_at=STAMP),
    ):
        world = poc_world(settings, loop=closed)
        with pytest.raises(Conflict) as read_only:
            world.service.record(KEY, BOARD_ID, LOOP, decision())
        assert read_only.value.code == "loop_read_only"


@pytest.mark.parametrize(
    "stage", [stage for stage in LOOP_STAGES if stage not in ("completed", "cancelled")]
)
def test_recording_works_in_every_stage_a_loop_takes_writes_with_or_without_a_plan(
    settings: Settings, stage: str
) -> None:
    for plan in (None, "plan-1"):
        loop = loop_row(LOOP, stage=stage).__replace__(key="WE012", current_plan_id=plan)
        world = poc_world(settings, loop=loop)
        recorded = world.service.record(KEY, BOARD_ID, LOOP, decision(card_id=CARD))
        assert recorded["key"] == "WE012-POC-001"


def test_a_waiting_blocked_or_completed_ticket_never_refuses_a_record(settings: Settings) -> None:
    blocked = readiness_item(CARD, ready=False)
    world = poc_world(settings, items=[blocked])
    world.state.cards[CARD] = world.state.cards[CARD].__replace__(
        waiting_for="decision", waiting_reason="Which store?", waiting_set_at=STAMP
    )
    waiting = world.service.record(KEY, BOARD_ID, LOOP, decision(card_id=CARD))
    world.state.cards[CARD] = world.state.cards[CARD].__replace__(completed_at=STAMP)
    done = world.service.record(KEY, BOARD_ID, LOOP, missing(card_id=CARD))
    assert [waiting["key"], done["key"]] == ["WE012-POC-001", "WE012-POC-002"]


# --- listing, order, due and counts --------------------------------------------------------------


def test_the_list_is_in_review_order_with_counts_over_the_whole_loop(settings: Settings) -> None:
    world = poc_world(settings)
    plain = world.service.record(KEY, BOARD_ID, LOOP, decision(title="Plain"))
    gone = world.service.record(KEY, BOARD_ID, LOOP, decision(title="Missing"))
    world.service.record(KEY, BOARD_ID, LOOP, missing(card_id=CARD))
    world.service.record(KEY, BOARD_ID, LOOP, decision(title="Base", builds_on="The export."))
    world.service.answer(ADA, BOARD_ID, LOOP, gone["id"], PocDecisionAnswerCreate(answer="ok"))
    listed = world.service.list(VIEWER, BOARD_ID, LOOP)
    assert [item["key"] for item in listed["items"]] == [
        "WE012-POC-004",
        "WE012-POC-003",
        "WE012-POC-001",
        "WE012-POC-002",
    ]
    assert listed["counts"] == {
        "open": 3,
        "built_on_open": 1,
        "missing_open": 1,
        "due": 0,
        "answered": 1,
    }
    only_card = world.service.list(VIEWER, BOARD_ID, LOOP, card_id=CARD)
    assert [item["key"] for item in only_card["items"]] == ["WE012-POC-003"]
    assert only_card["counts"] == listed["counts"]
    answered = world.service.list(VIEWER, BOARD_ID, LOOP, status="ok")
    assert [item["id"] for item in answered["items"]] == [gone["id"]]
    assert plain["id"] in {item["id"] for item in listed["items"]}
    with pytest.raises(Forbidden):
        world.service.list(KEY.__replace__(scopes=frozenset()), BOARD_ID, LOOP)


def test_every_open_record_is_due_once_every_ticket_of_the_loop_is_completed(
    settings: Settings,
) -> None:
    world = poc_world(settings)
    world.service.record(KEY, BOARD_ID, LOOP, decision())
    assert world.service.list(VIEWER, BOARD_ID, LOOP)["counts"]["due"] == 0
    world.state.cards[CARD] = world.state.cards[CARD].__replace__(completed_at=STAMP)
    listed = world.service.list(VIEWER, BOARD_ID, LOOP)
    assert [item["due"] for item in listed["items"]] == [True]
    assert listed["counts"]["due"] == 1


def phase(phase_id: str, number: int, state: str) -> PhaseView:
    return {
        "id": phase_id,
        "number": number,
        "name": f"Phase {number}",
        "objective": "",
        "entry_conditions": [],
        "exit_conditions": [],
        "prerequisite_phase_ids": [],
        "prerequisite_ticket_ids": [],
        "state": state,
        "blocked_by": [],
        "tickets": [],
    }


def test_a_record_other_work_builds_on_is_due_once_the_phase_of_its_ticket_is_complete(
    settings: Settings,
) -> None:
    first = readiness_item(CARD, phase_number=1)
    first["completed_at"] = STAMP
    later = readiness_item("card-2", phase_number=2)
    later["phase_id"] = "phase-2"
    world = poc_world(
        settings,
        items=[first, later],
        phases=[phase("phase-1", 1, "complete"), phase("phase-2", 2, "in_progress")],
    )
    world.state.cards["card-2"] = card_row("card-2", "todo", LOOP)
    built = world.service.record(KEY, BOARD_ID, LOOP, decision(card_id=CARD, builds_on="Phase 2."))
    plain = world.service.record(KEY, BOARD_ID, LOOP, decision(card_id=CARD, title="Plain"))
    waiting = world.service.record(
        KEY, BOARD_ID, LOOP, decision(card_id="card-2", title="Later", builds_on="The end.")
    )
    by_key = {item["key"]: item for item in world.service.list(VIEWER, BOARD_ID, LOOP)["items"]}
    assert (by_key[built["key"]]["phase_number"], by_key[built["key"]]["phase_complete"]) == (
        1,
        True,
    )
    assert [by_key[key]["due"] for key in (built["key"], plain["key"], waiting["key"])] == [
        True,
        False,
        False,
    ]
    assert by_key[waiting["key"]]["phase_complete"] is False


def test_the_board_marks_feed_the_loop_summary_in_one_read(settings: Settings) -> None:
    world = poc_world(settings)
    world.service.record(KEY, BOARD_ID, LOOP, missing())
    marks = world.service.board_marks(KEY, BOARD_ID)
    assert list(marks) == [LOOP]
    assert [(mark.kind, mark.status, mark.built_on) for mark in marks[LOOP]] == [
        ("missing", "open", False)
    ]


# --- answering -----------------------------------------------------------------------------------


def test_a_key_never_answers_not_even_one_that_may_decide_in_the_editor(
    settings: Settings,
) -> None:
    world = poc_world(settings)
    recorded = world.service.record(KEY, BOARD_ID, LOOP, decision())
    EDITOR.require_person_or_editor_decision("Clearing a Ticket's wait")
    for actor in (KEY, EDITOR):
        with pytest.raises(Forbidden) as refused:
            world.service.answer(
                actor, BOARD_ID, LOOP, recorded["id"], PocDecisionAnswerCreate(answer="ok")
            )
        assert refused.value.code == "human_action_required"
    assert world.state.poc_decisions[0].status == "open"


def test_a_person_answers_ok_and_the_log_says_so(settings: Settings) -> None:
    world = poc_world(settings)
    recorded = world.service.record(KEY, BOARD_ID, LOOP, decision())
    answered = world.service.answer(
        ADA, BOARD_ID, LOOP, recorded["id"], PocDecisionAnswerCreate(answer="ok")
    )
    assert (answered["status"], answered["answered_at"], answered["answered_by_name"]) == (
        "ok",
        STAMP,
        "Ada",
    )
    assert answered["feedback_ticket"] is None
    assert json.loads(world.state.activity[-1].changes_json) == {
        "decision_id": recorded["id"],
        "key": "WE012-POC-001",
        "answer": "ok",
        "before": "open",
    }
    # OK again changes nothing.
    world.service.answer(ADA, BOARD_ID, LOOP, recorded["id"], PocDecisionAnswerCreate(answer="ok"))
    assert actions(world) == ["loop.poc_decision_recorded", "loop.poc_decision_answered"]


def test_feedback_creates_a_ticket_in_the_first_column_with_the_decision_as_its_basis(
    settings: Settings,
) -> None:
    world = poc_world(settings)
    recorded = world.service.record(
        KEY, BOARD_ID, LOOP, decision(card_id=CARD, details="The list sits in the cards module.")
    )
    world.service.answer(ADA, BOARD_ID, LOOP, recorded["id"], PocDecisionAnswerCreate(answer="ok"))
    answered = world.service.answer(
        ADA,
        BOARD_ID,
        LOOP,
        recorded["id"],
        PocDecisionAnswerCreate(answer="feedback", feedback="Keep it on the server instead."),
    )
    assert (answered["status"], answered["feedback"]) == (
        "feedback",
        "Keep it on the server instead.",
    )
    ticket = answered["feedback_ticket"]
    assert ticket is not None and ticket["key"] == "WE012-UNP-002"
    card = world.state.cards[ticket["id"]]
    assert (card.list_id, card.loop_id, card.kind) == ("todo", LOOP, "manual")
    assert card.title == "Feedback on WE012-POC-001: Store the list in the browser"
    assert card.description.startswith("## Feedback\n\nKeep it on the server instead.\n\n")
    for part in (
        "- What was chosen: The list lives in the browser for now.",
        "- Why: It is the quickest way to show the page.",
        "- The alternative: Keep it on the server.",
        "- How to change it: Move the list to the server later.",
        "- Taken on: WE012-UNP-001 Show the list",
        "### Details\n\nThe list sits in the cards module.",
    ):
        assert part in card.description
    assert world.state.poc_decisions[0].feedback_card_id == card.id
    assert actions(world)[-2:] == ["card.created", "loop.poc_decision_answered"]
    assert json.loads(world.state.activity[-1].changes_json)["feedback_card_id"] == card.id


def test_a_decision_answered_with_feedback_is_answered_and_nothing_more_is_stored(
    settings: Settings,
) -> None:
    world = poc_world(settings)
    recorded = world.service.record(KEY, BOARD_ID, LOOP, decision())
    feedback = PocDecisionAnswerCreate(answer="feedback", feedback="No.")
    world.service.answer(ADA, BOARD_ID, LOOP, recorded["id"], feedback)
    cards = len(world.state.cards)
    for again in (feedback, PocDecisionAnswerCreate(answer="ok")):
        with pytest.raises(Conflict) as twice:
            world.service.answer(ADA, BOARD_ID, LOOP, recorded["id"], again)
        assert twice.value.code == "poc_decision_answered"
    assert len(world.state.cards) == cards


def test_a_loop_that_takes_no_new_ticket_refuses_the_feedback_and_stores_nothing(
    settings: Settings,
) -> None:
    loop = loop_row(LOOP, stage="roadmap_review").__replace__(
        key="WE012", current_plan_id="plan-1"
    )
    world = poc_world(settings, loop=loop)
    recorded = world.service.record(KEY, BOARD_ID, LOOP, decision())
    cards = dict(world.state.cards)
    with pytest.raises(Conflict) as refused:
        world.service.answer(
            ADA,
            BOARD_ID,
            LOOP,
            recorded["id"],
            PocDecisionAnswerCreate(answer="feedback", feedback="Do it differently."),
        )
    assert refused.value.code == "plan_change_required"
    assert world.state.cards == cards
    assert world.state.poc_decisions[0].status == "open"
    assert actions(world) == ["loop.poc_decision_recorded"]


def test_answering_needs_a_record_of_that_loop_and_a_writable_loop(settings: Settings) -> None:
    world = poc_world(settings)
    recorded = world.service.record(KEY, BOARD_ID, LOOP, decision())
    with pytest.raises(NotFound) as unknown:
        world.service.answer(
            ADA, BOARD_ID, OTHER_LOOP, recorded["id"], PocDecisionAnswerCreate(answer="ok")
        )
    assert unknown.value.code == "poc_decision_not_found"
    world.state.loops[LOOP] = world.state.loops[LOOP].__replace__(archived_at=STAMP)
    with pytest.raises(Conflict) as read_only:
        world.service.answer(
            ADA, BOARD_ID, LOOP, recorded["id"], PocDecisionAnswerCreate(answer="ok")
        )
    assert read_only.value.code == "loop_read_only"


def test_a_decision_outlives_the_tickets_it_names(settings: Settings) -> None:
    world = poc_world(settings)
    recorded = world.service.record(KEY, BOARD_ID, LOOP, decision(card_id=CARD))
    answered = world.service.answer(
        ADA,
        BOARD_ID,
        LOOP,
        recorded["id"],
        PocDecisionAnswerCreate(answer="feedback", feedback="Again."),
    )
    ticket = answered["feedback_ticket"]
    assert ticket is not None
    with FakeBoardUnitOfWork(world.state).writer(BOARD_ID) as repos:
        repos.cards.delete(CARD)
        repos.cards.delete(ticket["id"])
    (row,) = world.state.poc_decisions
    assert (row.card_id, row.feedback_card_id, row.status) == (None, None, "feedback")


# --- the request schemas -------------------------------------------------------------------------


def test_the_answer_schema_wants_feedback_only_with_feedback() -> None:
    with pytest.raises(ValidationError):
        PocDecisionAnswerCreate(answer="feedback")
    with pytest.raises(ValidationError):
        PocDecisionAnswerCreate(answer="ok", feedback="Fine.")
    with pytest.raises(ValidationError):
        PocDecisionAnswerCreate(answer="feedback", feedback="x" * 2001)
    with pytest.raises(ValidationError):
        PocDecisionAnswerCreate.model_validate({"answer": "maybe"})
    assert PocDecisionAnswerCreate(answer="feedback", feedback="  Yes.  ").feedback == "Yes."


def test_the_record_schema_takes_a_kind_and_refuses_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PocDecisionCreate.model_validate({"kind": "question", "title": "x"})
    with pytest.raises(ValidationError):
        PocDecisionCreate.model_validate({"kind": "decision", "status": "ok"})
    assert decision(title="  Padded  ").title == "Padded"
