"""``ask_person`` in the mode ``form`` on the fakes: the person decides in the editor as themselves.

The world is ``test_agent_tools_decisions``'s: the real Loop, Ticket, review, wait, QA, outcome,
request-state and auth services on an in-memory board and registry, with a clock the test moves.
Here the installation's setting ``editor_decisions`` is on and the key ``cred-1`` (Laptop) holds the
right ``loops:decide``; ``cred-2`` (Desktop) is another key of the same person without it. What is
tested: when the form is offered and never; its schema and message; each of the five decisions
taken as the owner, marked ``taken_through`` the key, with one comment on a Ticket; an answer that
is not the form's, a stale revision or version, a removed right, a setting turned off and a
disabled owner between question and answer; ``decline``, ``cancel`` and the choices that take no
decision; and two keys of one person on one decision."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import timedelta
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.core.config import Settings
from app.core.context import DECIDE_SCOPE, ActorContext
from app.core.errors import Forbidden
from app.services.agent_tools import (
    NO_INPUT,
    InputRequired,
    ToolInput,
    ToolResult,
    ask_person,
    ask_person_with_input,
)
from app.services.agent_tools_decide import FEEDBACK_MAX, FORM_NOTE, FormDecision, form_schema
from app.services.decision_outcomes import AskedDecision
from app.services.decision_requests import CLOSED, REQUESTED
from tests.unit.fakes.board import BOARD_ID, phase_row, plan_row
from tests.unit.test_agent_tools_decisions import (
    BOTH,
    CARD,
    FORM,
    KEY,
    LOOP,
    PERSON,
    PERSON_NAME,
    SCOPES,
    SECOND_KEY,
    URL,
    World,
    args_for,
    asked,
    complete,
    params,
    world_for,
)

RIGHT = KEY.__replace__(scopes=SCOPES | {DECIDE_SCOPE})
FIVE: tuple[FormDecision, ...] = ("analysis", "roadmap", "wait", "confirmation", "implementation")
TAKE: dict[FormDecision, str] = {
    "analysis": "approve",
    "roadmap": "approve",
    "wait": "clear",
    "confirmation": "confirm",
    "implementation": "accept",
}
LAPTOP_TAKEN = {"credential_id": "cred-1", "key_name": "Laptop", "via": "form"}


def deciding(settings: Settings, decision: AskedDecision, *, setting: bool = True) -> World:
    """``world_for(decision)`` with the setting on and the right on the key Laptop; the
    implementation in a Loop with a plan, whose acceptance hands it to its QA."""
    w = world_for(settings, decision)
    w.settings.editor_decisions = setting
    laptop = w.registry.credentials["cred-1"]
    w.registry.credentials["cred-1"] = laptop.__replace__(
        scopes=json.dumps(sorted(SCOPES | {DECIDE_SCOPE}))
    )
    if decision == "implementation":
        w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(current_plan_id="plan-1")
        w.state.plans["plan-1"] = plan_row("plan-1", LOOP)
        w.state.phases["phase-1"] = phase_row("phase-1", LOOP, "plan-1", 1)
    return w


def ask(
    w: World, decision: AskedDecision, given: ToolInput = FORM, key: ActorContext = RIGHT
) -> ToolResult | InputRequired:
    return ask_person_with_input(w, key, args_for(decision), given)


def answer(
    state: str, action: str = "accept", content: Mapping[str, JsonValue] | None = None
) -> ToolInput:
    response: dict[str, JsonValue] = {"action": action}
    if content is not None:
        response["content"] = dict(content)
    return ToolInput(form=True, responses={"decision": response}, request_state=state)


def answer_with(
    w: World,
    decision: AskedDecision,
    state: str,
    choice: str,
    feedback: str = "",
    key: ActorContext = RIGHT,
) -> ToolResult | InputRequired:
    content: dict[str, JsonValue] = {"decision": choice}
    if feedback:
        content["feedback"] = feedback
    return ask_person_with_input(w, key, args_for(decision), answer(state, content=content))


def _is_fields(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def logged(w: World, action: str) -> Mapping[str, object]:
    """The changes of the one history row ``action``, which the person wrote."""
    rows = [row for row in w.state.activity if row.action == action]
    assert len(rows) == 1, [row.action for row in w.state.activity]
    assert (rows[0].actor_id, rows[0].actor_type) == (PERSON, "user")
    found: object = json.loads(rows[0].changes_json or "{}")
    assert _is_fields(found)
    return found


def choices(decision: FormDecision) -> list[object]:
    properties = form_schema(decision)["properties"]
    assert _is_fields(properties)
    choice = properties["decision"]
    assert _is_fields(choice)
    options = choice["oneOf"]
    assert isinstance(options, list)
    return [option["const"] for option in options if _is_fields(option)]


def nothing_decided(w: World) -> None:
    """No approval, review, cleared wait, confirmation or comment since the question."""
    assert not [row for row in w.state.approvals if row.created_at >= "2026-11-26T12"]
    assert all(card.human_confirmed_at is None for card in w.state.cards.values())
    assert not [row for row in w.state.activity if row.action.endswith(("_reviewed", "_cleared"))]
    assert w.state.comments == {}


# --- when the form is offered ----------------------------------------------------------------


@pytest.mark.parametrize("decision", FIVE)
def test_the_five_decisions_are_asked_as_a_form_with_the_setting_the_right_and_the_mode(
    settings: Settings, decision: FormDecision
) -> None:
    w = deciding(settings, decision)
    found = params(asked(ask(w, decision, BOTH)))
    assert found["mode"] == "form"
    assert "url" not in found
    assert found["requestedSchema"] == form_schema(decision)
    (row,) = [entry for entry in w.state.activity if entry.action == REQUESTED]
    assert json.loads(row.changes_json or "{}")["via"] == "form"


@pytest.mark.parametrize(
    ("setting", "right", "given"),
    [(False, True, FORM), (True, False, FORM), (True, True, URL), (True, True, NO_INPUT)],
    ids=["setting-off", "no-right", "url-only", "no-modes"],
)
def test_without_the_setting_the_right_or_the_mode_the_question_is_as_before(
    settings: Settings, setting: bool, right: bool, given: ToolInput
) -> None:
    w = deciding(settings, "analysis", setting=setting)
    reply = ask(w, "analysis", given, RIGHT if right else KEY)
    if isinstance(reply, InputRequired):
        assert params(reply)["mode"] == "url"
    else:
        assert reply["status"] == "waiting_for_person"


def test_qa_and_the_implementation_of_a_loop_without_a_plan_never_get_a_form(
    settings: Settings,
) -> None:
    qa = deciding(settings, "qa")
    assert params(asked(ask(qa, "qa", BOTH)))["mode"] == "url"
    assert complete(ask(qa, "qa", FORM))["status"] == "waiting_for_person"
    closing = world_for(settings, "implementation")
    closing.settings.editor_decisions = True
    assert params(asked(ask(closing, "implementation", BOTH)))["mode"] == "url"


def test_a_client_of_2025_06_18_is_never_asked_a_form(settings: Settings) -> None:
    w = deciding(settings, "analysis")
    assert ask_person(w, RIGHT, args_for("analysis"))["status"] == "waiting_for_person"


def test_another_key_of_the_same_person_without_the_right_gets_no_form(settings: Settings) -> None:
    w = deciding(settings, "wait")
    assert params(asked(ask(w, "wait", BOTH)))["mode"] == "form"
    assert params(asked(ask(w, "wait", BOTH, SECOND_KEY)))["mode"] == "url"


# --- the form itself -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("decision", "question"),
    [
        ("analysis", "Approve revision 1 of the analysis of L-1, or ask for changes."),
        ("roadmap", "Approve revision 1 of the RoadMap of L-1, or ask for changes."),
        ("wait", "Clear the wait on L-1-UNP-001 in L-1, or keep it."),
        ("confirmation", "Confirm that the person's task L-1-UNP-001 in L-1 is done, or not yet."),
        ("implementation", "Accept the implementation of L-1 and hand it to its QA, or not yet."),
    ],
)
def test_the_message_names_the_keys_and_the_revision_in_plain_english(
    settings: Settings, decision: FormDecision, question: str
) -> None:
    w = deciding(settings, decision)
    found = params(asked(ask(w, decision)))
    assert found["message"] == f"{question} {FORM_NOTE}"
    assert "the agent never fills it in" in FORM_NOTE
    text = json.dumps(found)
    for forbidden in ("http", "/boards/", LOOP, CARD, BOARD_ID, "cred-1"):
        assert forbidden not in text


def test_the_schema_is_a_flat_object_with_a_titled_enum_and_a_bounded_text() -> None:
    assert form_schema("wait") == {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "title": "Your decision",
                "oneOf": [
                    {"const": "clear", "title": "Clear the wait"},
                    {"const": "keep", "title": "Keep the wait"},
                ],
            },
            "feedback": {
                "type": "string",
                "title": "Feedback",
                "description": "Optional: what you want changed or want the agent to know.",
                "maxLength": FEEDBACK_MAX,
            },
        },
        "required": ["decision"],
    }
    assert {decision: choices(decision) for decision in FIVE} == {
        "analysis": ["approve", "request_changes"],
        "roadmap": ["approve", "request_changes"],
        "wait": ["clear", "keep"],
        "confirmation": ["confirm", "not_yet"],
        "implementation": ["accept", "reject"],
    }


# --- the decision, taken as the owner --------------------------------------------------------


def test_approving_the_analysis_in_the_editor_is_the_persons_approval_through_the_key(
    settings: Settings,
) -> None:
    w = deciding(settings, "analysis")
    state = asked(ask(w, "analysis")).request_state
    reply = complete(answer_with(w, "analysis", state, "approve", "Looks right"))
    assert reply["status"] == "decided"
    assert (reply["outcome"], reply["decided_by_id"], reply["decided_by"]) == (
        "approved",
        PERSON,
        PERSON_NAME,
    )
    assert reply["taken_through"] == "Laptop"
    (approval,) = w.state.approvals
    assert (approval.reviewer_actor_id, approval.decision, approval.feedback) == (
        PERSON,
        "approved",
        "Looks right",
    )
    changes = logged(w, "loop.analysis_reviewed")
    assert changes["taken_through"] == LAPTOP_TAKEN
    assert changes["asked_through"] == [LAPTOP_TAKEN]


def test_asking_for_changes_to_the_roadmap_in_the_editor_is_a_decision(settings: Settings) -> None:
    w = deciding(settings, "roadmap")
    state = asked(ask(w, "roadmap")).request_state
    reply = complete(answer_with(w, "roadmap", state, "request_changes", "Split phase 2"))
    assert (reply["status"], reply["outcome"]) == ("decided", "changes_requested")
    assert logged(w, "loop.roadmap_reviewed")["taken_through"] == LAPTOP_TAKEN


@pytest.mark.parametrize(
    ("decision", "action", "outcome", "said"),
    [
        ("wait", "card.wait_cleared", "cleared", "cleared the wait on this Ticket"),
        (
            "confirmation",
            "card.human_confirmed",
            "confirmed",
            "confirmed that the person's task on this Ticket is done",
        ),
    ],
)
def test_a_decision_on_a_ticket_in_the_editor_leaves_exactly_one_comment(
    settings: Settings, decision: FormDecision, action: str, outcome: str, said: str
) -> None:
    w = deciding(settings, decision)
    # Both of the person's keys ask; only Laptop holds the right and answers.
    assert params(asked(ask(w, decision, BOTH, SECOND_KEY)))["mode"] == "url"
    w.clock.moment += timedelta(minutes=1)
    state = asked(ask(w, decision)).request_state
    reply = complete(answer_with(w, decision, state, TAKE[decision]))
    assert (reply["status"], reply["outcome"]) == ("decided", outcome)
    changes = logged(w, action)
    assert changes["taken_through"] == LAPTOP_TAKEN
    assert changes["asked_through"] == [
        {"credential_id": "cred-2", "key_name": "Desktop", "via": "link"},
        LAPTOP_TAKEN,
    ]
    (comment,) = w.state.comments.values()
    assert comment.actor_id == PERSON
    assert comment.content == (
        f"{PERSON_NAME} {said} in a coding session through the key Laptop. The question came "
        "from a coding session through the keys Desktop and Laptop."
    )


def test_accepting_the_implementation_in_the_editor_hands_the_loop_to_its_qa(
    settings: Settings,
) -> None:
    w = deciding(settings, "implementation")
    state = asked(ask(w, "implementation")).request_state
    reply = complete(answer_with(w, "implementation", state, "accept", "Ship it"))
    assert (reply["status"], reply["outcome"]) == ("decided", "accepted")
    (approval,) = [row for row in w.state.approvals if row.scope == "implementation"]
    assert approval.reviewer_actor_id == PERSON
    extra: object = json.loads(approval.revisions_json)
    assert _is_fields(extra)
    assert extra["taken_through"] == LAPTOP_TAKEN
    assert w.state.loops[LOOP].implementation_approval_id == approval.id
    assert w.state.loops[LOOP].completed_at is None
    assert logged(w, "loop.implementation_accepted")["taken_through"] == LAPTOP_TAKEN


# --- answers that take no decision -----------------------------------------------------------


@pytest.mark.parametrize("action", ["decline", "cancel"])
@pytest.mark.parametrize("decision", FIVE)
def test_decline_and_cancel_take_no_decision(
    settings: Settings, decision: FormDecision, action: str
) -> None:
    w = deciding(settings, decision)
    state = asked(ask(w, decision)).request_state
    reply = complete(ask_person_with_input(w, RIGHT, args_for(decision), answer(state, action)))
    assert reply["status"] == ("declined" if action == "decline" else "cancelled")
    nothing_decided(w)


@pytest.mark.parametrize(
    ("decision", "choice"),
    [("wait", "keep"), ("confirmation", "not_yet"), ("implementation", "reject")],
)
def test_keeping_it_as_it_is_takes_no_decision_and_closes_the_question(
    settings: Settings, decision: FormDecision, choice: str
) -> None:
    w = deciding(settings, decision)
    state = asked(ask(w, decision)).request_state
    reply = complete(answer_with(w, decision, state, choice, "Not before Friday"))
    assert (reply["status"], reply["feedback"]) == ("not_decided", "Not before Friday")
    nothing_decided(w)
    assert [row.action for row in w.state.activity] == [REQUESTED, CLOSED]


@pytest.mark.parametrize(
    "content",
    [
        {"decision": "maybe"},
        {"feedback": "no choice"},
        {"decision": "approve", "feedback": "x" * (FEEDBACK_MAX + 1)},
        {"decision": "approve", "extra": "field"},
    ],
    ids=["unknown-choice", "no-choice", "too-long", "extra-field"],
)
def test_an_answer_that_is_not_the_forms_is_asked_again(
    settings: Settings, content: dict[str, JsonValue]
) -> None:
    w = deciding(settings, "analysis")
    state = asked(ask(w, "analysis")).request_state
    given = answer(state, content=content)
    again = asked(ask_person_with_input(w, RIGHT, args_for("analysis"), given))
    assert params(again)["mode"] == "form"
    assert again.request_state != state
    nothing_decided(w)


def test_accept_without_content_is_asked_again(settings: Settings) -> None:
    w = deciding(settings, "analysis")
    state = asked(ask(w, "analysis")).request_state
    again = asked(ask_person_with_input(w, RIGHT, args_for("analysis"), answer(state)))
    assert params(again)["mode"] == "form"
    nothing_decided(w)


# --- what changed between the question and the answer ----------------------------------------


def test_a_revision_that_changed_is_asked_again_with_the_one_in_force(settings: Settings) -> None:
    w = deciding(settings, "analysis")
    state = asked(ask(w, "analysis")).request_state
    # A new revision of the analysis replaced the one the question was about.
    w.state.documents = [
        row.__replace__(id="analysis-2", revision_number=2) if row.kind == "analysis" else row
        for row in w.state.documents
    ]
    again = asked(answer_with(w, "analysis", state, "approve"))
    found = params(again)
    assert found["mode"] == "form"
    assert "revision 2" in str(found["message"])
    nothing_decided(w)


def test_a_ticket_changed_since_the_question_is_asked_again(settings: Settings) -> None:
    w = deciding(settings, "wait")
    state = asked(ask(w, "wait")).request_state
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(version=w.state.cards[CARD].version + 1)
    assert params(asked(answer_with(w, "wait", state, "clear")))["mode"] == "form"
    assert w.state.cards[CARD].waiting_for == "decision"


@pytest.mark.parametrize("change", ["right-removed", "setting-off", "owner-disabled", "revoked"])
def test_a_switch_turned_off_between_question_and_answer_refuses_the_decision(
    settings: Settings, change: str
) -> None:
    w = deciding(settings, "wait")
    state = asked(ask(w, "wait")).request_state
    laptop = w.registry.credentials["cred-1"]
    if change == "right-removed":
        w.registry.credentials["cred-1"] = laptop.__replace__(scopes=json.dumps(sorted(SCOPES)))
    elif change == "setting-off":
        w.settings.editor_decisions = False
    elif change == "owner-disabled":
        owner = w.registry.actors[PERSON]
        w.registry.actors[PERSON] = owner.__replace__(disabled_at="2026-11-26T11:59:00Z")
    else:
        w.registry.credentials["cred-1"] = laptop.__replace__(revoked_at="2026-11-26T11:59:00Z")
    with pytest.raises(Forbidden) as refused:
        answer_with(w, "wait", state, "clear")
    assert refused.value.code == "human_action_required"
    reason = {
        "right-removed": "no_right",
        "setting-off": "editor_decisions_off",
        "owner-disabled": "owner_disabled",
        "revoked": "no_right",
    }[change]
    assert refused.value.details == {"action": "Deciding in the editor", "reason": reason}
    assert w.state.cards[CARD].waiting_for == "decision"
    assert w.state.comments == {}


def test_a_key_whose_right_was_taken_after_authentication_is_refused_on_the_answer(
    settings: Settings,
) -> None:
    w = deciding(settings, "confirmation")
    state = asked(ask(w, "confirmation")).request_state
    # The key now authenticates without the right: the answer is no longer the person's.
    with pytest.raises(Forbidden):
        answer_with(w, "confirmation", state, "confirm", key=KEY)
    assert w.state.cards[CARD].human_confirmed_at is None


def test_a_decision_someone_took_in_tralala_meanwhile_is_reported(settings: Settings) -> None:
    w = deciding(settings, "wait")
    state = asked(ask(w, "wait")).request_state
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(waiting_for="nothing")
    reply = complete(answer_with(w, "wait", state, "clear"))
    assert reply["status"] == "not_pending"
    assert w.state.comments == {}
