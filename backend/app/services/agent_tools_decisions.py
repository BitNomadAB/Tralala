"""``ask_person``: a key asks its person for one decision, and later learns what they decided.

The decisions are the ones AGENTS.md rule 11a reserves for a person and that a coding session
waits for: approving the analysis or the RoadMap under review, clearing a Ticket's wait,
confirming a person's task, accepting the implementation and accepting or rejecting QA. The tool
only points at the decision and reports it; it never takes one. The person decides in Tralala,
signed in, on the page the decision's address opens (``decision_links``), exactly as without the
tool.

How the tool answers depends on what the client can be asked:

- the decision does not wait for a person: ``complete`` with ``status`` ``not_pending`` and why;
- it waits, the client declared the elicitation mode ``url`` (MCP 2026-07-28) and the installation
  has its public address (``Settings.public_url``): ``input_required``, with one request under
  ``decision`` (``elicitation/create`` in mode ``url``, an English message naming the Loop, the
  decision and the Ticket, and the absolute address of the decision, which carries only ids) and a
  sealed ``requestState`` (``RequestStateService``);
- it waits and the client cannot be asked so (no ``url`` mode, a client of 2025-06-18, or no public
  address, since a path is no URL for that mode): ``complete`` with ``status``
  ``waiting_for_person``, ``decision_link`` and the advice to call again later. The mode ``form`` is
  never used, whatever the client declared.

The client repeats the call with ``inputResponses`` and the state. The state is opened first, for
the same key and the same call, once; a state the service refuses ends the call there (the
transport answers JSON-RPC -32602 and nothing about the decision). Then:

- ``decline`` or ``cancel``: ``complete`` with ``status`` ``declined`` or ``cancelled``; the
  decision stays open in Tralala;
- ``accept`` (in mode ``url`` it only means the person agreed to open the address), or no answer:
  when the person took the decision the question was about, ``complete`` with ``status``
  ``decided``, the ``outcome``, who decided and when (``DecisionOutcomeService``); while it still
  waits, ``input_required`` again with a new state (the old one is used up). When what the question
  was about has changed under it (another revision under review, another wait), the state is
  refused as ``wrong_call``, so the key asks again without it; when nothing waits any more,
  ``not_pending``.

Each key asks for itself: a person may hold any number of keys, and two keys asking about one
decision each get a state of their own; who decided is the person, whichever key asks.

The handler is public and typed on the attributes of the composition root it uses, so a unit test
runs it with the real services on the typed fakes. ``ask_person`` is the catalogue handler for a
caller that can be asked nothing; ``ask_person_with_input`` is the one the transport of MCP
2026-07-28 runs with the call's ``ToolInput``. The catalogue entry is built here too
(``decision_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import ValidationFailure
from ..core.identifiers import canonical_board_id
from .agent_tools_loops import next_decision, next_step, ticket_counts
from .agent_tools_read import ToolArguments, ToolResult, _require, _text, tool_decision_link
from .agent_tools_schema import (
    NO_INPUT,
    AgentTool,
    ArgumentSchema,
    InputRequired,
    ToolInput,
    object_schema,
    string_argument,
)
from .decision_outcomes import ASKED_DECISIONS, TICKET_DECISIONS, AskedDecision, DecisionTaken
from .loop_documents_review import ANALYSIS_SCOPE_KINDS, ROADMAP_SCOPE_KINDS
from .request_state import OpenedState, PendingCall, RequestStateRefused

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from ..core.config import Settings
    from .cards import CardEntry, CardService
    from .decision_outcomes import DecisionOutcomeService
    from .decision_requests import DecisionRequestService
    from .loops import LoopEntry, LoopService
    from .request_state import RequestStateService

ASK_PERSON: Final = "ask_person"
# The key of the one input request the tool sends, and of the answer it reads back.
REQUEST_KEY: Final = "decision"

# What each decision is called in a sentence.
_NAMES: Final[dict[AskedDecision, str]] = {
    "analysis": "analysis",
    "roadmap": "RoadMap",
    "wait": "wait",
    "confirmation": "confirmation",
    "implementation": "implementation",
    "qa": "QA",
}
# The English message the client shows its person, by decision.
_MESSAGES: Final[dict[AskedDecision, str]] = {
    "analysis": "Open Tralala to approve the analysis of {loop} or ask for changes.",
    "roadmap": "Open Tralala to approve the RoadMap of {loop} or ask for changes.",
    "wait": "Open Tralala to answer and clear the wait on {ticket} in {loop}.",
    "confirmation": "Open Tralala to confirm that the person's task {ticket} in {loop} is done.",
    "implementation": "Open Tralala to accept the implementation of {loop}.",
    "qa": "Open Tralala to accept or reject the QA of {loop}.",
}
# The tool in one sentence: the MCP instructions give it in these words.
ASK_PERSON_RULE: Final = (
    "ask_person asks your person for such a decision and later says what they decided; the "
    "person takes it in Tralala, never the tool."
)
CALL_AGAIN: Final = (
    "A person takes this decision in Tralala at decision_link; call ask_person again later to "
    "learn what they decided."
)
STILL_OPEN: Final = (
    "The decision is still open in Tralala at decision_link; ask again only when your person "
    "wants to take it."
)


class DecisionAsking(Protocol):
    """What ``ask_person`` uses of the composition root."""

    @property
    def loop(self) -> LoopService: ...

    @property
    def card(self) -> CardService: ...

    @property
    def decision_outcome(self) -> DecisionOutcomeService: ...

    @property
    def decision_request(self) -> DecisionRequestService: ...

    @property
    def request_state(self) -> RequestStateService: ...

    @property
    def settings(self) -> Settings: ...


@dataclass(frozen=True, slots=True)
class _Request:
    """The call's arguments, checked: the board's canonical id and the decision asked about."""

    board_id: str
    loop_id: str
    decision: AskedDecision
    card_id: str | None


@dataclass(frozen=True, slots=True)
class _Situation:
    """Where the decision stands now: the Loop's and the Ticket's ids and keys, whether it waits
    for a person, why not, and what it is about (its ``subject``) while it waits."""

    loop_id: str
    loop_key: str
    card_id: str | None
    ticket_key: str | None
    pending: bool
    why: str = ""
    subject: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])


def _decision(args: ToolArguments) -> AskedDecision:
    value = _require(args, "decision")
    for decision in ASKED_DECISIONS:
        if value == decision:
            return decision
    raise ValidationFailure(
        "decision must be one of " + ", ".join(ASKED_DECISIONS),
        details={"argument": "decision", "allowed": list(ASKED_DECISIONS)},
    )


def _request(args: ToolArguments) -> _Request:
    board_id = canonical_board_id(_require(args, "board_id"))
    loop_id = _require(args, "loop_id")
    decision = _decision(args)
    card_id = _text(args.get("card_id"))
    if decision in TICKET_DECISIONS and card_id is None:
        raise ValidationFailure(
            f"A {decision} is taken on a Ticket: card_id is required",
            details={"argument": "card_id"},
        )
    if decision not in TICKET_DECISIONS and card_id is not None:
        raise ValidationFailure(
            f"The {_NAMES[decision]} is taken on the Loop: it takes no card_id",
            details={"argument": "card_id"},
        )
    return _Request(board_id, loop_id, decision, card_id)


def _read_only(entry: LoopEntry) -> str | None:
    """How a read-only Loop is closed (completed, cancelled or archived), else None."""
    if entry["completed_at"] is not None or entry["stage"] == "completed":
        return "completed"
    if entry["cancelled_at"] is not None or entry["stage"] == "cancelled":
        return "cancelled"
    if entry["archived_at"] is not None:
        return "archived"
    return None


def _revisions(entry: LoopEntry, kinds: tuple[str, ...]) -> dict[str, JsonValue]:
    """The current revision of every document a review of the scope binds to."""
    revisions: dict[str, JsonValue] = {}
    for kind in kinds:
        current = entry["documents"][kind]["current"]
        revisions[kind] = None if current is None else current["id"]
    return revisions


def _loop_situation(services: DecisionAsking, request: _Request, entry: LoopEntry) -> _Situation:
    """A decision taken on the Loop: pending while it is the Loop's next decision."""
    key = entry["key"]
    name = _NAMES[request.decision]
    readiness = services.loop.readiness(request.board_id, entry["id"])
    counts = ticket_counts(readiness)
    if next_decision(entry, readiness, counts) != request.decision:
        sentence, _ = next_step(entry, readiness, counts)
        why = f"The {name} of {key} does not wait for a person now. {sentence}"
        return _Situation(entry["id"], key, None, None, False, why)
    subject: dict[str, JsonValue] = {}
    if request.decision == "analysis":
        subject = {"revisions": _revisions(entry, ANALYSIS_SCOPE_KINDS)}
    elif request.decision == "roadmap":
        subject = {"revisions": _revisions(entry, ROADMAP_SCOPE_KINDS)}
    elif request.decision == "qa":
        subject = {"cycle_id": entry["active_qa_cycle_id"]}
    return _Situation(entry["id"], key, None, None, True, subject=subject)


