"""The worker tools that hand in a Loop's analysis and RoadMap (``write_analysis``,
``write_roadmap``) and the brief a person reads of either (``write_brief``, or the optional
``brief`` of the other two).

A connected worker may hold its organisation's own sources, policies and decisions that a board
agent does not, so it may write the brief itself: with ``brief`` the candidate's human view is that
brief and no board agent is asked; ``write_brief`` rewrites the brief of the current technical
revision. Either way the brief is held to the rules every brief keeps
(``loop_documents_human``; an analysis brief that breaks its sign answers ``422 brief_invalid``,
one message per field and rule), and over an approval a token is refused (the gate below).

A worker writes its own analysis and plan, and they go through the one route Tralala already has
for a candidate, ``LoopDocumentService.submit_candidate``: the same schemas (``AnalysisPayload``,
``PlanPayload``), the same validation, the same rendering of the human view and the same approval
by a person. The tools only make that route usable for a model:

- the payload is parsed here, so a schema error answers one ``loc: message`` line per error;
- a Phase or Ticket id that is not a UUID (``p1``, ``t3``) becomes ``uuid5`` of the Loop and the id,
  so a model can write readable ids and a second submission with the same ids keeps the same
  Phases and Tickets; an error about an id names the id the model wrote, and so does a refused
  face (``422 face_invalid``, one message per problem naming the Ticket, the field and the rule);
- the revision records who handed it in and that it came through MCP.

A token never replaces an approved analysis or RoadMap: ``submit_candidate`` refuses it, so REST
and MCP share the rule. The handlers are public and typed on ``PlanWriting``, the one attribute of
the composition root they use, so a unit test runs them with the real service on the fakes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, JsonValue, ValidationError

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..schemas.briefs import BRIEF_KINDS, BriefWrite, HumanBrief, HumanBriefWriter, RoadmapBrief
from ..schemas.loops import AnalysisPayload, CandidateSubmission, PlanPayload
from .agent_tools_read import ToolArguments, ToolResult, _require, _text
from .agent_tools_schema import (
    AgentTool,
    ArgumentSchema,
    model_argument,
    object_schema,
    string_argument,
)
from .loop_documents_human_limits import SIGN_QUESTION_EXAMPLE
from .loops import DOCUMENT_KINDS
from .ticket_face import FACE_INVALID, FACE_STEP_BAD, FACE_STEP_GOOD

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .loop_documents import LoopDocumentService
    from .loop_documents_views import DocumentsView
    from .loop_generation import LoopGenerationService

# A schema error answers at most this many lines; the count says how many there were.
MAX_ERROR_LINES = 20


class PlanWriting(Protocol):
    """What ``write_analysis`` and ``write_roadmap`` use of the composition root."""

    @property
    def loop_document(self) -> LoopDocumentService: ...


class PlanInstructions(Protocol):
    """What ``read_instructions`` uses of the composition root."""

    @property
    def loop_generation(self) -> LoopGenerationService: ...


# How a worker reads the instructions of a board agent: the same text, its own means.
INSTRUCTIONS_NOTE = (
    "These are the instructions a board agent works under for this purpose, word for word: the "
    "role of the agent the Loop would use, the rules and the JSON schema. Follow them as they are "
    "written. Where they speak of the request, the supplied context, the tools list_files, "
    "read_file and search, or answering with the JSON object alone, use your own means: read the "
    "Loop with read_loop and read_document, and the code where you work. examples, when present, "
    "are the Ticket faces the owner approved last, which a board agent is shown as the style to "
    "follow."
)
HAND_IN = {
    "analysis": "Hand the analysis in with write_analysis, as its analysis argument.",
    "analysis_human": (
        "Hand the brief in as write_analysis's brief, or later with write_brief (kind analysis)."
    ),
    "roadmap": (
        "Hand the RoadMap in with write_roadmap, as its plan argument; ids may be short (p1, t1) "
        "and become stable UUIDs."
    ),
    "roadmap_human": (
        "Hand the brief in as write_roadmap's brief, or later with write_brief (kind roadmap)."
    ),
}


# The ids a model wrote that became UUIDs: ``{"phases": {"p1": ...}, "tickets": {"t1": ...}}``.
type IdMap = dict[str, dict[str, str]]


def payload_errors(argument: str, error: ValidationError) -> list[str]:
    """One ``loc: message`` line per error, the location starting at the argument's name."""
    return [
        ".".join(str(part) for part in (argument, *detail["loc"])) + f": {detail['msg']}"
        for detail in error.errors()[:MAX_ERROR_LINES]
    ]


