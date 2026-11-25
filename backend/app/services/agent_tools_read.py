"""The worker tools that only read, and the helpers every tool handler shares.

The catalogue in ``agent_tools`` declares each tool's name, description, scopes and input schema;
the handlers here run the read-only entries (``list_boards``, ``read_board``,
``read_ticket`` and ``search_tickets``; ``read_discussion`` lives in ``agent_tools_discussions``).
Each takes
``(services, actor, args)``, opens with the ``actor.require`` checks of the scopes its entry
declares and calls the same services as the REST routes.

The two listing handlers are public and typed on the attributes of the composition root they use
(``BoardListing``, ``TicketSearching``), so a unit test runs them with the real services on the
typed fakes; the others still take the whole ``Services``.

A key reports on a Ticket it took before it takes another one (``409 report_required``).
``loop_summaries``, ``list_tickets`` and ``read_ticket`` show the key the Tickets it owes a report
on under ``unreported`` (``unreported_rows``), and ``next_step`` asks for the reports first
(``report_first``); ``REPORT_RULE`` is the rule in the one sentence the worker texts give it.

What waits for a person carries ``decision_link``, the address in the web UI where the person
decides (``decision_links``): ``loop_summaries`` and ``read_loop`` for the Loop's next decision,
``read_ticket`` for a wait to clear and a person's task to confirm (``ticket_decision_link``), and
the refusals a tool meets on a person's decision (``refused_at``). ``tool_decision_link`` builds
each from the ids the services read, with the address from the composition root
(``Services.settings.public_url``); ``DECISION_LINK_RULE`` is the sentence the worker texts give it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final, Literal, Protocol

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import ApiError, ValidationFailure
from ..core.identifiers import canonical_board_id
from .attachments import attachment_summary
from .decision_links import Decision, decision_link
from .search import search_engine

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from . import Services
    from .attachments import AttachmentEntry
    from .boards import BoardService
    from .card_notes import CardNoteEntry
    from .cards import CardEntry, UnreportedEntry
    from .lists import ListEntry, ListService
    from .loops import LoopService
    from .plan_views import Readiness
    from .search import SearchHit, SearchService

# A tool's arguments: the JSON object an MCP ``tools/call`` carried, untrusted.
type ToolArguments = Mapping[str, JsonValue]
# A tool's answer: an object built from the services' entries, sent back as JSON.
type ToolResult = dict[str, object]

# The listing tools are the way in, not a report: at most this many boards, and this many hits.
BOARD_LIST_LIMIT = 100
SEARCH_LIMIT = 100
SEARCH_DEFAULT = 25
# read_ticket names a Ticket's newest files; list_attachments names them all.
TICKET_ATTACHMENTS = 50

# The rule of 409 report_required in one sentence: move_ticket's description, the MCP instructions
# and /llms.txt give it in these words.
REPORT_RULE: Final = (
    "A key that took another Ticket and has not reported on it since, with a comment, a wait or a "
    "completion, is refused with 409 report_required; moving a Ticket back to the first column "
    "never is."
)
# What next_step says first while the key has Tickets under unreported.
REPORT_FIRST: Final = (
    "Report on each Ticket under unreported with comment_ticket, set_ticket_wait or "
    "complete_ticket before you move another Ticket."
)
# The address of a person's decision in one sentence: the MCP instructions, /llms.txt and whoami's
# note on what only a person decides give it in these words.
DECISION_LINK_RULE: Final = (
    "An answer or a refusal that waits for a person carries decision_link, the address in "
    "Tralala where that person decides."
)


class BoardListing(Protocol):
    """What ``list_boards`` uses of the composition root."""

    @property
    def board(self) -> BoardService: ...


class TicketSearching(Protocol):
    """What ``search_tickets`` uses of the composition root."""

    @property
    def search(self) -> SearchService: ...

    @property
    def loop(self) -> LoopService: ...

    @property
    def list(self) -> ListService: ...


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _require(args: ToolArguments, key: str) -> str:
    value = _text(args.get(key))
    if value is None:
        raise ValidationFailure(f"{key} is required", details={"argument": key})
    return value


def _whole_number(args: ToolArguments, key: str, *, default: int, maximum: int) -> int:
    """An optional whole number from 1 to ``maximum``; a refusal names the argument."""
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise ValidationFailure(f"{key} must be a whole number", details={"argument": key})
    number = int(value)
    if not 1 <= number <= maximum:
        raise ValidationFailure(
            f"{key} must be between 1 and {maximum}",
            details={"argument": key, "minimum": 1, "maximum": maximum},
        )
    return number


def _loop_lists(services: Services, board_id: str, loop_id: str) -> list[ListEntry]:
    return services.list.list(board_id, loop_id)


def _ticket_location(
    services: Services, board_id: str, card_id: str
) -> tuple[str, CardEntry]:
    loop_id, _ = services.card.locate(board_id, card_id)
    return loop_id, services.card.get(board_id, loop_id, card_id)


def unreported_rows(entries: Sequence[UnreportedEntry]) -> list[ToolResult]:
    """The Tickets a key took and has not reported on since, as the worker tools answer them under
    ``unreported``: id, key, title, the Loop's key and when the key first moved it."""
    return [
        {
            "id": entry["id"],
            "key": entry["key"],
            "title": entry["title"],
            "loop": entry["loop_key"],
            "taken_at": entry["taken_at"],
        }
        for entry in entries
    ]


