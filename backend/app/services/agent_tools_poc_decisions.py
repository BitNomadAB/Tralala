"""The worker tools for what stands in the way of work: a POC decision, something missing from a
person, and the list of both a person answered.

An obstacle is one of three kinds, and only the last stops work (``OBSTACLE_RULE``). A choice that
can be changed afterwards is a POC decision: the worker takes the one good practice points to,
records it with ``record_poc_decision`` and goes on. Something only a person can provide (an API
key, an account, access, a file, a fact) is reported with ``report_missing`` while the work goes
around it. A real stop is only what the Loop's stop list names, and that is a wait on a Ticket
(``set_ticket_wait`` with ``stop``). Neither record blocks anything; a signed-in person answers
each one afterwards with OK or with feedback that becomes a new Ticket, and
``list_poc_decisions`` shows the worker those answers. Answering is a person's act (AGENTS.md rule
11a) and never a tool.

``report_missing`` takes its fields under the names a worker thinks in (``went_around``,
``when_provided``) and stores them as the record's ``chosen`` and ``change_path``; a refusal
(``422 poc_decision_invalid``) names the fields as the tool took them (``refusal_for``), and the
list answers a missing record under the same names (``listed_item``), so a worker reads back what
it wrote. The record's rules are the service's (``poc_decision_rules``); nothing here judges text.

Each handler is public and typed on the attributes of the composition root it uses
(``PocRecording``), so a unit test runs it with the real service on the typed fakes. Their
catalogue entries are built here too (``poc_decision_tools``) and placed by
``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, Protocol

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..schemas.poc_decisions import POC_STATUSES, PocDecisionCreate
from .agent_tools_discussions import validated
from .agent_tools_listing import loop_id_of
from .agent_tools_read import ToolArguments, ToolResult, _require, _text
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument
from .poc_decision_rules import (
    POC_DETAILS_MAX_CHARS,
    POC_TEXT_MAX_SENTENCES,
    POC_TITLE_MAX_CHARS,
    PocDecisionRefusal,
    PocProblem,
)

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .loops import LoopService
    from .poc_decisions import PocDecisionEntry, PocDecisionService

OBSTACLE_RULE: Final = (
    "What stands in your way is one of three kinds, and only the last stops you. A choice that "
    "can be changed afterwards (two reasonable solutions, a name, a default, a layout, an order "
    "of work, how to read an unclear requirement): take the one good practice points to, write it "
    "down with record_poc_decision and go on; your person reviews those decisions when there is a "
    "result to look at, and answers OK or gives feedback that becomes a new Ticket. Something only "
    "a person can provide (an API key, an account, access, a file, a fact about their business): "
    "go around it, say so with report_missing and go on with everything that does not need it. A "
    "real stop is only what the Loop's stop list names (read_loop gives the list; a person writes "
    "it, and you never decide that something else is a stop): then set_ticket_wait with that line "
    "in stop, and work on other Tickets meanwhile. An obstacle that is not on the stop list is "
    "never a reason to wait or to ask first."
)
"""The three kinds of obstacle as the MCP instructions give them, word for word."""

CONFIRMATION_RULE: Final = (
    "A Ticket held up only by a person's confirmation of earlier work is ready: do it and "
    "complete it, and it shows as done, awaiting confirmation."
)
"""What a worker does with a Ticket that only waits for a person's confirmation, in one
sentence: the MCP instructions and ``complete_ticket``'s description give it in these words."""

RECORDED_NEXT_STEP: Final = (
    "Go on with the work now: nothing waits for this. Your person reviews it when there is a "
    "result to look at, and list_poc_decisions shows the answer; feedback becomes a new Ticket."
)
DEDUPLICATED_NEXT_STEP: Final = (
    "The same open record was already there, so nothing new was stored. Go on with the work now: "
    "nothing waits for this."
)
REWRITE: Final = (
    "Rewrite each field details.fields names by its rule and send the record again at once; "
    "files, code, symbols and ids go in details."
)
NOTHING_PRIVATE: Final = "Never put a secret (a key, a password, a token) in any field."
_PLAIN: Final = (
    f"The text is for a person: plain, at most {POC_TEXT_MAX_SENTENCES} sentences a field, no "
    "file paths, code or ids; those go in details."
)

# report_missing's arguments under the record's field names, and back.
MISSING_ARGUMENTS: Final[Mapping[str, str]] = {
    "chosen": "went_around",
    "change_path": "when_provided",
}


class PocRecording(Protocol):
    """What the POC decision tools use of the composition root."""

    @property
    def poc_decisions(self) -> PocDecisionService: ...

    @property
    def loop(self) -> LoopService: ...


