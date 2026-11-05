"""``loop_summaries``: where each Loop of a board stands and what it waits for, one row a Loop.

A row is computed from what the Loop already records (its stage, its documents' states, its
Tickets' readiness and the columns' counts), never written by anyone, so it is never older than
the Loop. ``next`` says in one sentence what has to happen now and ``waiting_on`` who does it: a
``person`` (a decision only a signed-in person may make, or a Ticket a person must do), an
``agent`` (work a worker key or a board agent can do), ``anyone`` or ``nobody`` (a Loop that is
finished). The documents, the Tickets and the notes themselves are read with ``read_loop``,
``list_tickets`` and ``read_document``.

The handler is public and typed on the attributes of the composition root it uses, so a unit test
runs it with the real services on the typed fakes. Its catalogue entry is built here too
(``loop_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..schemas.loops import DOCUMENT_KINDS, LOOP_STAGES
from .agent_tools_read import ToolArguments, ToolResult, _require, _text
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .lists import ListEntry, ListService
    from .loops import LoopEntry, LoopService
    from .plan_views import LoopReadiness

type WaitingOn = Literal["person", "agent", "anyone", "nobody"]

GOAL_CHARS: Final = 280
"""The most of a Loop's goal a row shows; read_loop shows the whole goal."""
_FINISHED: Final = ("completed", "cancelled")


class LoopSummarising(Protocol):
    """What ``loop_summaries`` uses of the composition root."""

    @property
    def loop(self) -> LoopService: ...

    @property
    def list(self) -> ListService: ...


@dataclass(frozen=True, slots=True)
class TicketCounts:
    """A Loop's open Tickets by what they wait for."""

    total: int = 0
    completed: int = 0
    for_agent: int = 0  # ready, and not a person's
    for_person: int = 0  # ready, and a person must do it
    waiting: int = 0  # not ready: an earlier Ticket or Phase is not done


def ticket_counts(readiness: LoopReadiness) -> TicketCounts:
    """The planned Tickets by readiness, plus the ones added outside the plan (archived ones left
    out), which never wait for anything."""
    items = readiness["items"]
    unplanned = [ticket for ticket in readiness["unplanned"] if ticket["archived_at"] is None]
    planned = [item for item in items if item["completed_at"] is None]
    return TicketCounts(
        total=len(items) + len(unplanned),
        completed=len(items)
        - len(planned)
        + sum(1 for ticket in unplanned if ticket["completed_at"] is not None),
        for_agent=sum(1 for ticket in unplanned if ticket["completed_at"] is None)
        + sum(1 for item in planned if item["ready"] and not item["human_action_required"]),
        for_person=sum(1 for item in planned if item["ready"] and item["human_action_required"]),
        waiting=sum(1 for item in planned if not item["ready"]),
    )


def _tickets(count: int, one: str, many: str) -> str:
    """``1 Ticket is ready`` or ``3 Tickets are ready``: the count and the verb that agrees."""
    return f"1 Ticket {one}" if count == 1 else f"{count} Tickets {many}"


def _review(name: str, states: list[str]) -> tuple[str, WaitingOn]:
    """A document waiting for its review: asked to change, out of date, or ready for a person."""
    if "changes_requested" in states:
        return f"A person asked for changes to the {name}: hand in a new one.", "agent"
    if "stale" in states:
        return f"The {name} is out of date with its inputs: hand in a new one.", "agent"
    if all(state == "empty" for state in states):
        return f"The {name} is not written yet.", "agent"
    return f"A person reviews the {name} and approves it or asks for changes.", "person"


