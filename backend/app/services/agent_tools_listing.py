"""The Ticket list a worker chooses from, and the summaries a person reads.

``list_tickets`` answers which Tickets there are and where each stands, never what one says: a row
is its id, key, title, Loop, column, Phase, owner, state (ready, needs input, blocked) and
workplace. Filters narrow it (a Loop, a column, an owner, a Phase, the state, the workplace, the
wait, what needs a person, whether the task is a person's, a label, a priority, a due date, a
missing or stale summary, words; ``agent_tools_filters``), and a worker reads the one it chose
with ``read_ticket``, so a list costs the same whatever the Tickets say.
``write_ticket_summaries`` writes the short summary ``read_ticket`` and the Ticket dialog show;
every write is an ordinary versioned Ticket edit through ``CardService.update``.

Both handlers are public and typed on the attributes of the composition root they use, so a unit
test runs them with the real services on the typed fakes. Their catalogue entries are built here
too (``listing_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, TypeIs

from pydantic import JsonValue, ValidationError

from ..core.context import ActorContext
from ..core.errors import ApiError, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import WAITING_FOR, WORKPLACES, CardUpdate
from .agent_tools_filters import (
    PRIORITIES,
    TicketFilters,
    assignee_filter,
    choice,
    chosen_columns,
    ticket_filters,
)
from .agent_tools_read import ToolArguments, ToolResult, _require, _text, _whole_number
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardEntry, CardService
    from .lists import ListEntry, ListService
    from .loops import LoopEntry, LoopService

LIST_DEFAULT: Final = 100
LIST_LIMIT: Final = 200
SUMMARY_WRITE_LIMIT: Final = 100
# The Tickets of one Loop read to filter and order them before a page is taken.
LOOP_CARD_LIMIT: Final = 1000
FIELDS: Final = ("standard", "brief")

# Refusals one Ticket's summary may meet without stopping the others: an unknown id, a read-only
# Loop or board, a summary the schema refuses.
_PER_TICKET_REFUSALS = (NotFound, ValidationFailure)


class LoopFinding(Protocol):
    """What naming a Loop by its id or its key uses of the composition root."""

    @property
    def loop(self) -> LoopService: ...


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


# --- naming a Loop -------------------------------------------------------------------------------


def find_loop(services: LoopFinding, board_id: str, reference: str) -> LoopEntry:
    """The Loop a worker named by its id or by its key (``AN001``, in any case), completed and
    archived ones included; an unknown one is refused with the keys there are."""
    loops = services.loop.list(board_id, include_completed=True, include_archived=True)
    for entry in loops:
        if entry["id"] == reference:
            return entry
    for entry in loops:
        if entry["key"].casefold() == reference.casefold():
            return entry
    raise NotFound(
        "Loop not found",
        details={"loop_id": reference, "loop_keys": [entry["key"] for entry in loops]},
    )


def loop_id_of(services: LoopFinding, args: ToolArguments) -> str:
    """The id of the Loop ``loop_id`` names, by its id or by its key."""
    return find_loop(services, _require(args, "board_id"), _require(args, "loop_id"))["id"]


# --- list_tickets --------------------------------------------------------------------------------


def ticket_row(card: CardEntry, *, loop_key: str, column: str, brief: bool = False) -> ToolResult:
    """One Ticket as a list shows it: what it is called and where it stands, never what it says."""
    if brief:
        return {"id": card["id"], "key": card["ticket_key"], "title": card["title"]}
    return {
        "id": card["id"],
        "key": card["ticket_key"],
        "title": card["title"],
        "loop": loop_key,
        "column": column,
        "phase": card["phase_number"],
        "state": card["state"],
        "workplace": card["workplace"],
        "human_action_required": card["human_action_required"],
        "assignee": card["assignee_name"],
        "completed": card["completed_at"] is not None,
    }


def board_order(cards: list[CardEntry], columns: list[ListEntry]) -> list[CardEntry]:
    """A Loop's Tickets column by column as its board shows them, then by Phase and by key, so
    the work of one Phase reads together."""
    order = {entry["id"]: index for index, entry in enumerate(columns)}

    def place(card: CardEntry) -> tuple[int, bool, int, bool, str, int]:
        phase = card["phase_number"]
        key = card["ticket_key"]
        return (
            order.get(card["list_id"], len(order)),
            phase is None,
            phase or 0,
            key is None,
            key or "",
            card["position"],
        )

    return sorted(cards, key=place)


def _loops(services: TicketListing, board_id: str, args: ToolArguments) -> list[LoopEntry]:
    reference = _text(args.get("loop_id"))
    if reference is not None:
        return [find_loop(services, board_id, reference)]
    return services.loop.list(board_id, include_completed=bool(args.get("include_completed")))


def _loop_rows(
    services: TicketListing,
    actor: ActorContext,
    board_id: str,
    loop: LoopEntry,
    filters: TicketFilters,
    *,
    brief: bool,
) -> list[ToolResult] | None:
    """One Loop's rows the filters keep, in board order; ``None`` when the call named columns and
    this Loop has none of them."""
    columns = services.list.list(board_id, loop["id"])
    chosen = chosen_columns(columns, filters.columns)
    names = {entry["id"]: entry["name"] for entry in columns}
    if filters.columns and not chosen:
        return None
    cards, _ = services.card.list(
        board_id,
        loop["id"],
        q=filters.query,
        label=filters.label,
        priority=filters.priority,
        due_before=filters.due_before,
        overdue=filters.overdue,
        assignee=assignee_filter(filters.assignee, actor),
        completed=None if filters.include_completed else False,
        limit=LOOP_CARD_LIMIT,
    )
    kept = [
        card for card in cards if filters.keeps(card) and (not chosen or card["list_id"] in chosen)
    ]
    return [
        ticket_row(card, loop_key=loop["key"], column=names.get(card["list_id"], ""), brief=brief)
        for card in board_order(kept, columns)
    ]


def list_tickets(services: TicketListing, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("cards:read")
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    filters = ticket_filters(args)
    brief = choice(args, "fields", FIELDS) == "brief"
    limit = _whole_number(args, "limit", default=LIST_DEFAULT, maximum=LIST_LIMIT)
    start = _whole_number(args, "continue_from", default=1, maximum=10**9) - 1
    loops = _loops(services, board_id, args)
    matched: list[ToolResult] = []
    column_found = False
    for loop in loops:
        rows = _loop_rows(services, actor, board_id, loop, filters, brief=brief)
        column_found = column_found or rows is not None
        matched += rows or []
    if filters.columns and loops and not column_found:
        names = {
            entry["name"] for loop in loops for entry in services.list.list(board_id, loop["id"])
        }
        raise ValidationFailure(
            "No Loop listed has a column of that name",
            details={"argument": "column", "columns": sorted(names)},
        )
    page = matched[start : start + limit]
    after = start + len(page)
    echo = filters.echo()
    return {
        "board_id": board_id,
        "filters": echo,
        "loops": {loop["key"]: loop["id"] for loop in loops},
        "tickets": page,
        "count": len(page),
        "total": len(matched),
        "continue_from": after + 1 if after < len(matched) else None,
        "next_step": (
            empty_advice(echo, loop_named=_text(args.get("loop_id")) is not None)
            if not matched
            else (
                "Choose a Ticket and read it with read_ticket. Narrow the list with a filter "
                "(column, assignee me, state, workplace, needs_person, phase) rather than reading "
                "more rows."
            )
        ),
    }


def _is_names(value: object) -> TypeIs[list[str]]:
    """A list in the filters' echo: the names of ``column`` or ``state``."""
    return isinstance(value, list)


