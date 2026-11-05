"""The Ticket list a worker chooses from, and the summaries a person reads.

``list_tickets`` answers which Tickets there are and where each stands, never what one says: a row
is its id, key, title, Loop, column, Phase, owner and whether it is ready. Filters narrow it (a
Loop, a column, an owner, a Phase, readiness, who must do it, a label, a priority, a due date, a
missing or stale summary, words), and a worker reads the one it chose with ``read_ticket``, so a
list costs the same whatever the Tickets say. ``write_ticket_summaries`` writes the short summary
``read_ticket`` and the Ticket dialog show; every write is an ordinary versioned Ticket edit
through ``CardService.update``.

Both handlers are public and typed on the attributes of the composition root they use, so a unit
test runs them with the real services on the typed fakes. Their catalogue entries are built here
too (``listing_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, TypeIs, get_args

from pydantic import JsonValue, ValidationError

from ..core.context import ActorContext
from ..core.errors import ApiError, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import CardUpdate
from ..schemas.common import Priority
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
SUMMARY_STATES: Final = ("missing", "stale")
PRIORITIES: Final[tuple[str, ...]] = get_args(Priority)

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


# --- the filters ---------------------------------------------------------------------------------


def _flag(args: ToolArguments, key: str) -> bool | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValidationFailure(f"{key} must be true or false", details={"argument": key})
    return value


def _choice(args: ToolArguments, key: str, choices: tuple[str, ...]) -> str | None:
    value = _text(args.get(key))
    if value is not None and value not in choices:
        raise ValidationFailure(
            f"{key} must be one of {', '.join(choices)}",
            details={"argument": key, "choices": list(choices)},
        )
    return value


def _names(args: ToolArguments, key: str) -> tuple[str, ...]:
    """A list of texts, or one text; blank entries are dropped."""
    value = args.get(key)
    if value is None:
        return ()
    entries: list[JsonValue] = (
        [value] if isinstance(value, str) else value if isinstance(value, list) else [None]
    )
    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, str):
            raise ValidationFailure(f"{key} must be a list of texts", details={"argument": key})
        if entry.strip():
            names.append(entry.strip())
    return tuple(names)


@dataclass(frozen=True, slots=True)
class TicketFilters:
    """What ``list_tickets`` was asked to keep. The card list filters words, owner, label,
    priority, due date and completion itself (``CardService.list``); the column, the Phase,
    readiness, who must do it and the summary are applied here, to the Loop's Tickets as read."""

    query: str | None = None
    columns: tuple[str, ...] = ()
    assignee: str | None = None
    phase: int | None = None
    ready: bool | None = None
    human: bool | None = None
    label: str | None = None
    priority: str | None = None
    due_before: str | None = None
    overdue: bool = False
    summary: str | None = None
    include_completed: bool = False

    def keeps(self, card: CardEntry) -> bool:
        return all(
            (
                self.phase is None or card["phase_number"] == self.phase,
                self.ready is None or card["ready"] is self.ready,
                self.human is None or card["human_action_required"] is self.human,
                self.summary != "missing" or not card["summary"],
                self.summary != "stale" or card["summary_stale"],
            )
        )

    def echo(self) -> ToolResult:
        """The filters as given, so an answer says what it was narrowed by."""
        given: ToolResult = {
            "query": self.query,
            "column": list(self.columns) or None,
            "assignee": self.assignee,
            "phase": self.phase,
            "ready": self.ready,
            "human_action_required": self.human,
            "label": self.label,
            "priority": self.priority,
            "due_before": self.due_before,
            "overdue": self.overdue or None,
            "summary": self.summary,
            "include_completed": self.include_completed or None,
        }
        return {key: value for key, value in given.items() if value is not None}


def ticket_filters(args: ToolArguments) -> TicketFilters:
    """The filters of a ``list_tickets`` call, each refused by name when it is malformed."""
    return TicketFilters(
        query=_text(args.get("query")),
        columns=_names(args, "column"),
        assignee=_text(args.get("assignee")),
        phase=None
        if args.get("phase") is None
        else _whole_number(args, "phase", default=1, maximum=999),
        ready=_flag(args, "ready"),
        human=_flag(args, "human_action_required"),
        label=_text(args.get("label")),
        priority=_choice(args, "priority", PRIORITIES),
        due_before=_text(args.get("due_before")),
        overdue=_flag(args, "overdue") or False,
        summary=_choice(args, "summary", SUMMARY_STATES),
        include_completed=_flag(args, "include_completed") or False,
    )


def assignee_filter(assignee: str | None, actor: ActorContext) -> str | None:
    """``me`` is the key's own actor and ``none`` a Ticket nobody has; anything else is an id."""
    if assignee is None:
        return None
    word = assignee.casefold()
    if word == "me":
        return actor.actor_id
    return "unassigned" if word == "none" else assignee


def chosen_columns(columns: list[ListEntry], names: tuple[str, ...]) -> set[str]:
    """The ids of a Loop's columns named by their name (in any case) or by their id."""
    wanted = {name.casefold() for name in names}
    return {
        entry["id"]
        for entry in columns
        if entry["name"].casefold() in wanted or entry["id"] in names
    }


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
        "ready": card["ready"],
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
    brief = _choice(args, "fields", FIELDS) == "brief"
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
    return {
        "board_id": board_id,
        "filters": filters.echo(),
        "loops": {loop["key"]: loop["id"] for loop in loops},
        "tickets": page,
        "count": len(page),
        "total": len(matched),
        "continue_from": after + 1 if after < len(matched) else None,
        "next_step": (
            "Choose a Ticket and read it with read_ticket. Narrow the list with a filter (column, "
            "assignee me, ready, phase) rather than reading more rows."
        ),
    }


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
                "key, title, Loop, column, Phase, whether it is ready, whether a person must do "
                "it, and who has it. Narrow it with the filters, choose one, then read it with "
                "read_ticket. The open Loops' open Tickets unless include_completed is true."
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
                    "ready": _boolean("Optional: only Tickets that may start now, or only not"),
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
    "find_loop",
    "list_tickets",
    "listing_tools",
    "loop_id_of",
    "ticket_filters",
    "ticket_row",
    "write_ticket_summaries",
]
