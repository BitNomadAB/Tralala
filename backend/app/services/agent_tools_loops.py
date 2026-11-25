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

Beside the rows, ``unreported`` names the Tickets on the board the calling key took and has not
reported on since (``CardService.unreported``), whatever the stage asked for, and ``next_step`` then
asks for those reports first; it is empty for a person.

When the next step is a person's decision, the row's ``decision_link`` is the address where the
person takes it (``loop_decision_link``, which ``read_loop`` answers too): approving the analysis or
the RoadMap under review, accepting the implementation once every Ticket is done (a Loop without a
plan closes in that one decision) and accepting or rejecting the result in QA. It is null for
everything else, a Ticket that waits for a person included: ``read_ticket`` links that one.

A draft is offered both paths: a plan, or a first Ticket that starts the Loop without one. A Loop
without a plan whose Tickets are all done waits for the person who closes it in one decision.

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
from .agent_tools_read import (
    ToolArguments,
    ToolResult,
    _require,
    _text,
    report_first,
    tool_decision_link,
    unreported_rows,
)
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from ..core.config import Settings
    from .cards import CardService
    from .decision_links import Decision
    from .lists import ListEntry, ListService
    from .loops import LoopEntry, LoopService
    from .plan_views import LoopReadiness

type WaitingOn = Literal["person", "agent", "anyone", "nobody"]

GOAL_CHARS: Final = 280
"""The most of a Loop's goal a row shows; read_loop shows the whole goal."""
_FINISHED: Final = ("completed", "cancelled")
ALL_DONE: Final = "Every Ticket is done: a person accepts the implementation."
"""``next`` once nothing in a Loop with a plan is left to do: the implementation is a person's to
accept, which sends the Loop to QA."""
ALL_DONE_WITHOUT_PLAN: Final = (
    "Every Ticket is done: a person closes the Loop with one decision; no QA."
)
"""``next`` once every Ticket of a Loop without a plan is done: the same acceptance, which closes
such a Loop."""
# The review stages whose person's step is a decision in the Plan tab, and QA's in the dialog.
_STAGE_DECISIONS: Final[dict[str, Decision]] = {
    "analysis_review": "analysis",
    "roadmap_review": "roadmap",
    "awaiting_qa": "qa",
}


class LoopSummarising(Protocol):
    """What ``loop_summaries`` uses of the composition root."""

    @property
    def loop(self) -> LoopService: ...

    @property
    def list(self) -> ListService: ...

    @property
    def card(self) -> CardService: ...

    @property
    def settings(self) -> Settings: ...


@dataclass(frozen=True, slots=True)
class TicketCounts:
    """A Loop's Tickets by state (``ticket_state``): open ones are ready, need input or are
    blocked, and in a closed Loop what was never done is not done; ``needs_person`` counts what
    waits for a person now (needs input, or ready and a person's task)."""

    total: int = 0
    completed: int = 0
    ready: int = 0
    needs_input: int = 0
    blocked: int = 0
    not_done: int = 0
    needs_person: int = 0


def ticket_counts(readiness: LoopReadiness) -> TicketCounts:
    """The planned Tickets by state, plus the ones added by hand (outside the plan, or every
    Ticket of a Loop without one; archived ones left out), which only their own wait can hold
    up."""
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
        not_done=states.count("not_done"),
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
        # A draft takes either path: a plan, or its first Ticket starts it without one.
        if states["info"] == "empty":
            return (
                "Write the Loop's Info for the planned path, or add a Ticket (create_ticket) for "
                "a small change without a plan.",
                "person",
            )
        return (
            "Ask for the analysis (run_analysis) or hand one in, written to a board agent's "
            "instructions (read_instructions, then write_analysis); or add a Ticket "
            "(create_ticket) for a small change without a plan.",
            "agent",
        )
    if stage == "analysis_review":
        return _review("analysis", [states["analysis_ai"], states["analysis"]])
    if stage == "planning":
        return (
            "Ask for the RoadMap (run_roadmap) or hand one in, written to a board agent's "
            "instructions (read_instructions, then write_roadmap).",
            "agent",
        )
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
    if entry["without_plan"]:
        # Accepting the work of a Loop without a plan closes it: there is no QA to follow.
        return ALL_DONE_WITHOUT_PLAN, "person"
    return ALL_DONE, "person"