def next_step(
    entry: LoopEntry, readiness: LoopReadiness, counts: TicketCounts
) -> tuple[str, WaitingOn]:
    """What has to happen next in a Loop, in one sentence, and who does it."""
    stage = entry["stage"]
    states = {kind: entry["documents"][kind]["state"] for kind in DOCUMENT_KINDS}
    if stage in _FINISHED:
        return f"Nothing: the Loop is {stage} and read-only.", "nobody"
    if stage == "draft":
        if states["info"] == "empty":
            return "Write the Loop's Info: what should change and why.", "person"
        return "Ask for the analysis (run_analysis) or hand one in (write_analysis).", "agent"
    if stage == "analysis_review":
        return _review("analysis", [states["analysis_ai"], states["analysis"]])
    if stage == "planning":
        return "Ask for the RoadMap (run_roadmap) or hand one in (write_roadmap).", "agent"
    if stage == "roadmap_review":
        return _review("RoadMap", [states["roadmap_ai"], states["roadmap"]])
    if stage == "replanning":
        return "The Info changed after planning: the RoadMap is planned again.", "agent"
    if stage == "awaiting_qa":
        return "A person accepts or rejects the result in QA.", "person"
    blocked = readiness["blocked_reason"]
    if blocked is not None:
        return blocked["message"], "person"
    if counts.for_agent:
        return _tickets(counts.for_agent, "can", "can") + " be worked on now.", "agent"
    if counts.for_person:
        ready = _tickets(counts.for_person, "is ready and needs", "are ready and need")
        return f"{ready} a person.", "person"
    if counts.waiting:
        return _tickets(counts.waiting, "waits", "wait") + " for earlier work to be done.", "anyone"
    return "Every Ticket is done: a person accepts the implementation.", "person"


def _document(entry: LoopEntry, kind: str) -> str:
    """A document's state and current revision in a few words, e.g. ``approved r12``."""
    document = entry["documents"][kind]
    current = document["current"]
    return (
        document["state"]
        if current is None
        else f"{document['state']} r{current['revision_number']}"
    )


def _goal(goal: str) -> str:
    text = " ".join(goal.split())
    return text if len(text) <= GOAL_CHARS else text[: GOAL_CHARS - 1].rstrip() + "…"


def loop_row(entry: LoopEntry, readiness: LoopReadiness, columns: list[ListEntry]) -> ToolResult:
    """One Loop as ``loop_summaries`` shows it."""
    counts = ticket_counts(readiness)
    sentence, waiting_on = next_step(entry, readiness, counts)
    return {
        "id": entry["id"],
        "key": entry["key"],
        "name": entry["name"],
        "goal": _goal(entry["goal"]),
        "stage": entry["stage"],
        "next": sentence,
        "waiting_on": waiting_on,
        "execution_allowed": readiness["execution_allowed"],
        "tickets": {
            "total": counts.total,
            "completed": counts.completed,
            "ready_for_agent": counts.for_agent,
            "ready_for_person": counts.for_person,
            "waiting": counts.waiting,
            "by_column": {column["name"]: column["card_count"] for column in columns},
        },
        "documents": {kind: _document(entry, kind) for kind in DOCUMENT_KINDS},
    }


def loop_summaries(
    services: LoopSummarising, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    stage = _text(args.get("stage"))
    if stage is not None and stage not in LOOP_STAGES:
        raise ValidationFailure(
            "stage must be one of " + ", ".join(LOOP_STAGES),
            details={"argument": "stage", "allowed": list(LOOP_STAGES)},
        )
    include_completed = args.get("include_completed") is True or stage in _FINISHED
    loops = services.loop.list(board_id, include_completed=include_completed, stage=stage)
    rows = [
        loop_row(
            entry,
            services.loop.readiness(board_id, entry["id"]),
            services.list.list(board_id, entry["id"]),
        )
        for entry in loops
    ]
    return {
        "board_id": board_id,
        "loops": rows,
        "count": len(rows),
        "next_step": (
            "list_tickets with a loop_id (or key) lists its Tickets, narrowed by column, "
            "assignee me or ready; read_loop gives one Loop's documents, Phases and notes."
        ),
    }


def loop_tools(board_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entry of the Loop summaries."""
    return [
        AgentTool(
            name="loop_summaries",
            description=(
                "Say where each Loop of a board stands, one row a Loop: its goal and stage, what "
                "has to happen next and who does it (a person, an agent, anyone or nobody), its "
                "Tickets by what they wait for and by column, and each document's state. Open "
                "Loops unless include_completed is true."
            ),
            scopes=("loops:read",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "stage": string_argument("Optional: only Loops in this stage"),
                    "include_completed": {
                        "type": "boolean",
                        "description": "Also completed and cancelled Loops",
                    },
                },
                required=["board_id"],
            ),
            handler=loop_summaries,
        ),
    ]


__all__ = [
    "GOAL_CHARS",
    "LoopSummarising",
    "TicketCounts",
    "WaitingOn",
    "loop_row",
    "loop_summaries",
    "loop_tools",
    "next_step",
    "ticket_counts",
]
