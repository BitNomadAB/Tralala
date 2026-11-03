"""The worker tools that hand in a Loop's analysis and RoadMap (``write_analysis``,
``write_roadmap``).

A worker writes its own analysis and plan, and they go through the one route Tralala already has
for a candidate, ``LoopDocumentService.submit_candidate``: the same schemas (``AnalysisPayload``,
``PlanPayload``), the same validation, the same rendering of the human view and the same approval
by a person. The tools only make that route usable for a model:

- the payload is parsed here, so a schema error answers one ``loc: message`` line per error;
- a Phase or Ticket id that is not a UUID (``p1``, ``t3``) becomes ``uuid5`` of the Loop and the id,
  so a model can write readable ids and a second submission with the same ids keeps the same
  Phases and Tickets; an error about an id names the id the model wrote;
- the revision records who handed it in and that it came through MCP.

A token never replaces an approved analysis or RoadMap: ``submit_candidate`` refuses it, so REST
and MCP share the rule. The handlers are public and typed on ``PlanWriting``, the one attribute of
the composition root they use, so a unit test runs them with the real service on the fakes.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, JsonValue, ValidationError

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..schemas.loops import AnalysisPayload, CandidateSubmission, PlanPayload
from .agent_tools_read import ToolArguments, ToolResult, _require, _text
from .loops import DOCUMENT_KINDS

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .loop_documents import LoopDocumentService
    from .loop_documents_views import DocumentsView

# A schema error answers at most this many lines; the count says how many there were.
MAX_ERROR_LINES = 20


class PlanWriting(Protocol):
    """What ``write_analysis`` and ``write_roadmap`` use of the composition root."""

    @property
    def loop_document(self) -> LoopDocumentService: ...


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


# --- handlers ------------------------------------------------------------------------------------


def write_analysis(services: PlanWriting, actor: ActorContext, args: ToolArguments) -> ToolResult:
    """The worker's analysis as the Loop's analysis candidate, both views written."""
    actor.require("loops:generate")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    analysis = parse_payload(AnalysisPayload, args, "analysis")
    submission = _submission(
        {
            "kind": "analysis",
            "analysis": analysis,
            "expected_info_revision_id": _text(args.get("expected_info_revision_id")),
            "provenance": _provenance(actor),
        }
    )
    view = services.loop_document.submit_candidate(actor, board_id, loop_id, submission)
    return {
        **_documents(view, ("info", "analysis_ai", "analysis")),
        # A board agent writes the analysis for people next; without one it stays rendered.
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
    submission = _submission(
        {
            "kind": "roadmap",
            "plan": plan,
            "expected_analysis_revision_id": _text(args.get("expected_analysis_revision_id")),
            "provenance": _provenance(actor),
        }
    )
    try:
        view = services.loop_document.submit_candidate(actor, board_id, loop_id, submission)
    except ValidationFailure as error:
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
        "next_step": (
            "A person reviews the RoadMap in the Loop's RoadMap tab; the approval publishes the "
            "Tickets with their keys, which read_loop then lists."
        ),
    }


__all__ = [
    "MAX_ERROR_LINES",
    "IdMap",
    "PlanWriting",
    "map_plan_ids",
    "parse_payload",
    "payload_errors",
    "write_analysis",
    "write_roadmap",
]
