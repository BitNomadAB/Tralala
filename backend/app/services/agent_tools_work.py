"""``set_ticket_wait``: a worker stops a Ticket for a real stop, with a reason.

Only what the Loop's stop list names stops work (``loop_stops``): a choice that can be changed
afterwards is a POC decision and something missing from a person is reported as missing
(``agent_tools_poc_decisions``), and neither waits. For a real stop the worker sets a wait: a
``decision``, ``information``, ``access`` (a system, key, account, setting or machine) or a
``third_party``, in a sentence or two what is needed, and in ``stop`` the line of the stop list it
falls under, by its text or its number. A wait without ``stop`` works exactly as it always did. A
``stop`` the list does not name is refused (``422 not_a_stop``) with the list and the tools to use
instead (``not_a_stop_refusal``). The Ticket's state follows on every read: it needs input (a
decision, information or access) or is blocked (a third party), and ``list_tickets`` with
``needs_person`` lists it for the person who answers.

Setting a wait describes the Ticket and assigns nothing. Clearing one, or replacing one with
another, is a person's act (AGENTS.md rule 11a), so it is never a tool: the person who answers
clears it in the Ticket dialog. The write is ``TicketWorkService.set_wait``, version-checked with
the version read for the worker and one retry when someone else changed the Ticket in between. A
token that would replace a wait is refused (``403 human_action_required``) with
``details.decision_link``, the address of the Ticket's page with the wait's Clear in focus.

The handler is public and typed on the attributes of the composition root it uses, so a unit test
runs it with the real services on the typed fakes. Its catalogue entry is built here too
(``work_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, Protocol, TypeIs

from pydantic import ValidationError

from ..core.context import ActorContext
from ..core.errors import ApiError, ValidationFailure, VersionConflict
from ..schemas.cards import WAITING_REASON_CHARS, WAITS, TicketWaitSet
from .agent_tools_read import (
    ToolArguments,
    ToolResult,
    _require,
    _text,
    refused_at,
    tool_decision_link,
)
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument
from .loop_stops import NOT_A_STOP

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from ..core.config import Settings
    from .cards import CardService
    from .ticket_work import TicketWorkService

USE_INSTEAD: Final = ("record_poc_decision", "report_missing")
INSTEAD: Final = (
    "Record a choice with record_poc_decision and something only a person can provide with "
    "report_missing, then go on with the work."
)
"""What a ``not_a_stop`` refusal tells a worker to do instead of waiting."""


class WaitSetting(Protocol):
    """What ``set_ticket_wait`` uses of the composition root."""

    @property
    def card(self) -> CardService: ...

    @property
    def ticket_work(self) -> TicketWorkService: ...

    @property
    def settings(self) -> Settings: ...


def _payload(version: int, args: ToolArguments) -> TicketWaitSet:
    waiting_for = _require(args, "waiting_for")
    if waiting_for not in WAITS:
        raise ValidationFailure(
            "waiting_for must be one of " + ", ".join(WAITS),
            details={"argument": "waiting_for", "choices": list(WAITS)},
        )
    fields: dict[str, object] = {
        "version": version,
        "waiting_for": waiting_for,
        "reason": _require(args, "reason"),
    }
    # A wait that names no stop is the wait it always was: the field is not even sent.
    stop = _text(args.get("stop"))
    if stop is not None:
        fields["stop"] = stop
    try:
        return TicketWaitSet.model_validate(fields)
    except ValidationError as error:
        problems = error.errors()
        about_stop = all(problem["loc"][:1] == ("stop",) for problem in problems)
        raise ValidationFailure(
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in problems),
            details=(
                {"argument": "stop"}
                if about_stop
                else {"argument": "reason", "maximum": WAITING_REASON_CHARS}
            ),
        ) from None


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _stops(details: Mapping[str, object] | None) -> list[str]:
    """The stop list a ``not_a_stop`` refusal carries in its details."""
    stops = details.get("stops") if details is not None else None
    if not _is_list(stops):
        return []
    return [line for line in stops if isinstance(line, str)]


def not_a_stop_refusal(refusal: ApiError) -> ValidationFailure:
    """``422 not_a_stop`` as the tool answers it: the service's sentence, what to do instead
    (``INSTEAD``) and the Loop's stop list numbered, so the worker names a line or goes on."""
    stops = _stops(refusal.details)
    if stops:
        numbered = "; ".join(f"{number}. {line}" for number, line in enumerate(stops, start=1))
        listed = f"This Loop's stop list: {numbered}."
    else:
        listed = "This Loop's stop list is empty: nothing stops its work."
    return ValidationFailure(
        f"{refusal.message} {INSTEAD} {listed}",
        code=NOT_A_STOP,
        details={**(refusal.details or {}), "stops": stops, "use_instead": list(USE_INSTEAD)},
    )


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
        except ApiError as refusal:
            if refusal.code == NOT_A_STOP:
                raise not_a_stop_refusal(refusal) from None
            if refusal.code != "human_action_required":
                raise
            # Another wait is set: the person who answers it clears it on the Ticket's page.
            link = tool_decision_link(
                "wait",
                board_id=board_id,
                loop_id=loop_id,
                card_id=card["id"],
                public_url=services.settings.public_url,
            )
            raise refused_at(
                refusal, link, "The person who answers it clears that wait on the Ticket's page"
            ) from None
        wait: ToolResult = {
            "waiting_for": written["waiting_for"],
            "reason": written["waiting_reason"],
            "set_by": written["waiting_set_by"],
            "set_at": written["waiting_set_at"],
        }
        next_step = (
            "A person answers and clears the wait in the Ticket dialog; list_tickets with "
            "needs_person true lists what waits for a person."
        )
        if written["waiting_stop"] is not None:
            # Only a wait that names its stop says so; one without keeps the answer it had.
            wait["stop"] = written["waiting_stop"]
            next_step += " Work on other Tickets meanwhile."
        return {
            "ticket": {
                "id": written["id"],
                "key": written["ticket_key"],
                "state": written["state"],
                "version": written["version"],
            },
            "wait": wait,
            "next_step": next_step,
        }
    raise AssertionError("unreachable: the second attempt returns or raises")


def work_tools(board_id: ArgumentSchema, card_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entry of setting a Ticket's wait."""
    return [
        AgentTool(
            name="set_ticket_wait",
            description=(
                "Stop a Ticket for a real stop: something the Loop's stop list names (read_loop "
                "gives the list; a person writes it). Give that line in stop and what is needed "
                "in reason. Not for a choice that can be changed afterwards (record_poc_decision) "
                "and not for something missing from a person that the work can go around "
                "(report_missing): those never stop work. The Ticket then needs input (or is "
                "blocked, for a third party) until a person clears the wait; clearing or "
                "replacing a wait is a person's act. Only on an open Ticket that waits for "
                "nothing; the version is read for you."
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
                    "stop": string_argument(
                        "The line of the Loop's stop list this falls under, word for word or by "
                        "its number"
                    ),
                },
                required=["board_id", "card_id", "waiting_for", "reason"],
            ),
            handler=set_ticket_wait,
        ),
    ]


__all__ = [
    "INSTEAD",
    "USE_INSTEAD",
    "WaitSetting",
    "not_a_stop_refusal",
    "set_ticket_wait",
    "work_tools",
]
