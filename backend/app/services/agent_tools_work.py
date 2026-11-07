"""``set_ticket_wait``: a worker says what a Ticket waits for, with a reason.

A worker that reads a Ticket and cannot go on without an answer sets a wait: a ``decision``,
``information``, ``access`` (a system, key, account, setting or machine) or a ``third_party``, and
in a sentence or two what is needed ("I need this answered"). The Ticket's state follows on every
read: it needs input (a decision, information or access) or is blocked (a third party), and
``list_tickets`` with ``needs_person`` lists it for the person who answers.

Setting a wait describes the Ticket and assigns nothing. Clearing one, or replacing one with
another, is a person's act (AGENTS.md rule 11a), so it is never a tool: the person who answers
clears it in the Ticket dialog. The write is ``TicketWorkService.set_wait``, version-checked with
the version read for the worker and one retry when someone else changed the Ticket in between.

The handler is public and typed on the attributes of the composition root it uses, so a unit test
runs it with the real services on the typed fakes. Its catalogue entry is built here too
(``work_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import ValidationError

from ..core.context import ActorContext
from ..core.errors import ValidationFailure, VersionConflict
from ..schemas.cards import WAITING_REASON_CHARS, WAITS, TicketWaitSet
from .agent_tools_read import ToolArguments, ToolResult, _require
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardService
    from .ticket_work import TicketWorkService


class WaitSetting(Protocol):
    """What ``set_ticket_wait`` uses of the composition root."""

    @property
    def card(self) -> CardService: ...

    @property
    def ticket_work(self) -> TicketWorkService: ...


def _payload(version: int, args: ToolArguments) -> TicketWaitSet:
    waiting_for = _require(args, "waiting_for")
    if waiting_for not in WAITS:
        raise ValidationFailure(
            "waiting_for must be one of " + ", ".join(WAITS),
            details={"argument": "waiting_for", "choices": list(WAITS)},
        )
    try:
        return TicketWaitSet.model_validate(
            {"version": version, "waiting_for": waiting_for, "reason": _require(args, "reason")}
        )
    except ValidationError as error:
        raise ValidationFailure(
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()),
            details={"argument": "reason", "maximum": WAITING_REASON_CHARS},
        ) from None


def set_ticket_wait(services: WaitSetting, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("cards:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    for attempt in range(2):
        loop_id, card = services.card.locate(board_id, card_id)
        payload = _payload(card["version"], args)
        try:
            written = services.ticket_work.set_wait(actor, board_id, loop_id, card_id, payload)
        except VersionConflict:
            if attempt:
                raise
            continue
        return {
            "ticket": {
                "id": written["id"],
                "key": written["ticket_key"],
                "state": written["state"],
                "version": written["version"],
            },
            "wait": {
                "waiting_for": written["waiting_for"],
                "reason": written["waiting_reason"],
                "set_by": written["waiting_set_by"],
                "set_at": written["waiting_set_at"],
            },
            "next_step": (
                "A person answers and clears the wait in the Ticket dialog; list_tickets with "
                "needs_person true lists what waits for a person."
            ),
        }
    raise AssertionError("unreachable: the second attempt returns or raises")


def work_tools(board_id: ArgumentSchema, card_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entry of setting a Ticket's wait."""
    return [
        AgentTool(
            name="set_ticket_wait",
            description=(
                "Say what a Ticket waits for before work can go on, with the reason: a decision, "
                "information, access (a system, key, account, setting or machine) or a "
                "third_party. The Ticket then needs input (or is blocked, for a third party) "
                "until a person clears the wait; clearing or replacing a wait is a person's act. "
                "Only on an open Ticket that waits for nothing; the version is read for you."
            ),
            scopes=("cards:write",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "card_id": card_id,
                    "waiting_for": string_argument("One of: " + ", ".join(WAITS)),
                    "reason": string_argument(
                        f"What is needed, in a sentence or two (at most {WAITING_REASON_CHARS} "
                        "characters)"
                    ),
                },
                required=["board_id", "card_id", "waiting_for", "reason"],
            ),
            handler=set_ticket_wait,
        ),
    ]


__all__ = ["WaitSetting", "set_ticket_wait", "work_tools"]