def unreported_besides(entries: Sequence[UnreportedEntry], card_id: str) -> list[ToolResult]:
    """What ``read_ticket`` answers under ``unreported``: the Tickets other than ``card_id`` that
    the key has not reported on, the ones that make its move of this Ticket refused."""
    return unreported_rows([entry for entry in entries if entry["id"] != card_id])


def report_first(unreported: Sequence[ToolResult], advice: str) -> str:
    """A ``next_step``: ``advice``, after ``REPORT_FIRST`` while ``unreported`` is not empty."""
    return f"{REPORT_FIRST} {advice}" if unreported else advice


def tool_decision_link(
    decision: Decision,
    *,
    board_id: str,
    loop_id: str,
    card_id: str | None = None,
    public_url: str | None,
) -> str:
    """``decision_links.decision_link`` as a worker tool answers it.

    ``board_id`` is the board the call named, which the services have already resolved: they read
    the board's registry row by its canonical text (``BoardService.require_row``), so that text is
    the board's id, whichever way a UUID was written. ``loop_id`` and ``card_id`` are the ids of
    the rows the services read, never a key, so the path is built from ids alone. ``public_url``
    is ``Services.settings.public_url``: a handler never reads the environment or a request.
    """
    return decision_link(
        decision,
        board_id=canonical_board_id(board_id),
        loop_id=loop_id,
        card_id=card_id,
        public_url=public_url,
    )


def ticket_decision_link(
    card: CardEntry,
    decision: Literal["wait", "confirmation"],
    *,
    loop_read_only: bool,
    public_url: str | None,
) -> str | None:
    """Where a person takes ``decision`` on the Ticket while it waits for them: clearing its wait
    (``wait``) while it waits for something, confirming it (``confirmation``) while it is a
    person's task. None otherwise, and for a completed or archived Ticket or one in a Loop that is
    read-only, where nobody clears or confirms anything any more (its page offers neither)."""
    if card["completed_at"] or card["archived_at"] or loop_read_only:
        return None
    pending = (
        card["waiting_for"] != "nothing" if decision == "wait" else card["human_action_required"]
    )
    if not pending:
        return None
    return tool_decision_link(
        decision,
        board_id=card["board_id"],
        loop_id=card["loop_id"],
        card_id=card["id"],
        public_url=public_url,
    )


def refused_at(refusal: ApiError, link: str, where: str) -> ApiError:
    """``refusal`` as a worker tool answers a decision that is a person's: the same class, code
    and status, ``details.decision_link`` the address of that decision, and the message ending in
    ``where`` the person takes it, followed by the address."""
    return type(refusal)(
        f"{refusal.message.rstrip('. ')}. {where}: {link}",
        code=refusal.code,
        status_code=refusal.status_code,
        details={**(refusal.details or {}), "decision_link": link},
        retryable=refusal.retryable,
    )