def refusal_for(refusal: PocDecisionRefusal, names: Mapping[str, str]) -> ValidationFailure:
    """``refusal`` as the tool answers it: each field under the argument the tool took it as
    (``names`` maps a record field to it), the same rules, and the message ending in how to fix
    it, so the worker rewrites the fields and sends the record again at once."""
    renamed = [
        PocProblem(
            names.get(problem.field, problem.field),
            problem.rule,
            names.get(problem.field, problem.field) + problem.message[len(problem.field) :],
        )
        for problem in refusal.problems
    ]
    shaped = PocDecisionRefusal(renamed)
    return ValidationFailure(
        f"{shaped.message} {REWRITE}", code=shaped.code, details=shaped.details
    )


def _field(args: ToolArguments, key: str) -> str:
    return _text(args.get(key)) or ""


def _record(
    services: PocRecording,
    actor: ActorContext,
    args: ToolArguments,
    fields: Mapping[str, object],
    names: Mapping[str, str],
) -> ToolResult:
    """Record ``fields`` (a kind and its texts) in the Loop ``args`` names, and answer what a
    worker needs to go on: the record's id and key and whether it was there already."""
    board_id = _require(args, "board_id")
    loop_id = loop_id_of(services, args)
    arguments = {field: names.get(field, field) for field in fields}
    payload = validated(PocDecisionCreate, fields, arguments)
    try:
        recorded = services.poc_decisions.record(actor, board_id, loop_id, payload)
    except PocDecisionRefusal as refusal:
        raise refusal_for(refusal, names) from None
    deduplicated = recorded["deduplicated"]
    return {
        "id": recorded["id"],
        "key": recorded["key"],
        "kind": recorded["kind"],
        "status": recorded["status"],
        "card_id": recorded["card_id"],
        "ticket_key": recorded["ticket_key"],
        "built_on": recorded["built_on"],
        "deduplicated": deduplicated,
        "next_step": DEDUPLICATED_NEXT_STEP if deduplicated else RECORDED_NEXT_STEP,
    }


def _card_id(args: ToolArguments) -> str | None:
    return _text(args.get("card_id"))