def _ticket_why(decision: AskedDecision, card: CardEntry, label: str) -> str | None:
    """Why a decision on the Ticket does not wait for a person, or None while it does."""
    if card["completed_at"] is not None:
        return f"{label} is completed: nothing on it waits for a person."
    if card["archived_at"] is not None:
        return f"{label} is archived: nothing on it waits for a person."
    if decision == "wait":
        return None if card["waiting_for"] != "nothing" else f"{label} waits for nothing."
    if card["human_confirmed_at"] is not None:
        return f"{label} is already confirmed."
    if card["human_action_required"]:
        return None
    return f"{label} is not a person's task."


def _ticket_situation(
    services: DecisionAsking, request: _Request, entry: LoopEntry, card_id: str
) -> _Situation:
    """A decision taken on a Ticket: its wait while it waits, its confirmation while it is a
    person's task."""
    card = services.card.get(request.board_id, entry["id"], card_id)
    ticket_key = card["ticket_key"]
    label = f"Ticket {ticket_key}" if ticket_key else "The Ticket"
    why = _ticket_why(request.decision, card, label)
    if why is not None:
        return _Situation(entry["id"], entry["key"], card["id"], ticket_key, False, why)
    subject: dict[str, JsonValue] = {}
    if request.decision == "wait":
        subject = {"waiting_for": card["waiting_for"], "waiting_set_at": card["waiting_set_at"]}
    return _Situation(entry["id"], entry["key"], card["id"], ticket_key, True, subject=subject)