def parse_payload[Model: BaseModel](
    model: type[Model], args: ToolArguments, argument: str
) -> Model:
    """The argument as the schema model; a JSON object, or the same object written as a string."""
    value = args.get(argument)
    if value is None:
        raise ValidationFailure(f"{argument} is required", details={"argument": argument})
    try:
        if isinstance(value, str):
            return model.model_validate_json(value)
        return model.model_validate(value)
    except ValidationError as error:
        lines = payload_errors(argument, error)
        raise ValidationFailure(
            f"{argument} does not match its schema: " + "; ".join(lines),
            details={"argument": argument, "errors": lines, "error_count": error.error_count()},
        ) from None


def _submission(fields: Mapping[str, object]) -> CandidateSubmission:
    try:
        return CandidateSubmission.model_validate(fields)
    except ValidationError as error:
        lines = payload_errors("submission", error)
        raise ValidationFailure(
            "The submission does not match its schema: " + "; ".join(lines),
            details={"errors": lines, "error_count": error.error_count()},
        ) from None


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _namespace(loop_id: str) -> uuid.UUID:
    """The Loop's id as the namespace of its plan ids. A loop id that is not a UUID finds no Loop
    in the service, so it only has to give a deterministic namespace."""
    if _is_uuid(loop_id):
        return uuid.UUID(loop_id)
    return uuid.uuid5(uuid.NAMESPACE_URL, f"tralala-loop:{loop_id}")


def map_plan_ids(plan: PlanPayload, loop_id: str) -> tuple[PlanPayload, IdMap]:
    """The plan with every Phase and Ticket id that is not a UUID replaced by ``uuid5(loop,
    "phase:<id>")`` or ``uuid5(loop, "ticket:<id>")``, references included; a UUID is kept."""
    namespace = _namespace(loop_id)
    id_map: IdMap = {"phases": {}, "tickets": {}}

    def mapped(value: str, kind: str) -> str:
        if _is_uuid(value):
            return value
        new = str(uuid.uuid5(namespace, f"{kind}:{value}"))
        id_map["phases" if kind == "phase" else "tickets"][value] = new
        return new

    phases = [
        phase.model_copy(
            update={
                "id": mapped(phase.id, "phase"),
                "prerequisite_phase_ids": [
                    mapped(value, "phase") for value in phase.prerequisite_phase_ids
                ],
                "prerequisite_ticket_ids": [
                    mapped(value, "ticket") for value in phase.prerequisite_ticket_ids
                ],
                "tickets": [
                    ticket.model_copy(
                        update={
                            "id": mapped(ticket.id, "ticket"),
                            "prerequisite_phase_ids": [
                                mapped(value, "phase") for value in ticket.prerequisite_phase_ids
                            ],
                            "prerequisite_ticket_ids": [
                                mapped(value, "ticket")
                                for value in ticket.prerequisite_ticket_ids
                            ],
                        }
                    )
                    for ticket in phase.tickets
                ],
            }
        )
        for phase in plan.phases
    ]
    return plan.model_copy(update={"phases": phases}), id_map


def _original_ids(details: Mapping[str, object], id_map: IdMap) -> dict[str, object]:
    """An error's details with each generated UUID replaced by the id the model wrote."""
    written = {new: old for ids in id_map.values() for old, new in ids.items()}
    return {
        key: written.get(value, value) if isinstance(value, str) else value
        for key, value in details.items()
    }


def _written_ids(text: str, id_map: IdMap, *, in_json: bool = False) -> str:
    """``text`` with each generated UUID replaced by the id the model wrote (escaped as a JSON
    string's content, ``in_json``)."""
    for ids in id_map.values():
        for old, new in ids.items():
            text = text.replace(new, json.dumps(old)[1:-1] if in_json else old)
    return text


def _original_face_error(error: ValidationFailure, id_map: IdMap) -> ValidationFailure:
    """A refused face with every generated UUID in its messages named by the id the model wrote."""
    written: JsonValue = json.loads(
        _written_ids(json.dumps(dict(error.details or {}), default=str), id_map, in_json=True)
    )
    details = dict(written) if isinstance(written, dict) else {}
    return ValidationFailure(_written_ids(error.message, id_map), code=error.code, details=details)


