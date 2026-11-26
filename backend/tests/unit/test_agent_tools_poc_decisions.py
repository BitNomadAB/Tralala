"""The worker tools for what stands in the way of work, on the board fakes with the real services:
``record_poc_decision``, ``report_missing`` and ``list_poc_decisions`` (``PocDecisionService``),
``set_ticket_wait`` with and without the stop it is for (``TicketWorkService``), and the texts an
agent reads to pick the POC decision first."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api.mcp import INSTRUCTIONS, render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, ValidationFailure
from app.schemas.poc_decisions import PocDecisionAnswerCreate
from app.services.agent_tools import (
    CONFIRMATION_RULE,
    OBSTACLE_RULE,
    ToolResult,
    list_poc_decisions,
    record_poc_decision,
    report_missing,
    set_ticket_wait,
    tool_catalog,
)
from app.services.agent_tools_identity import HUMAN_DECISIONS
from app.services.agent_tools_poc_decisions import (
    DEDUPLICATED_NEXT_STEP,
    RECORDED_NEXT_STEP,
    REWRITE,
    listed_next_step,
)
from app.services.agent_tools_read import ticket_poc_decisions, ticket_wait
from app.services.agent_tools_work import INSTEAD, USE_INSTEAD
from app.services.cards import CardService
from app.services.loop_stops import DEFAULT_STOPS, NOT_A_STOP, LoopStopService
from app.services.loops import LoopService
from app.services.poc_decision_rules import POC_DECISION_INVALID
from app.services.poc_decisions import PocDecisionService
from app.services.ticket_work import TicketWorkService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import FakePlanViews, plan_views
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
STAMP = "2026-11-26T09:00:00Z"
# A UUID, as a Loop's row has it.
LOOP = "7d1c2b3a-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
CARD = "3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f"
KEY = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Worker",
    scopes=frozenset({"cards:read", "cards:write", "loops:read"}),
    credential_id="key-1",
)
READER = KEY.__replace__(scopes=frozenset({"cards:read", "loops:read"}))
ADA = ActorContext(
    actor_id="user-ada",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"cards:read", "cards:write", "loops:read", "loops:write"}),
)
OLD_NEXT_STEP = (
    "A person answers and clears the wait in the Ticket dialog; list_tickets with needs_person "
    "true lists what waits for a person."
)


@dataclass(frozen=True, slots=True)
class PocToolWorld:
    """What the tools declare they use of the composition root, and the board."""

    poc_decisions: PocDecisionService
    loop: LoopService
    card: CardService
    ticket_work: TicketWorkService
    loop_stops: LoopStopService
    settings: Settings
    state: BoardState


def poc_tool_world(settings: Settings) -> PocToolWorld:
    """Loop WE012 (no plan, in progress) with a Todo and a Doing column and one Ticket added by
    hand (``CARD``, WE012-UNP-001, in Doing), whose stop list is the default one."""
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="in_progress").__replace__(key="WE012")}
    state.lists = {
        "todo": list_row("todo", LOOP, 512, name="Todo"),
        "doing": list_row("doing", LOOP, 1024, name="Doing"),
    }
    state.cards = {
        CARD: card_row(CARD, "doing", LOOP).__replace__(
            kind="manual", ticket_key="WE012-UNP-001", title="Show the list"
        )
    }
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(state)
    views = plan_views(FakePlanViews(items=[]))
    cards = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=views,
        clock=lambda: NOW,
    )
    return PocToolWorld(
        poc_decisions=PocDecisionService(checks, store, cards, plans=views, clock=lambda: NOW),
        loop=LoopService(settings, checks, store, plans=views, tickets=cards, clock=lambda: NOW),
        card=cards,
        ticket_work=TicketWorkService(checks, store, cards, clock=lambda: NOW),
        loop_stops=LoopStopService(checks, store, clock=lambda: NOW),
        settings=settings,
        state=state,
    )


def decision(**changes: JsonValue) -> dict[str, JsonValue]:
    return {
        "board_id": BOARD_ID,
        "loop_id": LOOP,
        "card_id": CARD,
        "title": "Store the list in the browser",
        "chosen": "The list lives in the browser for now.",
        "reason": "It is the quickest way to show the page.",
        "alternative": "Keep it on the server.",
        "change_path": "Move the list to the server later.",
        **changes,
    }


def missing(**changes: JsonValue) -> dict[str, JsonValue]:
    return {
        "board_id": BOARD_ID,
        "loop_id": LOOP,
        "title": "No mail account",
        "missing": "An account for the mail service.",
        "reason": "The invitation mail needs it.",
        "went_around": "Invitations are shown as a link to copy.",
        "when_provided": "Send the mail once the account is there.",
        **changes,
    }


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_rows(value: object) -> TypeIs[list[Mapping[str, object]]]:
    return _is_list(value) and all(_is_mapping(row) for row in value)


def items(answer: ToolResult) -> list[Mapping[str, object]]:
    value = answer["items"]
    assert _is_rows(value)
    return value


def part(answer: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = answer[key]
    assert _is_mapping(value)
    return value


# --- record_poc_decision -------------------------------------------------------------------------


def test_record_poc_decision_records_it_by_the_loops_key_and_says_to_go_on(
    settings: Settings,
) -> None:
    world = poc_tool_world(settings)
    answer = record_poc_decision(world, KEY, decision(loop_id="we012"))
    assert answer == {
        "id": world.state.poc_decisions[0].id,
        "key": "WE012-POC-001",
        "kind": "decision",
        "status": "open",
        "card_id": CARD,
        "ticket_key": "WE012-UNP-001",
        "built_on": False,
        "deduplicated": False,
        "next_step": RECORDED_NEXT_STEP,
    }
    assert "nothing waits for this" in RECORDED_NEXT_STEP
    (row,) = world.state.poc_decisions
    assert (row.kind, row.chosen, row.created_by_type) == (
        "decision",
        "The list lives in the browser for now.",
        "agent",
    )
    # A retry answers the first record and stores nothing new.
    again = record_poc_decision(world, KEY, decision())
    assert (again["key"], again["deduplicated"], again["next_step"]) == (
        "WE012-POC-001",
        True,
        DEDUPLICATED_NEXT_STEP,
    )
    assert len(world.state.poc_decisions) == 1
    # Without a Ticket, and with what builds on it.
    loose = record_poc_decision(
        world,
        KEY,
        decision(card_id=None, title="Name the column", builds_on="The export reads it."),
    )
    assert (loose["key"], loose["card_id"], loose["built_on"]) == ("WE012-POC-002", None, True)


def test_a_record_breaking_the_rules_is_refused_with_each_field_and_rule(
    settings: Settings,
) -> None:
    world = poc_tool_world(settings)
    with pytest.raises(ValidationFailure) as refused:
        record_poc_decision(
            world, KEY, decision(reason="", chosen="Keep it in a `cache` for now.")
        )
    assert refused.value.code == POC_DECISION_INVALID
    assert refused.value.status_code == 422
    details = refused.value.details
    assert details is not None
    assert details["fields"] == [
        {"field": "chosen", "rule": "code_span"},
        {"field": "reason", "rule": "missing"},
    ]
    assert details["error_count"] == 2
    assert refused.value.message.endswith(REWRITE)
    assert "reason: missing. Say why it was chosen." in refused.value.message
    assert world.state.poc_decisions == []
    # A field too long for any request names its argument too.
    with pytest.raises(ValidationFailure) as too_long:
        record_poc_decision(world, KEY, decision(details="x" * 40_001))
    assert too_long.value.details == {"argument": "details"}


def test_recording_needs_cards_write_and_a_ticket_of_the_loop(settings: Settings) -> None:
    world = poc_tool_world(settings)
    with pytest.raises(Forbidden):
        record_poc_decision(world, READER, decision())
    with pytest.raises(Forbidden):
        report_missing(world, READER, missing())
    world.state.loops["other"] = loop_row("other").__replace__(sequence=2, key="OT002")
    world.state.cards["far"] = card_row("far", "todo", "other")
    with pytest.raises(Conflict) as elsewhere:
        record_poc_decision(world, KEY, decision(card_id="far"))
    assert elsewhere.value.code == "loop_mismatch"
    with pytest.raises(ValidationFailure, match="board_id"):
        record_poc_decision(world, KEY, {**decision(), "board_id": None})


# --- report_missing ------------------------------------------------------------------------------


def test_report_missing_stores_how_the_work_goes_around_it(settings: Settings) -> None:
    world = poc_tool_world(settings)
    answer = report_missing(world, KEY, missing())
    assert (answer["key"], answer["kind"], answer["card_id"], answer["deduplicated"]) == (
        "WE012-POC-001",
        "missing",
        None,
        False,
    )
    assert answer["next_step"] == RECORDED_NEXT_STEP
    (row,) = world.state.poc_decisions
    assert (row.missing, row.chosen, row.change_path) == (
        "An account for the mail service.",
        "Invitations are shown as a link to copy.",
        "Send the mail once the account is there.",
    )


def test_a_missing_report_is_refused_under_the_names_the_tool_took(settings: Settings) -> None:
    world = poc_tool_world(settings)
    with pytest.raises(ValidationFailure) as refused:
        report_missing(world, KEY, missing(went_around="", when_provided=""))
    assert refused.value.code == POC_DECISION_INVALID
    details = refused.value.details
    assert details is not None
    assert details["fields"] == [
        {"field": "went_around", "rule": "missing"},
        {"field": "when_provided", "rule": "missing"},
    ]
    assert details["errors"] == [
        "went_around: missing. Say how the work goes around it.",
        "when_provided: missing. Say what is done once it is there.",
    ]
    assert "chosen" not in refused.value.message
    assert world.state.poc_decisions == []


# --- list_poc_decisions --------------------------------------------------------------------------


def test_the_list_shows_what_the_person_answered_and_the_ticket_feedback_became(
    settings: Settings,
) -> None:
    world = poc_tool_world(settings)
    first = record_poc_decision(world, KEY, decision(details="The list sits in the store module."))
    record_poc_decision(world, KEY, decision(title="Name the column", chosen="Todo."))
    report_missing(world, KEY, missing())
    world.poc_decisions.answer(
        ADA,
        BOARD_ID,
        LOOP,
        str(first["id"]),
        PocDecisionAnswerCreate(answer="feedback", feedback="Keep it on the server instead."),
    )
    answer = list_poc_decisions(world, READER, {"board_id": BOARD_ID, "loop_id": LOOP})
    listed = items(answer)
    # The order a person reviews them: what is missing, the other open one, the answered one.
    assert [item["key"] for item in listed] == ["WE012-POC-003", "WE012-POC-002", "WE012-POC-001"]
    gone, _, answered = listed
    assert (gone["went_around"], gone["when_provided"]) == (
        "Invitations are shown as a link to copy.",
        "Send the mail once the account is there.",
    )
    assert "chosen" not in gone
    assert (answered["status"], answered["feedback"], answered["answered_by"]) == (
        "feedback",
        "Keep it on the server instead.",
        "Ada",
    )
    ticket = part(answered, "feedback_ticket")
    created = world.state.cards[str(ticket["id"])]
    assert ticket["key"] == created.ticket_key
    assert created.title.startswith("Feedback on WE012-POC-001")
    assert (answered["has_details"], "details" in answered) == (True, False)
    assert answer["counts"] == {
        "open": 2,
        "built_on_open": 0,
        "missing_open": 1,
        "due": 0,
        "answered": 1,
    }
    assert "read_ticket" in str(answer["next_step"])
    # Narrowed to a status or a Ticket, with the details on request.
    narrowed = list_poc_decisions(
        world,
        READER,
        {"board_id": BOARD_ID, "loop_id": LOOP, "status": "feedback", "include_details": True},
    )
    (only,) = items(narrowed)
    assert only["details"] == "The list sits in the store module."
    on_ticket = list_poc_decisions(
        world, READER, {"board_id": BOARD_ID, "loop_id": LOOP, "card_id": CARD}
    )
    assert [item["key"] for item in items(on_ticket)] == ["WE012-POC-002", "WE012-POC-001"]
    with pytest.raises(ValidationFailure) as unknown:
        list_poc_decisions(world, READER, {"board_id": BOARD_ID, "loop_id": LOOP, "status": "x"})
    assert unknown.value.details == {"argument": "status", "choices": ["open", "ok", "feedback"]}


def test_the_lists_next_step_follows_what_was_answered() -> None:
    assert "go on" in listed_next_step([{"status": "open"}])
    assert "read_ticket" in listed_next_step([{"status": "ok"}, {"status": "feedback"}])
    assert listed_next_step([{"status": "ok"}]) == "Nothing here waits for anyone."


def test_read_ticket_names_the_records_taken_on_it(settings: Settings) -> None:
    world = poc_tool_world(settings)
    record_poc_decision(world, KEY, decision())
    report_missing(world, KEY, missing(card_id=CARD))
    listing = world.poc_decisions.list(READER, BOARD_ID, LOOP, card_id=CARD)
    assert ticket_poc_decisions(listing) == {
        "count": 2,
        "open": 2,
        "keys": ["WE012-POC-002", "WE012-POC-001"],
    }
    assert "poc_decisions" in tool_catalog()["read_ticket"].description


# --- set_ticket_wait and the stop list -----------------------------------------------------------


def wait(**changes: JsonValue) -> dict[str, JsonValue]:
    return {
        "board_id": BOARD_ID,
        "card_id": CARD,
        "waiting_for": "decision",
        "reason": "The old rows go once this runs.",
        **changes,
    }


def test_a_wait_names_its_stop_by_its_text_or_its_number(settings: Settings) -> None:
    world = poc_tool_world(settings)
    answer = set_ticket_wait(world, KEY, wait(stop="  deleting DATA "))
    assert part(answer, "wait")["stop"] == "Deleting data"
    assert answer["next_step"] == f"{OLD_NEXT_STEP} Work on other Tickets meanwhile."
    assert world.state.cards[CARD].waiting_stop == "Deleting data"
    # read_ticket shows the stop with the wait; a wait without one has no such key.
    shown = ticket_wait(world.card.get(BOARD_ID, LOOP, CARD), loop_read_only=False, public_url=None)
    assert shown is not None and shown["stop"] == "Deleting data"
    other = poc_tool_world(settings)
    by_number = set_ticket_wait(other, KEY, wait(stop="1"))
    assert part(by_number, "wait")["stop"] == "Deployment to production"
    # A number sent as a JSON number names the line all the same.
    third = poc_tool_world(settings)
    assert part(set_ticket_wait(third, KEY, wait(stop=3)), "wait")["stop"] == "Money"


def test_a_wait_without_a_stop_answers_as_it_always_did(settings: Settings) -> None:
    world = poc_tool_world(settings)
    answer = set_ticket_wait(world, KEY, wait(waiting_for="access", reason="The API key"))
    assert answer["wait"] == {
        "waiting_for": "access",
        "reason": "The API key",
        "set_by": "agent-1",
        "set_at": STAMP,
    }
    assert answer["next_step"] == OLD_NEXT_STEP
    assert world.state.cards[CARD].waiting_stop is None
    shown = ticket_wait(world.card.get(BOARD_ID, LOOP, CARD), loop_read_only=False, public_url=None)
    assert shown is not None and "stop" not in shown
    # An empty stop is no stop.
    fresh = poc_tool_world(settings)
    assert "stop" not in part(set_ticket_wait(fresh, KEY, wait(stop="  ")), "wait")


def test_a_stop_the_list_does_not_name_is_refused_with_the_list_and_what_to_use(
    settings: Settings,
) -> None:
    world = poc_tool_world(settings)
    with pytest.raises(ValidationFailure) as refused:
        set_ticket_wait(world, KEY, wait(stop="Which colour the button has"))
    assert (refused.value.code, refused.value.status_code) == (NOT_A_STOP, 422)
    assert refused.value.details == {
        "stops": list(DEFAULT_STOPS),
        "use_instead": list(USE_INSTEAD),
    }
    message = refused.value.message
    assert INSTEAD in message
    assert "1. Deployment to production; 2. Deleting data" in message
    assert world.state.cards[CARD].waiting_for == "nothing"
    # A person's list is the one the refusal names; an empty one stops nothing.
    their_list = ["Changing a customer's invoice"]
    world.loop_stops.write(ADA, BOARD_ID, LOOP, their_list)
    with pytest.raises(ValidationFailure) as theirs:
        set_ticket_wait(world, KEY, wait(stop="2"))
    assert theirs.value.details is not None
    assert theirs.value.details["stops"] == their_list
    world.loop_stops.write(ADA, BOARD_ID, LOOP, [])
    with pytest.raises(ValidationFailure) as empty:
        set_ticket_wait(world, KEY, wait(stop="1"))
    assert "This Loop's stop list is empty: nothing stops its work." in empty.value.message
    # A stop longer than any line is named as the argument it is.
    with pytest.raises(ValidationFailure) as long_stop:
        set_ticket_wait(world, KEY, wait(stop="x" * 2000))
    assert long_stop.value.details == {"argument": "stop"}


def test_set_ticket_wait_offers_stop_as_an_optional_argument() -> None:
    tool = tool_catalog()["set_ticket_wait"]
    assert "stop" in tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["board_id", "card_id", "waiting_for", "reason"]
    assert tool.description.startswith("Stop a Ticket for a real stop: something the Loop's")
    assert "record_poc_decision" in tool.description
    assert "report_missing" in tool.description


# --- the catalogue and the texts -----------------------------------------------------------------


def test_the_tools_are_offered_to_the_scopes_they_declare(settings: Settings) -> None:
    catalogue = tool_catalog()
    assert catalogue["record_poc_decision"].scopes == ("cards:write",)
    assert catalogue["report_missing"].scopes == ("cards:write",)
    assert catalogue["list_poc_decisions"].scopes == ("cards:read",)
    names = list(catalogue)
    assert names.index("set_ticket_wait") + 1 == names.index("record_poc_decision")
    offered = {tool["name"] for tool in tool_list(READER)}
    assert "list_poc_decisions" in offered
    assert not offered & {"record_poc_decision", "report_missing"}
    # Answering one and writing the stop list are a person's, so no tool does either.
    assert not [name for name in names if "answer" in name or "stop" in name]
    text = render_bootstrap(settings)
    for name, scope in (
        ("record_poc_decision", "cards:write"),
        ("report_missing", "cards:write"),
        ("list_poc_decisions", "cards:read"),
    ):
        assert f"### {name} (requires `{scope}`)" in text


def test_the_descriptions_put_the_poc_decision_first() -> None:
    catalogue = tool_catalog()
    record = catalogue["record_poc_decision"].description
    assert record.startswith(
        "Write down a POC decision: a choice you took yourself, so that work could go on, for a "
        "person to review afterwards."
    )
    assert "it never blocks anything and you go on working at once" in record
    assert "no file paths, code or ids; those go in details" in record
    gone = catalogue["report_missing"].description
    assert gone.startswith("Say that something only a person can provide is missing")
    assert "Never put a secret" in gone
    assert "done, awaiting confirmation" in catalogue["complete_ticket"].description
    waiting_for = str(catalogue["create_ticket"].input_schema["properties"]["waiting_for"])
    assert "stop list" in waiting_for
    assert "stop list" in str(catalogue["write_roadmap"].input_schema)
    assert "stops" in catalogue["read_loop"].description


def test_the_instructions_say_the_three_kinds_and_only_the_last_stops() -> None:
    flat = " ".join(INSTRUCTIONS.split())
    assert OBSTACLE_RULE in flat
    assert CONFIRMATION_RULE in flat
    assert "When you cannot go on without an answer" not in flat
    assert flat.index("record_poc_decision") < flat.index("report_missing")
    assert flat.index("report_missing") < flat.index("set_ticket_wait")
    assert (
        "An obstacle that is not on the stop list is never a reason to wait or to ask first."
        in OBSTACLE_RULE
    )
    assert (
        "answering a POC decision and writing a Loop's stop list are human decisions that no "
        "token can perform" in flat
    )


def test_llms_txt_works_a_ticket_with_the_three_kinds(settings: Settings) -> None:
    text = render_bootstrap(settings)
    working = text.split("### Working a Ticket", 1)[1].split("### Follow-ups", 1)[0]
    working = " ".join(working.split())
    order = ("`record_poc_decision`", "`report_missing`", "`set_ticket_wait`")
    assert [working.index(name) for name in order] == sorted(working.index(n) for n in order)
    assert "An obstacle that is not on the stop list is never a reason to wait" in working
    assert "`422 not_a_stop`" in working
    assert "`422 poc_decision_invalid`" in working
    assert "done, awaiting confirmation" in working
    rules = " ".join(text.split("\n## 4. ", 1)[1].split("\n## 5. ", 1)[0].split())
    assert "answering a POC decision, writing a Loop's stop list, and finalizing a Loop" in rules
    assert "Only what the Loop's stop list names stops work." in rules


def test_whoami_names_answering_and_the_stop_list_as_a_persons() -> None:
    assert "answering a POC decision" in HUMAN_DECISIONS
    assert "writing a Loop's stop list" in HUMAN_DECISIONS