# --- handlers ---------------------------------------------------------------


def list_boards(services: BoardListing, actor: ActorContext, args: ToolArguments) -> ToolResult:
    """The boards a worker may start from, by name; archived ones only on request."""
    actor.require("boards:read")
    status = _text(args.get("status"))
    include_archived = bool(args.get("include_archived", False)) or status == "archived"
    entries, total = services.board.list(
        q=_text(args.get("query")),
        status=status,
        sort="name",
        order="asc",
        limit=BOARD_LIST_LIMIT,
        with_counts=True,
    )
    boards: list[ToolResult] = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "description": entry["description"],
            "status": entry["status"],
            "loop_count": entry["loop_count"],
            "updated_at": entry["updated_at"],
        }
        for entry in entries
        if include_archived or entry["status"] != "archived"
    ]
    return {
        "boards": boards,
        "count": len(boards),
        "truncated": total > BOARD_LIST_LIMIT,
        "next_step": (
            "Call read_board with one of these board ids to list its Loops, or search_tickets "
            "to find a Ticket by words."
        ),
    }


def _found_ticket(hit: SearchHit, columns: Mapping[str, str]) -> ToolResult:
    return {
        "board_id": hit["board_id"],
        "loop_id": hit["loop_id"],
        "loop_key": hit["loop_key"],
        "card_id": hit["id"],
        "key": hit["ticket_key"],
        "title": hit["title"],
        "column": columns.get(hit["list_id"]),
        "completed_at": hit["completed_at"],
    }