def _situation(services: DecisionAsking, request: _Request) -> _Situation:
    entry = services.loop.get(request.board_id, request.loop_id)
    closed = _read_only(entry)
    if closed is not None:
        why = (
            f"The Loop {entry['key']} is {closed} and read-only: nothing in it waits for a person."
        )
        return _Situation(entry["id"], entry["key"], request.card_id, None, False, why)
    if request.card_id is None:
        return _loop_situation(services, request, entry)
    return _ticket_situation(services, request, entry, request.card_id)


def _call(request: _Request, situation: _Situation) -> PendingCall:
    """The call a state belongs to, by the ids the services read: the same however the key wrote
    them."""
    return PendingCall(
        ASK_PERSON,
        {
            "board_id": request.board_id,
            "loop_id": situation.loop_id,
            "decision": request.decision,
            "card_id": situation.card_id,
        },
    )


def _about(request: _Request, situation: _Situation) -> ToolResult:
    """What every answer says about the decision it is about."""
    return {
        "decision": request.decision,
        "loop_key": situation.loop_key,
        "ticket_key": situation.ticket_key,
    }


def _link(services: DecisionAsking, request: _Request, situation: _Situation) -> str:
    return tool_decision_link(
        request.decision,
        board_id=request.board_id,
        loop_id=situation.loop_id,
        card_id=situation.card_id,
        public_url=services.settings.public_url,
    )


def ask_message(decision: AskedDecision, loop_key: str, ticket_key: str | None) -> str:
    """The English sentence the client shows its person: the Loop, the decision, the Ticket."""
    return _MESSAGES[decision].format(loop=loop_key, ticket=ticket_key or "the Ticket")


def _ask(
    services: DecisionAsking,
    actor: ActorContext,
    request: _Request,
    situation: _Situation,
    given: ToolInput,
) -> ToolResult | InputRequired:
    """The decision waits: ask in mode ``url`` when the client can be asked so and the address
    is absolute, else answer with the address as text."""
    link = _link(services, request, situation)
    message = ask_message(request.decision, situation.loop_key, situation.ticket_key)
    # The board records the question once while it is open (decision_requests), so the decision
    # that answers it names this key.
    services.decision_request.asked(
        actor, request.board_id, situation.loop_id, request.decision, situation.card_id
    )
    if given.url and services.settings.public_url:
        state = services.request_state.seal(actor, _call(request, situation), situation.subject)
        return InputRequired(
            {
                REQUEST_KEY: {
                    "method": "elicitation/create",
                    "params": {"mode": "url", "message": message, "url": link},
                }
            },
            state,
        )
    return {
        "status": "waiting_for_person",
        **_about(request, situation),
        "decision_link": link,
        "message": message,
        "next_step": CALL_AGAIN,
    }


def _not_pending(request: _Request, situation: _Situation) -> ToolResult:
    return {"status": "not_pending", **_about(request, situation), "why": situation.why}


