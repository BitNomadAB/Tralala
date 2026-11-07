"""``loop_summaries``: where each Loop of a board stands and what it waits for, one row a Loop.

A row is computed from what the Loop already records (its stage, its documents' states, its
Tickets' readiness and the columns' counts), never written by anyone, so it is never older than
the Loop. ``next`` says in one sentence what has to happen now and ``waiting_on`` who it waits
for: a ``person`` (a decision only a signed-in person may make, an answer a Ticket waits for, or a
Ticket that is a person's task), an ``agent`` (a document a worker key or a board agent can write:
asking Tralala's agent for an analysis is decision support), ``anyone`` or ``nobody`` (a Loop that
is finished). Delivery never waits on an agent: a person owns every Ticket, and a ready one is
``anyone``'s to take. The Tickets count by state: ready, needs input, blocked, completed, and
``needs_person``. The documents, the Tickets and the notes themselves are read with ``read_loop``,
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
    """A Loop's Tickets by state (``ticket_state``): open ones are ready, need input or are
    blocked; ``needs_person`` counts what waits for a person now (needs input, or ready and a
    person's task)."""

    total: int = 0
    completed: int = 0
    ready: int = 0
    needs_input: int = 0
    blocked: int = 0
    needs_person: int = 0


def ticket_counts(readiness: LoopReadiness) -> TicketCounts:
    """The planned Tickets by state, plus the ones added outside the plan (archived ones left
    out), which only their own wait can hold up."""
    items = readiness["items"]
    unplanned = [ticket for ticket in readiness["unplanned"] if ticket["archived_at"] is None]
    states = [item["state"] for item in items] + [ticket["state"] for ticket in unplanned]
    person_tasks = sum(
        1 for item in items if item["state"] == "ready" and item["human_action_required"]
    )
    needs_input = states.count("needs_input")
    return TicketCounts(
        total=len(states),
        completed=states.count(None),
        ready=states.count("ready"),
        needs_input=needs_input,
        blocked=states.count("blocked"),
        needs_person=needs_input + person_tasks,
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
    # Delivery: a person owns every Ticket, so no sentence here names an agent as the one who
    # does it; a ready Ticket is anyone's to take, in a coding session or not.
    if counts.needs_input:
        waiting = _tickets(counts.needs_input, "waits", "wait")
        return f"{waiting} for a person's decision, information or access.", "person"
    person_tasks = counts.needs_person - counts.needs_input
    if counts.ready > person_tasks:
        return _tickets(counts.ready - person_tasks, "is", "are") + " ready to start.", "anyone"
    if person_tasks:
        ready = _tickets(person_tasks, "is ready and needs", "are ready and need")
        return f"{ready} a person.", "person"
    if counts.blocked:
        blocked = _tickets(counts.blocked, "waits", "wait")
        return f"{blocked} for earlier work or a third party.", "anyone"
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
            "ready": counts.ready,
            "needs_input": counts.needs_input,
            "blocked": counts.blocked,
            "completed": counts.completed,
            "total": counts.total,
            "needs_person": counts.needs_person,
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
            "assignee me, state or needs_person; read_loop gives one Loop's documents, Phases "
            "and notes."
        ),
    }


def loop_tools(board_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entry of the Loop summaries."""
    return [
        AgentTool(
            name="loop_summaries",
            description=(
                "Say where each Loop of a board stands, one row a Loop: its goal and stage, what "
                "has to happen next and who it waits for (a person, an agent for a document, "
                "anyone or nobody), its Tickets by state (ready, needs_input, blocked, completed, "
                "total, needs_person) and by column, and each document's state. Open Loops unless "
                "include_completed is true."
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