def _provenance(actor: ActorContext) -> dict[str, object]:
    return {
        "submitted": True,
        "through": "mcp",
        "author": actor.actor_name,
        "actor_id": actor.actor_id,
    }


def _documents(view: DocumentsView, kinds: tuple[str, ...]) -> ToolResult:
    documents = view["documents"]
    return {
        "loop_version": view["loop_version"],
        "documents": {
            kind: {
                "state": documents[kind]["state"],
                "revision_id": documents[kind]["current_revision_id"],
                "revision_number": documents[kind]["current_revision_number"],
            }
            for kind in kinds
        },
        "stale_reasons": {
            kind: documents[kind]["stale_reasons"]
            for kind in DOCUMENT_KINDS
            if documents[kind]["stale_reasons"]
        },
    }


def _plan_id(view: DocumentsView) -> str | None:
    payload: JsonValue = view["documents"]["roadmap_ai"]["current_payload"]
    if isinstance(payload, dict):
        plan_id = payload.get("plan_id")
        if isinstance(plan_id, str):
            return plan_id
    return None


def _optional_brief[Model: BaseModel](model: type[Model], args: ToolArguments) -> Model | None:
    return None if args.get("brief") is None else parse_payload(model, args, "brief")


def _brief_answer(view: DocumentsView, kind: str) -> ToolResult:
    """Whether the human view is a brief, and who wrote it."""
    provenance = view["documents"][kind]["current_provenance"]
    return {"written": provenance.get("written") is True, "through": provenance.get("through")}


# --- handlers ------------------------------------------------------------------------------------


def write_analysis(services: PlanWriting, actor: ActorContext, args: ToolArguments) -> ToolResult:
    """The worker's analysis as the Loop's analysis candidate, both views written."""
    actor.require("loops:generate")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    analysis = parse_payload(AnalysisPayload, args, "analysis")
    brief = _optional_brief(HumanBrief, args)
    submission = _submission(
        {
            "kind": "analysis",
            "analysis": analysis,
            "analysis_brief": brief,
            "expected_info_revision_id": _text(args.get("expected_info_revision_id")),
            "provenance": _provenance(actor),
        }
    )
    view = services.loop_document.submit_candidate(actor, board_id, loop_id, submission)
    return {
        **_documents(view, ("info", "analysis_ai", "analysis")),
        "brief": _brief_answer(view, "analysis"),
        # Without your brief, a board agent writes one next; without an agent it stays rendered.
        "human_view": view.get("human_view"),
        "next_step": (
            "A person reviews the analysis in the Loop's Analysis tab. Once it is approved, "
            "write_roadmap plans the work."
        ),
    }


def write_roadmap(services: PlanWriting, actor: ActorContext, args: ToolArguments) -> ToolResult:
    """The worker's RoadMap as the Loop's RoadMap candidate, its plan registered as a draft."""
    actor.require("loops:generate")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    plan, id_map = map_plan_ids(parse_payload(PlanPayload, args, "plan"), loop_id)
    brief = _optional_brief(RoadmapBrief, args)
    submission = _submission(
        {
            "kind": "roadmap",
            "plan": plan,
            "roadmap_brief": brief,
            "expected_analysis_revision_id": _text(args.get("expected_analysis_revision_id")),
            "provenance": _provenance(actor),
        }
    )
    try:
        view = services.loop_document.submit_candidate(actor, board_id, loop_id, submission)
    except ValidationFailure as error:
        if error.code == FACE_INVALID:
            raise _original_face_error(error, id_map) from None
        if error.code != "invalid_dependency_graph" or error.details is None:
            raise
        raise ValidationFailure(
            error.message, code=error.code, details=_original_ids(error.details, id_map)
        ) from None
    return {
        **_documents(view, ("roadmap_ai", "roadmap")),
        "plan": {
            "plan_id": _plan_id(view),
            "phases": len(plan.phases),
            "tickets": sum(len(phase.tickets) for phase in plan.phases),
        },
        "id_map": id_map,
        "brief": _brief_answer(view, "roadmap"),
        "human_view": view.get("human_view"),
        "next_step": (
            "A person reviews the RoadMap in the Loop's RoadMap tab; the approval publishes the "
            "Tickets with their keys, which read_loop then lists."
        ),
    }