def _decided(request: _Request, situation: _Situation, taken: DecisionTaken) -> ToolResult:
    return {
        "status": "decided",
        **_about(request, situation),
        "outcome": taken["outcome"],
        "decided_by": taken["decided_by"],
        "decided_by_id": taken["decided_by_id"],
        "decided_at": taken["decided_at"],
    }


def _action(responses: Mapping[str, Mapping[str, JsonValue]]) -> str | None:
    """The person's action on the request, when the client answered it."""
    answer = responses.get(REQUEST_KEY)
    action = None if answer is None else answer.get("action")
    return action if isinstance(action, str) else None


def _retry(
    services: DecisionAsking,
    actor: ActorContext,
    request: _Request,
    situation: _Situation,
    opened: OpenedState,
    given: ToolInput,
) -> ToolResult | InputRequired:
    """The call repeated with a state that opened: the person's answer, then the decision."""
    action = _action(given.responses)
    if action in ("decline", "cancel"):
        status = "declined" if action == "decline" else "cancelled"
        # The person turned the question down: a later decision does not answer it.
        services.decision_request.withdrawn(
            actor, request.board_id, situation.loop_id, request.decision, situation.card_id, status
        )
        return {
            "status": status,
            **_about(request, situation),
            "decision_link": _link(services, request, situation),
            "next_step": STILL_OPEN,
        }
    taken = services.decision_outcome.taken(
        request.board_id,
        situation.loop_id,
        request.decision,
        card_id=situation.card_id,
        subject=opened.subject,
        since=iso_utc(opened.issued_at),
    )
    if taken is not None:
        return _decided(request, situation, taken)
    if situation.pending and situation.subject == dict(opened.subject):
        return _ask(services, actor, request, situation, given)
    if situation.pending:
        # The question was about a revision or a wait that is no longer the one that waits.
        raise RequestStateRefused("wrong_call")
    return _not_pending(request, situation)


def ask_person_with_input(
    services: DecisionAsking, actor: ActorContext, args: ToolArguments, given: ToolInput
) -> ToolResult | InputRequired:
    """Ask the person for one decision, or say what became of it; ``given`` is what the client
    brought (its modes, its answers and the state)."""
    actor.require("loops:read")
    actor.require("cards:read")
    request = _request(args)
    situation = _situation(services, request)
    if given.request_state is not None:
        opened = services.request_state.open(actor, _call(request, situation), given.request_state)
        return _retry(services, actor, request, situation, opened, given)
    if not situation.pending:
        return _not_pending(request, situation)
    return _ask(services, actor, request, situation, given)


def ask_person(services: DecisionAsking, actor: ActorContext, args: ToolArguments) -> ToolResult:
    """``ask_person`` for a caller that can be asked nothing: the decision's address as text."""
    answer = ask_person_with_input(services, actor, args, NO_INPUT)
    if isinstance(answer, InputRequired):  # pragma: no cover - NO_INPUT declares no mode
        raise TypeError("a call that declares no elicitation mode is never asked")
    return answer


def decision_tools(board_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entry of asking a person for a decision."""
    return [
        AgentTool(
            name=ASK_PERSON,
            description=(
                "Ask your person for a decision only a person takes, and later learn what they "
                "decided: the analysis or RoadMap under review, a Ticket's wait to clear, a "
                "person's task to confirm, the implementation to accept, or QA. The tool never "
                "takes the decision; the person takes it in Tralala, signed in. A client that "
                "declared the elicitation mode url gets the question as input_required with the "
                "decision's address; any other gets status waiting_for_person with "
                "decision_link. Call again (with the requestState and inputResponses when you "
                "were asked) to get status decided with the outcome, who decided and when."
            ),
            scopes=("loops:read", "cards:read"),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "loop_id": string_argument("Loop identifier from read_board"),
                    "decision": string_argument(
                        "analysis, roadmap, wait, confirmation, implementation or qa"
                    ),
                    "card_id": string_argument(
                        "The Ticket, for wait and confirmation only: an identifier from "
                        "list_tickets or search_tickets"
                    ),
                },
                required=["board_id", "loop_id", "decision"],
            ),
            handler=ask_person,
            asks=ask_person_with_input,
        )
    ]


__all__ = [
    "ASK_PERSON",
    "ASK_PERSON_RULE",
    "CALL_AGAIN",
    "REQUEST_KEY",
    "STILL_OPEN",
    "DecisionAsking",
    "ask_message",
    "ask_person",
    "ask_person_with_input",
    "decision_tools",
]
