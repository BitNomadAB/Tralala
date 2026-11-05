"""``read_loop`` as an overview, and ``read_document`` for the text a worker chooses to read.

``read_loop`` answers what a Loop is and where it stands without one line of its documents: each
document's state, revision, author and size, the Phases, the columns, one short row per Ticket and
the newest notes cut short. The documents themselves are read with ``read_document``: as numbered
lines a page at a time, or, for the technical analysis and RoadMap, as an outline whose items (a
finding, a Phase, a Ticket) are read one at a time. No answer carries a document twice.

The handlers are public and typed on the attributes of the composition root they use, so a unit
test runs them with the real services on the typed fakes. Their catalogue entries are built here
too (``document_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, TypeIs

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import NotFound, ValidationFailure
from ..schemas.loops import DOCUMENT_KINDS
from .agent_tools_listing import LOOP_CARD_LIMIT, board_rows
from .agent_tools_read import ToolArguments, ToolResult, _require, _text, _whole_number
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardService
    from .lists import ListService
    from .loop_documents import LoopDocumentService
    from .loop_documents_views import DocumentView
    from .loop_notes import LoopNoteService
    from .loops import LoopService

PAGE_CHARS: Final = 60_000
"""The most text one ``read_document`` answer carries; the rest is read from ``continue_from``."""
OVERVIEW_TICKETS: Final = 200
OVERVIEW_NOTES: Final = 5
NOTE_PREVIEW_CHARS: Final = 500
MAX_START_LINE: Final = 10_000_000
VIEWS: Final = ("text", "structured")
# What the overview shows of a revision's provenance: who wrote it and how, never its inputs.
_PROVENANCE_KEYS: Final = (
    "author",
    "agent_name",
    "model",
    "through",
    "submitted",
    "written",
    "rendered",
)


class LoopReading(Protocol):
    """What ``read_loop`` uses of the composition root."""

    @property
    def loop_document(self) -> LoopDocumentService: ...

    @property
    def loop(self) -> LoopService: ...

    @property
    def loop_notes(self) -> LoopNoteService: ...

    @property
    def list(self) -> ListService: ...

    @property
    def card(self) -> CardService: ...


class DocumentReading(Protocol):
    """What ``read_document`` uses of the composition root."""

    @property
    def loop_document(self) -> LoopDocumentService: ...


# --- read_loop -----------------------------------------------------------------------------------


def document_summary(document: DocumentView) -> ToolResult:
    """A document as the overview shows it: its state and size, never its text."""
    content = document["current_content"] or ""
    provenance = document["current_provenance"]
    return {
        "state": document["state"],
        "revision_id": document["current_revision_id"],
        "revision_number": document["current_revision_number"],
        "approved_revision_number": document["approved_revision_number"],
        "characters": len(content),
        "lines": len(content.splitlines()),
        "provenance": {key: provenance[key] for key in _PROVENANCE_KEYS if key in provenance},
        "stale_reasons": document["stale_reasons"],
    }


def read_loop(services: LoopReading, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("loops:read")
    if "document_kinds" in args:
        raise ValidationFailure(
            "read_loop no longer carries document text; read a document with read_document",
            details={"argument": "document_kinds"},
        )
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    context = services.loop_document.context(board_id, loop_id)
    documents = services.loop_document.documents(board_id, loop_id)["documents"]
    readiness = services.loop.readiness(board_id, loop_id)
    notes = services.loop_notes.list(actor, board_id, loop_id, limit=OVERVIEW_NOTES)
    columns = services.list.list(board_id, loop_id)
    cards, total = services.card.list(board_id, loop_id, limit=LOOP_CARD_LIMIT)
    tickets = board_rows(cards, columns, loop_key=context["loop_key"])[:OVERVIEW_TICKETS]
    return {
        "loop": {
            "id": context["loop_id"],
            "key": context["loop_key"],
            "name": context["loop_name"],
            "goal": context["goal"],
            "stage": context["stage"],
        },
        "execution_allowed": readiness["execution_allowed"],
        "blocked_reason": readiness["blocked_reason"],
        "documents": {kind: document_summary(documents[kind]) for kind in DOCUMENT_KINDS},
        "phases": [
            {
                "id": phase["id"],
                "number": phase["number"],
                "name": phase["name"],
                "state": phase["state"],
                "tickets": len(phase["tickets"]),
                "completed": sum(1 for ticket in phase["tickets"] if ticket["completed_at"]),
            }
            for phase in context["plan"]["phases"]
        ],
        "columns": [
            {"id": column["id"], "name": column["name"], "tickets": column["card_count"]}
            for column in columns
        ],
        "tickets": tickets,
        "ticket_count": total,
        "tickets_truncated": total > len(tickets),
        # Work added outside the plan (create_ticket): it never blocks readiness or completion.
        "unplanned_tickets": readiness["unplanned"],
        "notes": [
            {
                **note,
                "content": note["content"][:NOTE_PREVIEW_CHARS],
                "truncated": len(note["content"]) > NOTE_PREVIEW_CHARS,
            }
            for note in notes["notes"]
        ],
        "note_count": notes["count"],
        "next_step": (
            "Read a document with read_document (kind info, analysis, analysis_ai, roadmap or "
            "roadmap_ai), a Ticket with read_ticket, the older notes with read_notes."
        ),
    }


# --- read_document -------------------------------------------------------------------------------


def text_page(content: str, start_line: int) -> ToolResult:
    """Numbered lines from ``start_line`` until the page holds ``PAGE_CHARS`` characters; a single
    line longer than a page is cut and still counts as read."""
    lines = content.splitlines()
    total = len(lines)
    if start_line > max(total, 1):
        raise ValidationFailure(
            f"start_line {start_line} is past the end: the document has {total} lines",
            details={"argument": "start_line", "lines": total},
        )
    page: list[str] = []
    used = 0
    last = start_line - 1
    for number in range(start_line, total + 1):
        line = f"{number}\t{lines[number - 1]}"
        if page and used + len(line) + 1 > PAGE_CHARS:
            break
        page.append(line[:PAGE_CHARS])
        used += len(page[-1]) + 1
        last = number
    return {
        "lines": f"{start_line}-{last} of {total}" if total else "0 of 0",
        "text": "\n".join(page),
        "continue_from": last + 1 if last < total else None,
    }


def _is_object(value: JsonValue) -> TypeIs[dict[str, JsonValue]]:
    return isinstance(value, dict)


def _objects(value: JsonValue) -> list[dict[str, JsonValue]]:
    return [entry for entry in value if _is_object(entry)] if isinstance(value, list) else []


def _picked(source: dict[str, JsonValue], *keys: str) -> dict[str, JsonValue]:
    return {key: source[key] for key in keys if key in source}


def _count(source: dict[str, JsonValue], key: str) -> int:
    value = source.get(key)
    return len(value) if isinstance(value, list) else 0


def analysis_outline(payload: dict[str, JsonValue]) -> ToolResult:
    recommendation = payload.get("recommendation")
    return {
        "outcome": payload.get("outcome"),
        "findings": [
            _picked(finding, "id", "title", "category")
            for finding in _objects(payload.get("findings"))
        ],
        "open_questions": payload.get("open_questions", []),
        "recommendation_characters": len(recommendation) if isinstance(recommendation, str) else 0,
        "counts": {
            key: _count(payload, key)
            for key in ("scope", "non_goals", "assumptions", "options", "verification", "sources")
        },
    }


def roadmap_outline(payload: dict[str, JsonValue]) -> ToolResult:
    return {
        "summary": payload.get("summary"),
        "phases": [
            {
                **_picked(phase, "id", "number", "name"),
                "tickets": [
                    _picked(ticket, "id", "key", "title", "summary")
                    for ticket in _objects(phase.get("tickets"))
                ],
            }
            for phase in _objects(payload.get("phases"))
        ],
    }


def structured_item(kind: str, payload: dict[str, JsonValue], item: str) -> ToolResult:
    """One finding of the analysis, or one Phase or Ticket of the RoadMap, in full."""
    if kind == "analysis_ai":
        candidates = {str(entry.get("id")): entry for entry in _objects(payload.get("findings"))}
        label = "finding"
    else:
        candidates = {}
        for phase in _objects(payload.get("phases")):
            candidates[str(phase.get("id"))] = phase
            for ticket in _objects(phase.get("tickets")):
                candidates[str(ticket.get("id"))] = {**ticket, "phase_id": phase.get("id")}
        label = "Phase or Ticket"
    if item not in candidates:
        raise NotFound(
            f"No {label} {item} in this {kind} revision",
            details={"item": item, "items": list(candidates)},
        )
    return {"item": candidates[item]}


def read_document(
    services: DocumentReading, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    kind = _require(args, "kind")
    if kind not in DOCUMENT_KINDS:
        raise ValidationFailure(
            "kind must be one of " + ", ".join(DOCUMENT_KINDS),
            details={"argument": "kind", "allowed": list(DOCUMENT_KINDS)},
        )
    view = _text(args.get("view")) or "text"
    if view not in VIEWS:
        raise ValidationFailure(
            "view must be text or structured", details={"argument": "view", "allowed": list(VIEWS)}
        )
    document = services.loop_document.documents(board_id, loop_id)["documents"][kind]
    answer: ToolResult = {
        "kind": kind,
        "view": view,
        "state": document["state"],
        "revision_id": document["current_revision_id"],
        "revision_number": document["current_revision_number"],
    }
    if document["current_revision_id"] is None:
        return answer | {"empty": True, "next_step": f"This Loop has no {kind} yet."}
    if view == "text":
        start = _whole_number(args, "start_line", default=1, maximum=MAX_START_LINE)
        return answer | text_page(document["current_content"] or "", start)
    payload = document["current_payload"]
    if kind not in ("analysis_ai", "roadmap_ai") or not _is_object(payload):
        raise ValidationFailure(
            "Only analysis_ai and roadmap_ai have a structured view; read this one as text",
            details={"argument": "view", "kind": kind},
        )
    item = _text(args.get("item"))
    if item is not None:
        return answer | structured_item(kind, payload, item)
    outline = analysis_outline(payload) if kind == "analysis_ai" else roadmap_outline(payload)
    return answer | {
        "outline": outline,
        "next_step": "Read one finding, Phase or Ticket in full with item set to its id.",
    }


def document_tools(board_id: ArgumentSchema, loop_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entries of the Loop overview and of reading one document."""
    return [
        AgentTool(
            name="read_loop",
            description=(
                "Read one Loop as an overview: its goal and stage, whether execution is allowed, "
                "each document's state and size (not its text), the Phases, the columns, one "
                "short row per Ticket with its summary, and the newest notes. Read a document "
                "with read_document and a Ticket with read_ticket."
            ),
            scopes=("loops:read",),
            input_schema=object_schema(
                {"board_id": board_id, "loop_id": loop_id}, required=["board_id", "loop_id"]
            ),
            handler=read_loop,
        ),
        AgentTool(
            name="read_document",
            description=(
                "Read one of a Loop's documents (info, analysis, analysis_ai, roadmap or "
                f"roadmap_ai). As text it answers numbered lines, at most {PAGE_CHARS} "
                "characters, with continue_from for the rest. analysis_ai and roadmap_ai also "
                "have a structured view: an outline of the findings or the Phases and Tickets, "
                "and one of them in full with item."
            ),
            scopes=("loops:read",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "loop_id": loop_id,
                    "kind": string_argument(
                        "info, analysis, analysis_ai, roadmap or roadmap_ai"
                    ),
                    "view": string_argument("Optional: text (default) or structured"),
                    "start_line": {"type": "number", "minimum": 1},
                    "item": string_argument(
                        "Optional, with view structured: a finding, Phase or Ticket id"
                    ),
                },
                required=["board_id", "loop_id", "kind"],
            ),
            handler=read_document,
        ),
    ]


__all__ = [
    "PAGE_CHARS",
    "DocumentReading",
    "LoopReading",
    "analysis_outline",
    "document_summary",
    "document_tools",
    "read_document",
    "read_loop",
    "roadmap_outline",
    "structured_item",
    "text_page",
]