def next_decision(
    entry: LoopEntry, readiness: LoopReadiness, counts: TicketCounts
) -> Decision | None:
    """The decision ``next_step`` waits on a person for, read from its answer so the two never
    disagree: the analysis or the RoadMap a person reviews, the result a person accepts or rejects
    in QA, and the implementation a person accepts once every Ticket is done (``ALL_DONE``, or
    ``ALL_DONE_WITHOUT_PLAN`` where that acceptance closes the Loop). None
    when the next step is anyone's, an agent's or nobody's, and when the person's step is not one
    decision of the Loop: writing the Info, answering a Ticket's wait or doing a person's task."""
    sentence, waiting_on = next_step(entry, readiness, counts)
    if waiting_on != "person":
        return None
    decision = _STAGE_DECISIONS.get(entry["stage"])
    if decision is not None:
        return decision
    return "implementation" if sentence in (ALL_DONE, ALL_DONE_WITHOUT_PLAN) else None


def loop_decision_link(
    entry: LoopEntry, readiness: LoopReadiness, *, public_url: str | None
) -> str | None:
    """The address where a person takes the Loop's next decision (``next_decision``), or None.
    ``loop_summaries`` and ``read_loop`` both answer it, so they never point at different places.
    The Loop's id is its row's; ``public_url`` is ``Services.settings.public_url``."""
    decision = next_decision(entry, readiness, ticket_counts(readiness))
    if decision is None:
        return None
    return tool_decision_link(
        decision, board_id=entry["board_id"], loop_id=entry["id"], public_url=public_url
    )


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


def loop_row(
    entry: LoopEntry,
    readiness: LoopReadiness,
    columns: list[ListEntry],
    *,
    public_url: str | None,
) -> ToolResult:
    """One Loop as ``loop_summaries`` shows it."""
    counts = ticket_counts(readiness)
    sentence, waiting_on = next_step(entry, readiness, counts)
    return {
        "id": entry["id"],
        "key": entry["key"],
        "name": entry["name"],
        "goal": _goal(entry["goal"]),
        "stage": entry["stage"],
        "without_plan": entry["without_plan"],
        "next": sentence,
        "waiting_on": waiting_on,
        "decision_link": loop_decision_link(entry, readiness, public_url=public_url),
        "execution_allowed": readiness["execution_allowed"],
        "tickets": {
            "ready": counts.ready,
            "needs_input": counts.needs_input,
            "blocked": counts.blocked,
            "not_done": counts.not_done,
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
    public_url = services.settings.public_url
    rows = [
        loop_row(
            entry,
            services.loop.readiness(board_id, entry["id"]),
            services.list.list(board_id, entry["id"]),
            public_url=public_url,
        )
        for entry in loops
    ]
    unreported = unreported_rows(services.card.unreported(board_id, actor))
    return {
        "board_id": board_id,
        "loops": rows,
        "count": len(rows),
        "unreported": unreported,
        "next_step": report_first(
            unreported,
            "list_tickets with a loop_id (or key) lists its Tickets, narrowed by column, "
            "assignee me, state or needs_person; read_loop gives one Loop's documents, Phases "
            "and notes.",
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
                "anyone or nobody), its Tickets by state (ready, needs_input, blocked, not_done, "
                "completed, total, needs_person) and by column, and each document's state. Open "
                "Loops unless include_completed is true. unreported names the Tickets on the "
                "board this key took and has not reported on yet. without_plan is true for a "
                "Loop that runs its Tickets without a plan, which a person closes in one decision."
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
    "ALL_DONE",
    "ALL_DONE_WITHOUT_PLAN",
    "GOAL_CHARS",
    "LoopSummarising",
    "TicketCounts",
    "WaitingOn",
    "loop_decision_link",
    "loop_row",
    "loop_summaries",
    "loop_tools",
    "next_decision",
    "next_step",
    "ticket_counts",
]