def search_tickets(
    services: TicketSearching, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    """Tickets whose title or description carry the words: in one Loop, in a board's open Loops
    (its completed ones on request), or in the open Loops of every active board."""
    actor.require("cards:read")
    query = _require(args, "query")
    limit = _whole_number(args, "limit", default=SEARCH_DEFAULT, maximum=SEARCH_LIMIT)
    board_id = _text(args.get("board_id"))
    loop_id = _text(args.get("loop_id"))
    if loop_id is not None and board_id is None:
        raise ValidationFailure(
            "board_id is required with loop_id", details={"argument": "board_id"}
        )
    hits: list[SearchHit] = []
    engines: list[str] = []
    truncated = False
    if board_id is None:
        found = services.search.global_search(q=query, limit_per_loop=limit)
        hits = found["items"]
        engines.append(found["engine"])
    else:
        loop_ids = (
            [loop_id]
            if loop_id is not None
            else [
                entry["id"]
                for entry in services.loop.list(
                    board_id,
                    include_completed=bool(args.get("include_completed", False)),
                    include_archived=False,
                )
            ]
        )
        for current in loop_ids:
            if len(hits) >= limit:
                truncated = True
                break
            page = services.search.board(board_id, current, q=query, limit=limit)
            hits += page["items"]
            engines.append(page["engine"])
            truncated = truncated or page["has_more"]
    if len(hits) > limit:
        truncated = True
        del hits[limit:]
    # The column is the list's name, read once per Loop a hit sits in.
    columns: dict[tuple[str, str], dict[str, str]] = {}
    tickets: list[ToolResult] = []
    for hit in hits:
        place = (hit["board_id"], hit["loop_id"])
        if place not in columns:
            columns[place] = {
                entry["id"]: entry["name"]
                for entry in services.list.list(
                    hit["board_id"], hit["loop_id"], include_archived=True
                )
            }
        tickets.append(_found_ticket(hit, columns[place]))
    return {
        "query": query,
        "tickets": tickets,
        "engine": search_engine(engines),
        "truncated": truncated,
        "next_step": (
            "Call read_ticket with the board_id and card_id of a hit before you change anything."
        ),
    }


def _read_board(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("boards:read")
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    board = services.board.get(board_id)
    loops = services.loop.list(
        board_id,
        include_completed=bool(args.get("include_completed", False)),
        include_archived=False,
    )
    # Where each Loop stands, and what comes next, is loop_summaries' answer; this one names them.
    summaries: list[ToolResult] = [
        {"id": entry["id"], "key": entry["key"], "name": entry["name"], "stage": entry["stage"]}
        for entry in loops
    ]
    return {
        "board": {
            "id": board["id"],
            "name": board["name"],
            "status": board["status"],
        },
        "loops": summaries,
        "people": services.agent.assignable_people(),
        "agents": services.agent.askable_agents(board_id),
        "next_step": (
            "Call loop_summaries for where each Loop stands and what comes next, list_tickets for "
            "the Tickets, or read_loop with a loop id (or key) for one Loop's overview."
        ),
    }


def allowed_actions(
    card: CardEntry,
    *,
    execution_allowed: bool,
    loop_read_only: bool = False,
    others_unreported: bool = False,
) -> list[str]:
    """The tools a worker may call on a Ticket now. ``comment_ticket`` always, done or not, in a
    completed, archived or cancelled Loop too, as the service allows (only an archived board
    refuses it); nothing else in such a Loop; ``set_ticket_wait`` while it is open and waits for
    nothing (clearing a wait is a person's act); ``complete_ticket`` only while the Ticket is ready
    (no blocker, no wait), open and not a person's, and for a planned one only while the Loop
    executes. ``move_ticket`` is left out while the key has another Ticket it took and has not
    reported on (``others_unreported``), which ``409 report_required`` would refuse."""
    if card["archived_at"] or loop_read_only:
        return ["comment_ticket"]
    may_wait = not card["completed_at"] and card["waiting_for"] == "nothing"
    if card["human_action_required"] and not card["completed_at"]:
        return ["comment_ticket", "ask_agents", *(["set_ticket_wait"] if may_wait else [])]
    allowed = ["comment_ticket", "assign_ticket", "move_ticket", "ask_agents"]
    # A planned Ticket waits for its phase entry conditions, a manual one does not; and while the
    # key owes a report on another Ticket, 409 report_required would refuse the move.
    if (card["plan_item_id"] and not card["ready"]) or others_unreported:
        allowed.remove("move_ticket")
    if may_wait:
        allowed.append("set_ticket_wait")
    if card["state"] == "ready" and (execution_allowed or not card["plan_item_id"]):
        allowed.append("complete_ticket")
    return allowed


def _read_ticket(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:read")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    loop_id, card = _ticket_location(services, board_id, card_id)
    readiness = services.loop.readiness(board_id, loop_id)
    column = next(
        (
            entry["name"]
            for entry in _loop_lists(services, board_id, loop_id)
            if entry["id"] == card["list_id"]
        ),
        None,
    )
    # Empty for a person and for an actor without a credential, so their answer keeps its shape.
    unreported = unreported_besides(services.card.unreported(board_id, actor), card_id)
    loop_read_only = services.loop.read_only(board_id, loop_id)
    allowed = allowed_actions(
        card,
        execution_allowed=readiness["execution_allowed"],
        loop_read_only=loop_read_only,
        others_unreported=bool(unreported),
    )
    public_url = services.settings.public_url
    return {
        "ticket": {
            "id": card["id"],
            "key": card["ticket_key"],
            "title": card["title"],
            "summary": card["summary"],
            "summary_source": card["summary_source"],
            "summary_stale": card["summary_stale"],
            "face": card["face"],
            "description": card["description"],
            "plan": ticket_plan(readiness, card["id"]),
            "column": column,
            "list_id": card["list_id"],
            "priority": card["priority"],
            "labels": [label["name"] for label in card["labels"]],
            "assignee": (
                {
                    "id": card["assignee_actor_id"],
                    "name": card["assignee_name"],
                    "type": card["assignee_type"],
                }
                if card["assignee_actor_id"]
                else None
            ),
            "version": card["version"],
            "completed_at": card["completed_at"],
            "acceptance_criteria": card["acceptance_criteria"],
            "expected_evidence": card["expected_evidence"],
            "state": card["state"],
            "workplace": card["workplace"],
            "wait": ticket_wait(card, loop_read_only=loop_read_only, public_url=public_url),
            "blockers": card["blockers"],
            "human_action_required": card["human_action_required"],
            # Where a person confirms a person's task.
            "decision_link": ticket_decision_link(
                card, "confirmation", loop_read_only=loop_read_only, public_url=public_url
            ),
            "needs_person": card["needs_person"],
            "human_instructions": card["human_instructions"],
            "checklists": services.checklist.list(board_id, card_id),
            "comments": services.comment.list(board_id, card_id),
            "person_notes": person_notes(
                services.card_note.list(actor, board_id, loop_id, card_id)
            ),
            **ticket_attachments(services.attachment.for_ticket(board_id, card_id)),
        },
        "loop": {
            "id": loop_id,
            "stage": readiness["stage"],
            "execution_allowed": readiness["execution_allowed"],
            "blocked_reason": readiness["blocked_reason"],
        },
        "allowed_actions": allowed,
        # Why move_ticket is not offered: the other Tickets the key owes a report on.
        **({"unreported": unreported} if unreported else {}),
    }


def ticket_wait(
    card: CardEntry, *, loop_read_only: bool, public_url: str | None
) -> ToolResult | None:
    """What the Ticket waits for as ``read_ticket`` shows it, None while it waits for nothing:
    the kind, the reason, who set it and when, and ``decision_link``, where the person who
    answers clears it (``ticket_decision_link``)."""
    if card["waiting_for"] == "nothing":
        return None
    return {
        "waiting_for": card["waiting_for"],
        "reason": card["waiting_reason"],
        "set_by": card["waiting_set_by"],
        "set_at": card["waiting_set_at"],
        "decision_link": ticket_decision_link(
            card, "wait", loop_read_only=loop_read_only, public_url=public_url
        ),
    }


def ticket_attachments(entries: list[AttachmentEntry]) -> ToolResult:
    """A Ticket's files as ``read_ticket`` shows them: the newest ``TICKET_ATTACHMENTS`` of
    ``entries`` (newest first already) and how many there are; the rest is
    ``list_attachments``'."""
    return {
        "attachments": [attachment_summary(entry) for entry in entries[:TICKET_ATTACHMENTS]],
        "attachment_count": len(entries),
    }


def person_notes(entries: list[CardNoteEntry]) -> list[ToolResult]:
    """A person's notes on the Ticket as `read_ticket` shows them, oldest first: who wrote each,
    when, and the text. A person writes them and no token can; they are the person's words beside
    the plan, not part of it."""
    return [
        {"author": entry["author"], "written_at": entry["written_at"], "text": entry["text"]}
        for entry in entries
    ]


def ticket_plan(readiness: Readiness, card_id: str) -> ToolResult | None:
    """What the approved RoadMap says about a planned Ticket beyond its instructions: why it is
    there (its objective) and the Phase it belongs to. A Ticket outside the plan has none."""
    item = next((entry for entry in readiness["items"] if entry["card_id"] == card_id), None)
    if item is None:
        return None
    phase = next((entry for entry in readiness["phases"] if entry["id"] == item["phase_id"]), None)
    return {
        "objective": item["objective"],
        "phase": {"number": item["phase_number"], "name": phase["name"] if phase else None},
    }


__all__ = [
    "BOARD_LIST_LIMIT",
    "DECISION_LINK_RULE",
    "REPORT_FIRST",
    "REPORT_RULE",
    "SEARCH_DEFAULT",
    "SEARCH_LIMIT",
    "TICKET_ATTACHMENTS",
    "BoardListing",
    "TicketSearching",
    "ToolArguments",
    "ToolResult",
    "_loop_lists",
    "_read_board",
    "_read_ticket",
    "_require",
    "_text",
    "_ticket_location",
    "_whole_number",
    "allowed_actions",
    "list_boards",
    "person_notes",
    "refused_at",
    "report_first",
    "search_tickets",
    "ticket_attachments",
    "ticket_decision_link",
    "ticket_plan",
    "ticket_wait",
    "tool_decision_link",
    "unreported_besides",
    "unreported_rows",
]