def _shown(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if _is_names(value):
        return ", ".join(value)
    return str(value)


def empty_advice(filters: ToolResult, *, loop_named: bool) -> str:
    """What an empty ``list_tickets`` answer advises: which filters it applied, and that widening
    or dropping one (or ``loop_id``, or adding ``include_completed``) shows more."""
    applied = [
        f"{key} {_shown(value)}" for key, value in filters.items() if key != "include_completed"
    ]
    sentences = [
        f"No Ticket matches the filters applied ({'; '.join(applied)}): widen or drop one of "
        "them to see more."
        if applied
        else "No Ticket is listed, and no filter was applied."
    ]
    if loop_named:
        sentences.append("Drop loop_id to list every open Loop of the board.")
    if "include_completed" not in filters:
        sentences.append("include_completed true also lists completed Tickets and Loops.")
    return " ".join(sentences)


# --- write_ticket_summaries ----------------------------------------------------------------------


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
        "next_step": (
            "read_ticket shows a summary; list_tickets with summary missing or stale lists the "
            "Tickets that still need one."
        ),
    }


# --- the catalogue -------------------------------------------------------------------------------


def _boolean(description: str) -> ArgumentSchema:
    return {"type": "boolean", "description": description}


def listing_tools(board_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entries of the Ticket list and of writing the Tickets' summaries."""
    return [
        AgentTool(
            name="list_tickets",
            description=(
                "List which Tickets there are and where each stands, never what they say: id, "
                "key, title, Loop, column, Phase, state (ready, needs_input or blocked), "
                "workplace (codebase, outside or unknown), whether the task is a person's, and "
                "who has it. Work for a coding session: workplace codebase, state ready, "
                "human_action_required false. What needs a person: needs_person true. Choose "
                "one, then read it with read_ticket. The open Loops' open Tickets unless "
                "include_completed is true."
            ),
            scopes=("cards:read", "loops:read"),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "loop_id": string_argument("Optional Loop id or key (AN001), from read_board"),
                    "column": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'Optional column names, e.g. ["Todo", "In Progress"]',
                    },
                    "assignee": string_argument(
                        "Optional: me (this key), none (nobody), or a person id from read_board"
                    ),
                    "phase": {"type": "number", "minimum": 1, "description": "Optional Phase"},
                    "state": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional states: ready (may start now), needs_input (waits for a "
                            "decision, information or access) or blocked (earlier work, or a "
                            "third party)"
                        ),
                    },
                    "workplace": string_argument("Optional: " + ", ".join(WORKPLACES)),
                    "waiting_for": string_argument("Optional: " + ", ".join(WAITING_FOR)),
                    "needs_person": _boolean(
                        "Optional: what needs a person now (needs_input, or ready and a "
                        "person's task)"
                    ),
                    "human_action_required": _boolean(
                        "Optional: only Tickets a person must do (true) or only the others (false)"
                    ),
                    "label": string_argument("Optional label name"),
                    "priority": string_argument("Optional: " + ", ".join(PRIORITIES)),
                    "due_before": string_argument("Optional ISO 8601 date or time"),
                    "overdue": _boolean("Optional: only Tickets past their due date"),
                    "summary": string_argument(
                        "Optional: missing or stale, the Tickets whose summary needs writing"
                    ),
                    "query": string_argument("Optional words in the title or description"),
                    "include_completed": _boolean("Also list completed Tickets and Loops"),
                    "fields": string_argument("Optional: brief for id, key and title alone"),
                    "limit": {"type": "number", "minimum": 1, "maximum": LIST_LIMIT},
                    "continue_from": {
                        "type": "number",
                        "minimum": 1,
                        "description": "The continue_from of the previous answer",
                    },
                },
                required=["board_id"],
            ),
            handler=list_tickets,
        ),
        AgentTool(
            name="write_ticket_summaries",
            description=(
                "Write the short summary of one or more Tickets: what each is about in one or two "
                "plain sentences (at most 400 characters, no file paths or code), the first thing "
                "read_ticket and the Ticket dialog show. Each write is a versioned edit that "
                "reads the version itself; an empty summary removes one."
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
    "LoopFinding",
    "SummaryWriting",
    "TicketFilters",
    "TicketListing",
    "assignee_filter",
    "board_order",
    "chosen_columns",
    "empty_advice",
    "find_loop",
    "list_tickets",
    "listing_tools",
    "loop_id_of",
    "ticket_filters",
    "ticket_row",
    "write_ticket_summaries",
]
