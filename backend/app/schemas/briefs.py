"""The decision brief: what a person reads of an analysis or a RoadMap, as structure.

A person who decides whether work goes ahead does not read a rewrite of the technical analysis. The
brief answers what they ask: can it be done, what stands in the way, the highlights for and against,
what they must decide, and what is recommended. The technical revision (``analysis_ai``,
``roadmap_ai``) stays complete and unchanged beside it.

The ids in ``finding_ids``, ``phase_ids`` and ``ticket_ids`` carry the traceability back to the
technical revision; they are never part of the visible text, which the server refuses when it
holds an id, a file path or code (``services/loop_documents_human``). Field order is the order a
model writes in, evidence before judgement (the comment on ``SCHEMAS`` in
``services/loop_generation_prompts``): the obstacles and the highlights come before the verdict,
and the summary and the recommendation last. The rendered view puts the verdict first.

The analysis brief is a sign (``services/loop_documents_human_limits``): the verdict in one line,
at most three reasons, each question on one line, how big the work is. Its limits are tighter than
what this model parses, on purpose: a brief stored before the sign existed (more obstacles, longer
text, no ``verdict_line`` or ``size``) is still read, and the server refuses a new one that breaks
the sign when it is handed in (``422 brief_invalid``). The JSON schema a writer is shown carries
the sign's limits (``json_schema_extra``), so a model and a worker see what is accepted.
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import ConfigDict, Field, StringConstraints
from pydantic.config import JsonDict, JsonValue

from .common import Id, StrictModel

BriefKind = Literal["analysis", "roadmap"]
BRIEF_KINDS: tuple[str, ...] = get_args(BriefKind)
Verdict = Literal["yes", "yes_with_conditions", "no", "unclear"]
VERDICTS: tuple[str, ...] = get_args(Verdict)
ObstacleLevel = Literal["business", "technical", "security", "legal", "people_time"]
OBSTACLE_LEVELS: tuple[str, ...] = get_args(ObstacleLevel)
SizeKind = Literal["small", "medium", "large"]
SIZE_KINDS: tuple[str, ...] = get_args(SizeKind)

# What the sign accepts of a new analysis brief, as the schema a writer is shown says it; the check
# in ``services/loop_documents_human_limits`` holds a hand-in to the same numbers.
SIGN_MAX_ITEMS = 3
SIGN_MAX_DECISIONS = 5
SIGN_MAX_CHARS = 140
SIGN_MAX_VERDICT_WORDS = 20


# Visible text: stripped, never empty, at most so many characters.
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text300 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Text600 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Text800 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
FindingRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
FindingRefs = Annotated[list[FindingRef], Field(max_length=20)]
# Text a brief written before the sign may lack: stripped, possibly empty.
OptionalText300 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
_SIGN_TEXT: JsonDict = {"maxLength": SIGN_MAX_CHARS}


class BriefObstacle(StrictModel):
    level: ObstacleLevel
    text: Text300 = Field(json_schema_extra=_SIGN_TEXT)
    finding_ids: FindingRefs = Field(default_factory=list[str])


class BriefPoint(StrictModel):
    text: Text200 = Field(json_schema_extra=_SIGN_TEXT)
    finding_ids: FindingRefs = Field(default_factory=list[str])


class BriefDecision(StrictModel):
    question: Text200 = Field(
        description="One line: the question a person answers", json_schema_extra=_SIGN_TEXT
    )
    finding_ids: FindingRefs = Field(default_factory=list[str])


class BriefSize(StrictModel):
    """How big the work is: a kind a person can compare, and one sentence why."""

    kind: SizeKind
    text: Text300 = Field(
        description="One sentence: what makes it that size", json_schema_extra=_SIGN_TEXT
    )


class HumanBrief(StrictModel):
    """The analysis for people. Its items together name every finding of a material category or
    of category ``decision`` in ``finding_ids``; an obstacle is listed only when it exists."""

    schema_version: int = Field(default=1, ge=1, le=1)
    obstacles: list[BriefObstacle] = Field(
        default_factory=list[BriefObstacle],
        max_length=8,
        description="Why: what stands in the way, at any level; only obstacles that exist",
        json_schema_extra={"maxItems": SIGN_MAX_ITEMS},
    )
    pros: list[BriefPoint] = Field(
        default_factory=list[BriefPoint],
        max_length=5,
        json_schema_extra={"maxItems": SIGN_MAX_ITEMS},
    )
    cons: list[BriefPoint] = Field(
        default_factory=list[BriefPoint],
        max_length=5,
        json_schema_extra={"maxItems": SIGN_MAX_ITEMS},
    )
    decisions: list[BriefDecision] = Field(
        default_factory=list[BriefDecision],
        max_length=8,
        description="What a person must decide, each as a question on one line",
        json_schema_extra={"maxItems": SIGN_MAX_DECISIONS},
    )
    # None only in a brief written before the sign; a new one says it (the check refuses none).
    size: BriefSize | None = Field(default=None, description="How big the work is")
    verdict: Verdict = Field(description="Can it be done")
    verdict_line: OptionalText300 = Field(
        default="",
        description=f"The verdict in one line of at most {SIGN_MAX_VERDICT_WORDS} words",
        json_schema_extra={"minLength": 1},
    )
    verdict_reason: Text300 = Field(description="One sentence why")
    summary: Text600 = Field(description="The highlights in two or three sentences")
    recommendation: Text800 = Field(description="One paragraph")


# What a new analysis brief must hold beyond the parsed model's required fields: the sign's size
# and verdict line. HumanBrief keeps them optional, so a brief stored before the sign still reads.
WRITER_REQUIRED = ("verdict_line", "size")


def _writer_schema(schema: JsonDict) -> None:
    """The schema a writer is shown: ``WRITER_REQUIRED`` required, and the size an object, never
    null. A model follows the schema it is given; a field it sees as optional it may leave out, and
    the sign check then refuses the brief however often it is asked to repair it."""
    required = schema.get("required")
    names: list[JsonValue] = list(required) if isinstance(required, list) else []
    names.extend(name for name in WRITER_REQUIRED if name not in names)
    schema["required"] = names
    properties = schema.get("properties")
    size = properties.get("size") if isinstance(properties, dict) else None
    options = size.get("anyOf") if isinstance(size, dict) else None
    if isinstance(properties, dict) and isinstance(size, dict) and isinstance(options, list):
        # The reference pydantic wrote, without the null beside it: its own ref is resolved later.
        (ref,) = [option for option in options if option != {"type": "null"}]
        if isinstance(ref, dict):
            properties["size"] = {**ref, "description": size.get("description")}


class HumanBriefWriter(HumanBrief):
    """The analysis brief as a writer is shown it (the generation's schema, a worker's
    ``write_brief``): the same fields, with the sign's size and verdict line required. A hand-in
    is still read as ``HumanBrief`` and held to the sign by its check."""

    model_config = ConfigDict(json_schema_extra=_writer_schema)


class BriefPhaseStep(StrictModel):
    phase_id: Id
    what_happens: Text300
    done_when: Text200


class BriefPart(StrictModel):
    text: Text200
    phase_ids: list[Id] = Field(default_factory=list[str], max_length=30)
    ticket_ids: list[Id] = Field(default_factory=list[str], max_length=100)


class BriefRisk(StrictModel):
    text: Text200
    phase_ids: list[Id] = Field(default_factory=list[str], max_length=30)


class RoadmapBrief(StrictModel):
    """The RoadMap for people: every Phase in ``order`` exactly once, and every Ticket a person
    must do (``required_actor: human``) in ``your_part``."""

    schema_version: int = Field(default=1, ge=1, le=1)
    order: list[BriefPhaseStep] = Field(min_length=1, max_length=30)
    your_part: list[BriefPart] = Field(
        default_factory=list[BriefPart],
        max_length=12,
        description="What the person must do themselves, with the Tickets it concerns",
    )
    could_block: list[BriefRisk] = Field(default_factory=list[BriefRisk], max_length=8)
    summary: Text600


class BriefWrite(StrictModel):
    """A brief for the current technical revision of a scope, written by a person or a worker."""

    kind: BriefKind
    brief: HumanBrief | RoadmapBrief
    expected_revision_id: Id | None = Field(
        default=None,
        description=(
            "The technical revision (analysis_ai or roadmap_ai) the brief was written from; a "
            "mismatch returns document_stale"
        ),
    )


__all__ = [
    "BRIEF_KINDS",
    "OBSTACLE_LEVELS",
    "SIGN_MAX_CHARS",
    "SIGN_MAX_DECISIONS",
    "SIGN_MAX_ITEMS",
    "SIGN_MAX_VERDICT_WORDS",
    "SIZE_KINDS",
    "VERDICTS",
    "BriefDecision",
    "BriefKind",
    "BriefObstacle",
    "BriefPart",
    "BriefPhaseStep",
    "BriefPoint",
    "BriefRisk",
    "BriefSize",
    "BriefWrite",
    "FindingRef",
    "HumanBrief",
    "ObstacleLevel",
    "RoadmapBrief",
    "SizeKind",
    "Verdict",
]
