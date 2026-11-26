"""``ask_person`` in the mode ``form``: the person decides in the editor, as themselves.

This is the opt-in of AGENTS.md rule 11a. ``ask_person`` (``agent_tools_decisions``) offers the
question as a form only when all of these hold on the call that asks:

- the client declared the elicitation mode ``form`` (MCP 2026-07-28; a call of 2025-06-18 brings
  no modes, so it is never asked so);
- the installation's setting ``editor_decisions`` is on;
- the key holds the right ``loops:decide``, which only its owner gives it;
- the decision is one of the five in ``FORM_DECISIONS``: approving the analysis or the RoadMap,
  clearing a wait, confirming a person's task, accepting the implementation of a Loop with a plan.
  QA, a reset, closing or cancelling a Loop, and the implementation of a Loop without a plan
  (accepting it closes the Loop) are never offered as a form; they keep the link.

The form (``form_request``) is the flat object the specification's page client/elicitation allows:
an enum ``decision`` with a title per choice, and an optional ``feedback`` text with ``maxLength``.
No field carries an address, and the message names the Loop's key, the Ticket's key and the
revision number it is about, in plain English.

The answer comes from the client, so Tralala cannot know that a person gave it; it is taken as the
person's only on the call that brings it (``agent_tools_decisions._form_retry``): the state is
opened and used up first, then ``AuthService.editor_decision_actor`` checks the setting, the right
on the key and the owner's account again and builds the owner's context, the content is checked
against the form, and the revision, the Ticket's version or the Loop's version the question was
about must still be the one in force. The decision then runs through the same service methods as
REST, as the owner, marked ``taken_through`` the key in its history (``decision_requests``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, Literal

from pydantic import JsonValue

from ..core.context import DECIDE_SCOPE, ActorContext
from .decision_outcomes import AskedDecision

if TYPE_CHECKING:
    from ..core.config import Settings

FormDecision = Literal["analysis", "roadmap", "wait", "confirmation", "implementation"]
FORM_DECISIONS: Final[tuple[FormDecision, ...]] = (
    "analysis",
    "roadmap",
    "wait",
    "confirmation",
    "implementation",
)
# The key of the form's choice and of its optional text.
CHOICE: Final = "decision"
FEEDBACK: Final = "feedback"
# The longest feedback a form takes: the shortest field it may go into (a confirmation's note).
FEEDBACK_MAX: Final = 500

# Per decision: the choice that takes it, and the one that leaves it as it is (for a review, asks
# for changes), each with its title.
_CHOICES: Final[dict[FormDecision, tuple[tuple[str, str], tuple[str, str]]]] = {
    "analysis": (("approve", "Approve"), ("request_changes", "Ask for changes")),
    "roadmap": (("approve", "Approve"), ("request_changes", "Ask for changes")),
    "wait": (("clear", "Clear the wait"), ("keep", "Keep the wait")),
    "confirmation": (("confirm", "Confirm it is done"), ("not_yet", "Not done yet")),
    "implementation": (("accept", "Accept the implementation"), ("reject", "Do not accept yet")),
}
_QUESTIONS: Final[dict[FormDecision, str]] = {
    "analysis": "Approve revision {revision} of the analysis of {loop}, or ask for changes.",
    "roadmap": "Approve revision {revision} of the RoadMap of {loop}, or ask for changes.",
    "wait": "Clear the wait on {ticket} in {loop}, or keep it.",
    "confirmation": "Confirm that the person's task {ticket} in {loop} is done, or not yet.",
    "implementation": "Accept the implementation of {loop} and hand it to its QA, or not yet.",
}
FORM_NOTE: Final = (
    "Only you answer this; the agent never fills it in. Your answer is your decision in "
    "Tralala, recorded as taken in a coding session through this key."
)
# The tool's rule in one sentence: the description, the MCP instructions and /llms.txt say it.
FORM_RULE: Final = (
    "With the installation's setting editor_decisions on, the right loops:decide on the key and "
    "the mode form declared, the analysis, the RoadMap, a wait, a person's task and the "
    "implementation are asked as a form that the person answers in their editor; an agent never "
    "fills it in, and QA, a reset and closing a Loop always keep the link."
)


def form_decision(decision: AskedDecision) -> FormDecision | None:
    """The decision as one the form may take, or None for QA."""
    for allowed in FORM_DECISIONS:
        if decision == allowed:
            return allowed
    return None


def offers_form(
    settings: Settings,
    actor: ActorContext,
    decision: AskedDecision,
    *,
    declared: bool,
    without_plan: bool,
) -> bool:
    """Whether this call is asked in the mode ``form``: the client declared it, the setting is
    on, the key holds the right, and the decision is one of the five (the implementation only of
    a Loop with a plan)."""
    if not (declared and settings.editor_decisions and actor.credential_id is not None):
        return False
    if not actor.has_scope(DECIDE_SCOPE):
        return False
    allowed = form_decision(decision)
    return allowed is not None and not (allowed == "implementation" and without_plan)


def form_message(
    decision: FormDecision, loop_key: str, ticket_key: str | None, revision: int | None
) -> str:
    """The plain English the client shows its person: the Loop's and the Ticket's keys and the
    revision number, never an id or an address."""
    question = _QUESTIONS[decision].format(
        loop=loop_key, ticket=ticket_key or "the Ticket", revision=revision or "the current"
    )
    return f"{question} {FORM_NOTE}"


def form_schema(decision: FormDecision) -> dict[str, JsonValue]:
    """The ``requestedSchema``: a flat object with the enum ``decision`` and the text
    ``feedback``."""
    (take_value, take_title), (keep_value, keep_title) = _CHOICES[decision]
    return {
        "type": "object",
        "properties": {
            CHOICE: {
                "type": "string",
                "title": "Your decision",
                "oneOf": [
                    {"const": take_value, "title": take_title},
                    {"const": keep_value, "title": keep_title},
                ],
            },
            FEEDBACK: {
                "type": "string",
                "title": "Feedback",
                "description": "Optional: what you want changed or want the agent to know.",
                "maxLength": FEEDBACK_MAX,
            },
        },
        "required": [CHOICE],
    }


def form_request(
    decision: FormDecision, loop_key: str, ticket_key: str | None, revision: int | None
) -> dict[str, JsonValue]:
    """The ``elicitation/create`` request in the mode ``form``."""
    return {
        "method": "elicitation/create",
        "params": {
            "mode": "form",
            "message": form_message(decision, loop_key, ticket_key, revision),
            "requestedSchema": form_schema(decision),
        },
    }


Answer = tuple[bool, str]
"""What the person chose: True to take the decision (for a review: to approve), and the
feedback."""


def read_answer(decision: FormDecision, content: JsonValue) -> Answer | None:
    """The content checked against the form: exactly the choice, and the feedback when given, of
    the right type and length; None for anything else."""
    if not isinstance(content, dict):
        return None
    if set(content) - {CHOICE, FEEDBACK}:
        return None
    choice = content.get(CHOICE)
    feedback = content.get(FEEDBACK, "")
    if not isinstance(feedback, str) or len(feedback) > FEEDBACK_MAX:
        return None
    (take_value, _), (keep_value, _) = _CHOICES[decision]
    if choice == take_value:
        return True, feedback
    if choice == keep_value:
        return False, feedback
    return None


def answered_content(responses: Mapping[str, Mapping[str, JsonValue]], key: str) -> JsonValue:
    """The ``content`` of the answer to the request ``key``, or None."""
    answer = responses.get(key)
    return None if answer is None else answer.get("content")


def no_decision(decision: FormDecision, taken: bool) -> bool:
    """Whether the answer leaves the decision as it is: keeping a wait, a task not done yet, an
    implementation not accepted yet. Asking for changes to a review is a decision."""
    return not taken and decision not in ("analysis", "roadmap")


def revision_ids(subject: Mapping[str, JsonValue]) -> dict[str, str]:
    """The revisions a review question was about, as the review binds to them."""
    revisions = subject.get("revisions")
    if not isinstance(revisions, dict):
        return {}
    return {kind: value for kind, value in revisions.items() if isinstance(value, str)}


__all__ = [
    "CHOICE",
    "FEEDBACK",
    "FEEDBACK_MAX",
    "FORM_DECISIONS",
    "FORM_NOTE",
    "FORM_RULE",
    "Answer",
    "FormDecision",
    "answered_content",
    "form_decision",
    "form_message",
    "form_request",
    "form_schema",
    "no_decision",
    "offers_form",
    "read_answer",
    "revision_ids",
]

