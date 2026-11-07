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
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field, StringConstraints

from .common import Id, StrictModel

BriefKind = Literal["analysis", "roadmap"]
BRIEF_KINDS: tuple[str, ...] = get_args(BriefKind)
Verdict = Literal["yes", "yes_with_conditions", "no", "unclear"]
VERDICTS: tuple[str, ...] = get_args(Verdict)
ObstacleLevel = Literal["business", "technical", "security", "legal", "people_time"]
OBSTACLE_LEVELS: tuple[str, ...] = get_args(ObstacleLevel)


# Visible text: stripped, never empty, at most so many characters.
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text300 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Text600 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Text800 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
FindingRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
FindingRefs = Annotated[list[FindingRef], Field(max_length=20)]


class BriefObstacle(StrictModel):
    level: ObstacleLevel
    text: Text300
    finding_ids: FindingRefs = Field(default_factory=list[str])


class BriefPoint(StrictModel):
    text: Text200
    finding_ids: FindingRefs = Field(default_factory=list[str])


class BriefDecision(StrictModel):
    question: Text200
    finding_ids: FindingRefs = Field(default_factory=list[str])


class HumanBrief(StrictModel):
    """The analysis for people. Its items together name every finding of a material category or
    of category ``decision`` in ``finding_ids``; an obstacle is listed only when it exists."""

    schema_version: int = Field(default=1, ge=1, le=1)
    obstacles: list[BriefObstacle] = Field(
        default_factory=list[BriefObstacle],
        max_length=8,
        description="What stands in the way, at any level; only obstacles that exist",
    )
    pros: list[BriefPoint] = Field(default_factory=list[BriefPoint], max_length=5)
    cons: list[BriefPoint] = Field(default_factory=list[BriefPoint], max_length=5)
    decisions: list[BriefDecision] = Field(
        default_factory=list[BriefDecision],
        max_length=8,
        description="What a person must decide, each as a question",
    )
    verdict: Verdict = Field(description="Can it be done")
    verdict_reason: Text300 = Field(description="One sentence why")
    summary: Text600 = Field(description="The highlights in two or three sentences")
    recommendation: Text800 = Field(description="One paragraph")


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
    "VERDICTS",
    "BriefDecision",
    "BriefKind",
    "BriefObstacle",
    "BriefPart",
    "BriefPhaseStep",
    "BriefPoint",
    "BriefRisk",
    "BriefWrite",
    "FindingRef",
    "HumanBrief",
    "ObstacleLevel",
    "RoadmapBrief",
    "Verdict",
]