def write_brief(services: PlanWriting, actor: ActorContext, args: ToolArguments) -> ToolResult:
    """The worker's brief for people as the human view of the current technical revision."""
    actor.require("loops:generate")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    kind = _require(args, "kind")
    if kind not in BRIEF_KINDS:
        raise ValidationFailure(
            "kind is analysis or roadmap", details={"argument": "kind", "allowed": [*BRIEF_KINDS]}
        )
    brief: HumanBrief | RoadmapBrief = (
        parse_payload(HumanBrief, args, "brief")
        if kind == "analysis"
        else parse_payload(RoadmapBrief, args, "brief")
    )
    write = BriefWrite.model_validate(
        {
            "kind": kind,
            "brief": brief,
            "expected_revision_id": _text(args.get("expected_revision_id")),
        }
    )
    view = services.loop_document.write_brief(actor, board_id, loop_id, write, through="mcp")
    scope = "analysis" if kind == "analysis" else "RoadMap"
    return {
        **_documents(view, (f"{kind}_ai", kind)),
        "brief": _brief_answer(view, kind),
        "next_step": (
            f"A person reads the brief in the Loop's {scope} tab (For people) and decides; "
            "writing a brief approves nothing."
        ),
    }


def read_instructions(
    services: PlanInstructions, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    """The instructions a board agent works under for one purpose, for a worker that writes the
    document itself, with how to use them and where the answer goes."""
    actor.require("loops:generate")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    purpose = _require(args, "purpose")
    view = services.loop_generation.instructions(actor, board_id, loop_id, purpose)
    return {**view, "how_to_use": INSTRUCTIONS_NOTE, "hand_in": HAND_IN[purpose]}


def plan_tools(
    board_id: ArgumentSchema,
) -> tuple[AgentTool, AgentTool, AgentTool, AgentTool]:
    """The catalogue entries of ``read_instructions``, ``write_analysis``, ``write_roadmap`` and
    ``write_brief``."""
    analysis, analysis_definitions = model_argument(
        AnalysisPayload,
        "The analysis as one JSON object, written in the order of its fields: outcome, "
        "scope, findings with technical_detail and plain_language, recommendation and the rest",
    )
    plan, plan_definitions = model_argument(
        PlanPayload,
        "The RoadMap as one JSON object: a summary and the Phases in order with their Tickets; "
        "a Ticket a person must do has required_actor human, a reason and instructions",
    )
    human_brief, human_definitions = model_argument(
        HumanBriefWriter,
        "Optional: your brief for the person who decides (the human view), naming in "
        "finding_ids every risk, blocker, legal, security, question and decision finding; "
        "plain text without ids, paths or code. It is a sign: verdict_line in at most 20 words, "
        "at most 3 obstacles, 3 pros and 3 cons, at most 5 decisions with each question on one "
        "line, and size (small, medium or large, with one sentence); every item at most 140 "
        f'characters. A question, for example: "{SIGN_QUESTION_EXAMPLE}" A brief that breaks the '
        "sign is refused with brief_invalid, one message per field and rule. Without it a board "
        "agent writes one",
    )
    roadmap_brief, roadmap_definitions = model_argument(
        RoadmapBrief,
        "Optional: your brief of the RoadMap for the person who approves it: its goal, what is "
        "true when the plan is done, in one line of at most 20 words, plain text without ids, "
        "paths or code. The page shows the Phases and Tickets from the plan and counts them. "
        "Without it a board agent writes one",
    )
    loop_id = string_argument("Loop identifier from read_board or create_loop")
    read_instructions_tool = AgentTool(
        name="read_instructions",
        description=(
            "Read the instructions a board agent works under before you write an analysis, a "
            "RoadMap or a brief for people yourself: word for word the role of the agent the "
            "Loop would use, the rules and the JSON schema, and for a RoadMap the Ticket faces "
            "the owner approved last as examples. Purpose analysis or roadmap for the document, "
            "analysis_human or roadmap_human for its brief. Your own document is held to the "
            "same schema and checks either way; these instructions make it written the same way."
        ),
        scopes=("loops:generate",),
        input_schema=object_schema(
            {
                "board_id": board_id,
                "loop_id": loop_id,
                "purpose": string_argument("analysis, analysis_human, roadmap or roadmap_human"),
            },
            required=["board_id", "loop_id", "purpose"],
        ),
        handler=read_instructions,
    )
    write_analysis_tool = AgentTool(
        name="write_analysis",
        description=(
            "Hand in your own analysis of a Loop that has Info, in Tralala's structure: the "
            "same schema, validation, rendering and review as an analysis a board agent "
            "writes. Write it to the instructions that agent works under: read_instructions "
            "with purpose analysis, and analysis_human for the brief. technical_detail is for "
            "engineers; plain_language is for a project manager and every risk, blocker, legal, "
            "security or question finding needs it. With brief, your decision brief for people "
            "is the human view; without it a board agent writes one. A person approves it; an "
            "approved analysis is replaced only after that person requests changes or resets "
            "it."
        ),
        scopes=("loops:generate",),
        input_schema=object_schema(
            {
                "board_id": board_id,
                "loop_id": loop_id,
                "analysis": analysis,
                "brief": human_brief,
                "expected_info_revision_id": string_argument(
                    "Optional Info revision id you wrote from (read_loop); a mismatch returns "
                    "document_stale"
                ),
            },
            required=["board_id", "loop_id", "analysis"],
            definitions={**analysis_definitions, **human_definitions},
        ),
        handler=write_analysis,
    )
    write_roadmap_tool = AgentTool(
        name="write_roadmap",
        description=(
            "Hand in your own RoadMap for a Loop whose analysis is approved: the Phases in "
            "order with their Tickets, in the same schema, validation and review as a "
            "generated RoadMap. Write it to the instructions a board agent works under: "
            "read_instructions with purpose roadmap, and roadmap_human for the brief. Ids may "
            "be short (p1, t1): they become stable UUIDs, listed in id_map, so the same ids "
            "keep the same Tickets when you hand it in again; a brief may use the same short "
            "ids. Every Ticket ends with its face for people: "
            "summary of at most 20 words, why and if_skipped in at most 3 sentences each, at "
            "most 3 pros and 3 cons, and 1 to 5 steps saying what changes for the person (a "
            "Ticket that needs more is split), all plain text without file paths, code symbols "
            "or ids. "
            f'Step, good: "{FACE_STEP_GOOD}" Step, bad: "{FACE_STEP_BAD}" '
            "A face that breaks this is refused with face_invalid, one message per Ticket, "
            "field and rule. A person approves it, and the approval publishes the Tickets with "
            "their keys."
        ),
        scopes=("loops:generate",),
        input_schema=object_schema(
            {
                "board_id": board_id,
                "loop_id": loop_id,
                "plan": plan,
                "brief": roadmap_brief,
                "expected_analysis_revision_id": string_argument(
                    "Optional technical analysis (analysis_ai) revision id you planned from; "
                    "a mismatch returns document_stale"
                ),
            },
            required=["board_id", "loop_id", "plan"],
            definitions={**plan_definitions, **roadmap_definitions},
        ),
        handler=write_roadmap,
    )
    write_brief_tool = AgentTool(
        name="write_brief",
        description=(
            "Write the brief for people (the human view) of the Loop's current analysis or "
            "RoadMap, for example from your organisation's own sources: can it be done, what "
            "stands in the way, for and against, what a person must decide. The schema is "
            "write_analysis's or write_roadmap's brief argument; an analysis brief keeps its "
            "sign (see write_analysis) or is refused with brief_invalid, one message per field "
            "and rule. read_instructions with purpose analysis_human or roadmap_human gives the "
            "instructions a board agent writes it to. Over an approved analysis or "
            "RoadMap a person requests changes or resets it first; a brief approves nothing."
        ),
        scopes=("loops:generate",),
        input_schema=object_schema(
            {
                "board_id": board_id,
                "loop_id": loop_id,
                "kind": string_argument("analysis or roadmap"),
                "brief": {
                    "type": "object",
                    "description": (
                        "The brief as one JSON object: the schema of write_analysis's brief for "
                        "analysis, of write_roadmap's brief for roadmap"
                    ),
                },
                "expected_revision_id": string_argument(
                    "Optional technical revision id (analysis_ai or roadmap_ai) you wrote the "
                    "brief from; a mismatch returns document_stale"
                ),
            },
            required=["board_id", "loop_id", "kind", "brief"],
        ),
        handler=write_brief,
    )
    return read_instructions_tool, write_analysis_tool, write_roadmap_tool, write_brief_tool


__all__ = [
    "HAND_IN",
    "INSTRUCTIONS_NOTE",
    "MAX_ERROR_LINES",
    "IdMap",
    "PlanInstructions",
    "PlanWriting",
    "map_plan_ids",
    "parse_payload",
    "payload_errors",
    "plan_tools",
    "read_instructions",
    "write_analysis",
    "write_brief",
    "write_roadmap",
]
