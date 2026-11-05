"""The Ticket list a worker reads first, and the summaries that make it readable.

``list_tickets`` answers one short row per Ticket of a board (or of one Loop): its key, title, a
summary of what it is about, where it stands and whether it is ready, never its description, so a
worker can choose before it reads a Ticket in full with ``read_ticket``. A Ticket nobody has
summarised shows an excerpt of its description, marked as one. ``write_ticket_summaries`` lets a
worker write those summaries; every write is an ordinary versioned Ticket edit through
``CardService.update``.

Both handlers are public and typed on the attributes of the composition root they use, so a unit
test runs them with the real services on the typed fakes. Their catalogue entries are built here
too (``listing_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeIs

from pydantic import JsonValue, ValidationError

from ..core.context import ActorContext
from ..core.errors import ApiError, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import CardUpdate
from .agent_tools_read import ToolArguments, ToolResult, _require, _text, _whole_number
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument
from .ticket_summaries import excerpt

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardEntry, CardService
    from .lists import ListEntry, ListService
    from .loops import LoopEntry, LoopService

LIST_DEFAULT = 100
LIST_LIMIT = 200
SUMMARY_WRITE_LIMIT = 100
# The Tickets of one Loop read to order them as the board shows them, before the limit is taken.
LOOP_CARD_LIMIT = 1000

# Refusals one Ticket's summary may meet without stopping the others: an unknown id, a read-only
# Loop or board, a summary the schema refuses.
_PER_TICKET_REFUSALS = (NotFound, ValidationFailure)


class TicketListing(Protocol):
    """What ``list_tickets`` uses of the composition root."""

    @property
    def loop(self) -> LoopService: ...

    @property
    def card(self) -> CardService: ...

    @property
    def list(self) -> ListService: ...


class SummaryWriting(Protocol):
    """What ``write_ticket_summaries`` uses of the composition root."""

    @property
    def card(self) -> CardService: ...


def ticket_row(card: CardEntry, *, loop_key: str, column: str) -> ToolResult:
    """One Ticket as a list shows it: what it is, where it stands, never its description."""
    written = bool(card["summary"])
    shown = card["summary"] if written else excerpt(card["description"])
    return {
        "id": card["id"],
        "key": card["ticket_key"],
        "title": card["title"],
        "summary": shown,
        "summary_kind": "written" if written else ("excerpt" if shown else "none"),
        "summary_stale": card["summary_stale"],
        "loop_key": loop_key,
        "column": column,
        "phase_number": card["phase_number"],
        "ready": card["ready"],
        "human_action_required": card["human_action_required"],
        "assignee": card["assignee_name"],
        "completed_at": card["completed_at"],
    }


def board_rows(
    cards: list[CardEntry], columns: list[ListEntry], *, loop_key: str
) -> list[ToolResult]:
    """One Loop's Tickets as list rows, in the order its board shows them: column by column, then
    down each column."""
    names = {entry["id"]: entry["name"] for entry in columns}
    order = {entry["id"]: index for index, entry in enumerate(columns)}
    ordered = sorted(
        cards, key=lambda card: (order.get(card["list_id"], len(order)), card["position"])
    )
    return [
        ticket_row(card, loop_key=loop_key, column=names.get(card["list_id"], ""))
        for card in ordered
    ]


def _loops(services: TicketListing, board_id: str, args: ToolArguments) -> list[LoopEntry]:
    include_completed = bool(args.get("include_completed", False))
    loop_id = _text(args.get("loop_id"))
    loops = services.loop.list(
        board_id, include_completed=include_completed or loop_id is not None
    )
    if loop_id is None:
        return loops
    chosen = [entry for entry in loops if entry["id"] == loop_id]
    if not chosen:
        raise NotFound("Loop not found", details={"loop_id": loop_id})
    return chosen


def list_tickets(services: TicketListing, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("cards:read")
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    limit = _whole_number(args, "limit", default=LIST_DEFAULT, maximum=LIST_LIMIT)
    include_completed = bool(args.get("include_completed", False))
    query = _text(args.get("query"))
    tickets: list[ToolResult] = []
    truncated = False
    for loop in _loops(services, board_id, args):
        if len(tickets) >= limit:
            truncated = True  # Loops are left that were not read
            break
        cards, total = services.card.list(
            board_id,
            loop["id"],
            q=query,
            completed=None if include_completed else False,
            limit=LOOP_CARD_LIMIT,
        )
        # The limit is taken after ordering, so it never skips a column's first Tickets.
        rows = board_rows(cards, services.list.list(board_id, loop["id"]), loop_key=loop["key"])
        taken = rows[: limit - len(tickets)]
        tickets += taken
        truncated = truncated or total > len(taken)
    unsummarised = sum(1 for row in tickets if row["summary_kind"] != "written")
    stale = sum(1 for row in tickets if row["summary_stale"])
    return {
        "board_id": board_id,
        "tickets": tickets,
        "count": len(tickets),
        "truncated": truncated,
        "without_summary": unsummarised,
        "stale_summaries": stale,
        "next_step": (
            "Call read_ticket with a Ticket id to read it in full. A row whose summary_kind is "
            "excerpt or none, or whose summary is stale, needs a summary: write_ticket_summaries."
        ),
    }


def _is_entries(value: JsonValue) -> TypeIs[list[JsonValue]]:
    return isinstance(value, list)


def _entries(args: ToolArguments) -> list[tuple[str, str]]:
    """The ``{card_id, summary}`` pairs, refused as a whole when one is malformed."""
    value = args.get("summaries")
    if not _is_entries(value) or not value:
        raise ValidationFailure(
            "summaries must be a non-empty list of {card_id, summary}",
            details={"argument": "summaries"},
        )
    if len(value) > SUMMARY_WRITE_LIMIT:
        raise ValidationFailure(
            f"At most {SUMMARY_WRITE_LIMIT} summaries per call",
            details={"argument": "summaries", "maximum": SUMMARY_WRITE_LIMIT},
        )
    pairs: list[tuple[str, str]] = []
    for index, entry in enumerate(value):
        card_id = _text(entry.get("card_id")) if isinstance(entry, dict) else None
        summary = entry.get("summary") if isinstance(entry, dict) else None
        if card_id is None or not isinstance(summary, str):
            raise ValidationFailure(
                f"summaries[{index}] needs card_id and summary (text)",
                details={"argument": "summaries", "index": index},
            )
        pairs.append((card_id, summary))
    return pairs


def _write_one(
    services: SummaryWriting, actor: ActorContext, board_id: str, card_id: str, summary: str
) -> ToolResult:
    """Write one summary as a versioned edit, reading the version itself and retrying once when
    someone else changed the Ticket in between."""
    for attempt in range(2):
        loop_id, card = services.card.locate(board_id, card_id)
        try:
            payload = CardUpdate(version=card["version"], summary=summary)
        except ValidationError as error:
            raise ValidationFailure(
                "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
            ) from None
        try:
            written = services.card.update(actor, board_id, loop_id, card_id, payload)
        except VersionConflict:
            if attempt:
                raise
            continue
        return {
            "card_id": card_id,
            "key": written["ticket_key"],
            "status": "written",
            "version": written["version"],
        }
    raise AssertionError("unreachable: the second attempt returns or raises")


def write_ticket_summaries(
    services: SummaryWriting, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:write")
    board_id = _require(args, "board_id")
    results: list[ToolResult] = []
    for card_id, summary in _entries(args):
        try:
            results.append(_write_one(services, actor, board_id, card_id, summary))
        except ApiError as refusal:
            if not isinstance(refusal, _PER_TICKET_REFUSALS) and refusal.code != "loop_read_only":
                raise
            results.append(
                {
                    "card_id": card_id,
                    "status": "refused",
                    "code": refusal.code,
                    "message": refusal.message,
                }
            )
    written = sum(1 for result in results if result["status"] == "written")
    return {
        "written": written,
        "refused": len(results) - written,
        "results": results,
        "next_step": "Call list_tickets to see the summaries as a list.",
    }


def listing_tools(board_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entries of the Ticket list and of writing its summaries."""
    return [
        AgentTool(
            name="list_tickets",
            description=(
                "List a board's Tickets, or one Loop's, as short rows: key, title, a summary of "
                "what each is about, its Loop, column, Phase, whether it is ready and who has it. "
                "Choose from this list, then read the Ticket in full with read_ticket. Completed "
                "Tickets and completed Loops are left out unless include_completed is true."
            ),
            scopes=("cards:read", "loops:read"),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "loop_id": string_argument("Optional Loop identifier from read_board"),
                    "query": string_argument("Optional words in the title or description"),
                    "include_completed": {
                        "type": "boolean",
                        "description": "Also list completed Tickets and completed Loops",
                    },
                    "limit": {"type": "number", "minimum": 1, "maximum": LIST_LIMIT},
                },
                required=["board_id"],
            ),
            handler=list_tickets,
        ),
        AgentTool(
            name="write_ticket_summaries",
            description=(
                "Write the short summary of one or more Tickets: what each is about in one or two "
                "plain sentences (at most 400 characters, no file paths or code), so the Ticket "
                "list reads well for people and agents. Each write is a versioned edit that reads "
                "the version itself; an empty summary removes one."
            ),
            scopes=("cards:write",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "summaries": {
                        "type": "array",
                        "description": (
                            f"At most {SUMMARY_WRITE_LIMIT} objects {{card_id, summary}}; card_id "
                            "from list_tickets"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "card_id": {"type": "string"},
                                "summary": {"type": "string"},
                            },
                            "required": ["card_id", "summary"],
                            "additionalProperties": False,
                        },
                    },
                },
                required=["board_id", "summaries"],
            ),
            handler=write_ticket_summaries,
        ),
    ]


__all__ = [
    "LIST_LIMIT",
    "LOOP_CARD_LIMIT",
    "SUMMARY_WRITE_LIMIT",
    "SummaryWriting",
    "TicketListing",
    "board_rows",
    "list_tickets",
    "listing_tools",
    "ticket_row",
    "write_ticket_summaries",
]