def record_poc_decision(
    services: PocRecording, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:write")
    fields: dict[str, object] = {
        "kind": "decision",
        "card_id": _card_id(args),
        "title": _field(args, "title"),
        "chosen": _field(args, "chosen"),
        "reason": _field(args, "reason"),
        "alternative": _field(args, "alternative"),
        "change_path": _field(args, "change_path"),
        "builds_on": _field(args, "builds_on"),
        "details": _field(args, "details"),
    }
    return _record(services, actor, args, fields, {})


def report_missing(services: PocRecording, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("cards:write")
    fields: dict[str, object] = {
        "kind": "missing",
        "card_id": _card_id(args),
        "title": _field(args, "title"),
        "missing": _field(args, "missing"),
        "reason": _field(args, "reason"),
        "chosen": _field(args, "went_around"),
        "change_path": _field(args, "when_provided"),
        "builds_on": _field(args, "builds_on"),
        "details": _field(args, "details"),
    }
    return _record(services, actor, args, fields, MISSING_ARGUMENTS)


def listed_item(entry: PocDecisionEntry, *, include_details: bool) -> ToolResult:
    """One record as ``list_poc_decisions`` answers it: a decision under the names
    ``record_poc_decision`` takes, something missing under the names ``report_missing`` takes,
    with the person's answer and the Ticket a feedback became. ``details`` only on request."""
    if entry["kind"] == "missing":
        texts: ToolResult = {
            "missing": entry["missing"],
            "reason": entry["reason"],
            "went_around": entry["chosen"],
            "when_provided": entry["change_path"],
        }
    else:
        texts = {
            "chosen": entry["chosen"],
            "reason": entry["reason"],
            "alternative": entry["alternative"],
            "change_path": entry["change_path"],
        }
    item: ToolResult = {
        "id": entry["id"],
        "key": entry["key"],
        "kind": entry["kind"],
        "title": entry["title"],
        **texts,
        "builds_on": entry["builds_on"],
        "card_id": entry["card_id"],
        "ticket_key": entry["ticket_key"],
        "status": entry["status"],
        "due": entry["due"],
        "feedback": entry["feedback"],
        "feedback_ticket": entry["feedback_ticket"],
        "answered_by": entry["answered_by_name"],
        "answered_at": entry["answered_at"],
        "created_by": entry["created_by"]["name"],
        "created_at": entry["created_at"],
        "has_details": entry["details"] != "",
    }
    if include_details:
        item["details"] = entry["details"]
    return item


def listed_next_step(items: list[ToolResult]) -> str:
    """What a worker does with what its person answered: a feedback Ticket is work like any
    other, an open record waits for nobody but the review."""
    if any(item["status"] == "feedback" for item in items):
        return (
            "Feedback became a new Ticket (feedback_ticket): read it with read_ticket and work it "
            "like any other. An OK needs nothing more; an open record waits only for your "
            "person's review, so go on with the work."
        )
    if any(item["status"] == "open" for item in items):
        return "Open records wait only for your person's review: go on with the work."
    return "Nothing here waits for anyone."


def list_poc_decisions(
    services: PocRecording, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:read")
    board_id = _require(args, "board_id")
    loop_id = loop_id_of(services, args)
    status = _text(args.get("status"))
    if status is not None and status not in POC_STATUSES:
        raise ValidationFailure(
            "status must be one of " + ", ".join(POC_STATUSES),
            details={"argument": "status", "choices": list(POC_STATUSES)},
        )
    found = services.poc_decisions.list(
        actor, board_id, loop_id, card_id=_card_id(args), status=status
    )
    include_details = args.get("include_details") is True
    items = [listed_item(entry, include_details=include_details) for entry in found["items"]]
    return {
        "loop_id": loop_id,
        "items": items,
        "counts": dict(found["counts"]),
        "next_step": listed_next_step(items),
    }


def poc_decision_tools(board_id: ArgumentSchema, loop_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entries of recording a POC decision, reporting something missing and
    listing both, in catalogue order."""
    taken_on = string_argument(
        "Optional Ticket identifier (from list_tickets) the record was taken on"
    )
    title = string_argument(
        f"What it is about in a few words, at most {POC_TITLE_MAX_CHARS} characters"
    )
    builds_on = string_argument(
        "Optional: what other work builds on it; empty when nothing does"
    )
    details = string_argument(
        f"Optional text for the AI: files, code, symbols, evidence (at most "
        f"{POC_DETAILS_MAX_CHARS} characters)"
    )
    return [
        AgentTool(
            name="record_poc_decision",
            description=(
                "Write down a POC decision: a choice you took yourself, so that work could go on, "
                "for a person to review afterwards. Use it whenever you would otherwise have "
                "asked or waited and the choice can be changed later; it never blocks anything "
                "and you go on working at once. Say what you chose, why, what the alternative was "
                "and how it is changed afterwards, and in builds_on what other work builds on it "
                "(empty when nothing does; decisions other work builds on are shown to the person "
                "first). " + _PLAIN + " The person answers OK or gives feedback, which becomes a "
                "new Ticket; list_poc_decisions shows the answers. A refusal "
                "(poc_decision_invalid) names each field and rule: rewrite and send it again."
            ),
            scopes=("cards:write",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "loop_id": loop_id,
                    "card_id": taken_on,
                    "title": title,
                    "chosen": string_argument("What you chose"),
                    "reason": string_argument("Why you chose it"),
                    "alternative": string_argument("The reasonable alternative you did not choose"),
                    "change_path": string_argument("How it is changed afterwards"),
                    "builds_on": builds_on,
                    "details": details,
                },
                required=[
                    "board_id",
                    "loop_id",
                    "title",
                    "chosen",
                    "reason",
                    "alternative",
                    "change_path",
                ],
            ),
            handler=record_poc_decision,
        ),
        AgentTool(
            name="report_missing",
            description=(
                "Say that something only a person can provide is missing (an API key, an "
                "account, access, a file, a fact) and how the work goes around it. It never "
                "blocks: go on with everything that does not need it. Say what is missing, why it "
                "is needed, how you went around it and what is done once it is there. "
                + NOTHING_PRIVATE
                + " It is listed for the person beside the POC decisions. "
                + _PLAIN
            ),
            scopes=("cards:write",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "loop_id": loop_id,
                    "card_id": taken_on,
                    "title": title,
                    "missing": string_argument("What a person has to provide"),
                    "reason": string_argument("Why it is needed"),
                    "went_around": string_argument("How the work goes around it meanwhile"),
                    "when_provided": string_argument("What is done once it is there"),
                    "builds_on": builds_on,
                    "details": details,
                },
                required=[
                    "board_id",
                    "loop_id",
                    "title",
                    "missing",
                    "reason",
                    "went_around",
                    "when_provided",
                ],
            ),
            handler=report_missing,
        ),
        AgentTool(
            name="list_poc_decisions",
            description=(
                "List a Loop's POC decisions and what is missing from a person, in the order a "
                "person reviews them (open ones other work builds on first, then what is missing, "
                "then the other open ones, then the answered ones), each with its status (open, "
                "ok or feedback), the person's feedback and the Ticket it became, and the counts. "
                "Read it to see what your person answered: work a feedback Ticket like any other."
            ),
            scopes=("cards:read",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "loop_id": loop_id,
                    "card_id": string_argument("Optional: only the records taken on this Ticket"),
                    "status": string_argument("Optional: open, ok or feedback; all unless given"),
                    "include_details": {
                        "type": "boolean",
                        "description": "Also return each record's details; defaults to false",
                    },
                },
                required=["board_id", "loop_id"],
            ),
            handler=list_poc_decisions,
        ),
    ]


__all__ = [
    "CONFIRMATION_RULE",
    "DEDUPLICATED_NEXT_STEP",
    "MISSING_ARGUMENTS",
    "NOTHING_PRIVATE",
    "OBSTACLE_RULE",
    "RECORDED_NEXT_STEP",
    "REWRITE",
    "PocRecording",
    "list_poc_decisions",
    "listed_item",
    "listed_next_step",
    "poc_decision_tools",
    "record_poc_decision",
    "refusal_for",
    "report_missing",
]
