"""The brief a person reads, checked against the technical revision it explains, and stored.

A person and a model read differently. The technical analysis (``analysis_ai``) and the technical
RoadMap (``roadmap_ai``) are structure for engineers and models; the human view (``analysis``,
``roadmap``) is a decision brief (``schemas/briefs.py``): can it be done, what stands in the way,
the highlights for and against, what a person must decide. Until somebody writes one, the human
view is rendered from the structure and says so in its provenance (``rendered``).

Whoever writes a brief (a connected worker over ``/mcp``, a board agent's run, a person), it is
held to the same rules before it is stored:

- **coverage**: the items of an analysis brief together name, in their ``finding_ids``, every
  finding of a material category or of category ``decision``; a RoadMap brief is its goal in one
  line of at most ``GOAL_MAX_WORDS`` words, since the page shows the Phases and Tickets from the
  plan;
- **known ids**: an id the technical analysis does not hold is refused;
- **plain text**: the visible text holds no finding id, no other id, no file path and no code; the
  ids carry the traceability, the text is for people;
- **the sign** (an analysis brief only, ``loop_documents_human_limits``): the verdict in one line,
  at most three reasons, each question on one line, how big the work is.

A brief that breaks the sign is refused with ``422 brief_invalid``, naming the sign's problems and
then the others; one that keeps the sign and breaks another rule with ``422 brief_rejected``, every
problem named, field by field. Everything here is pure except ``store_brief``, which writes the
revision inside the caller's unit of work.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TypedDict

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import Conflict, ValidationFailure, VersionConflict
from ..db.generated.board import LoopDocumentsRow, LoopsRow
from ..repositories.board import BoardRepositories
from ..schemas.briefs import GOAL_MAX_WORDS, HumanBrief, RoadmapBrief
from ..schemas.loops import AnalysisPayload
from .loop_documents_human_limits import refuse_sign, sign_findings
from .loop_documents_render import render_analysis_brief, render_roadmap_brief
from .loop_documents_revisions import invalidate_downstream, log_loop_activity, write_revision
from .plain_text import text_problems, word_count

# The findings a person must be told about; a brief names the decisions as well, since a decision is
# what a person must take.
MATERIAL_FINDING_CATEGORIES = frozenset({"risk", "blocker", "legal", "security", "question"})
BRIEF_FINDING_CATEGORIES = frozenset({*MATERIAL_FINDING_CATEGORIES, "decision"})


class BriefCheck(TypedDict):
    """What a brief got wrong: one sentence per problem, the fields with text to change, the ids
    the technical revision does not hold and the ones the brief leaves out."""

    problems: list[str]
    fields: list[str]
    unknown_ids: list[str]
    missing_ids: list[str]


@dataclass(slots=True)
class _Findings:
    problems: list[str] = field(default_factory=list[str])
    fields: list[str] = field(default_factory=list[str])
    unknown: list[str] = field(default_factory=list[str])
    missing: list[str] = field(default_factory=list[str])

    def wording(self, path: str, problem: str) -> None:
        self.problems.append(f"{path}: {problem}")
        if path not in self.fields:
            self.fields.append(path)

    def result(self) -> BriefCheck:
        return {
            "problems": self.problems,
            "fields": self.fields,
            "unknown_ids": self.unknown,
            "missing_ids": self.missing,
        }


# --- visible text --------------------------------------------------------------------------------


def _analysis_texts(brief: HumanBrief) -> Iterator[tuple[str, str]]:
    yield "verdict_line", brief.verdict_line
    yield "verdict_reason", brief.verdict_reason
    yield "summary", brief.summary
    for index, obstacle in enumerate(brief.obstacles):
        yield f"obstacles[{index}].text", obstacle.text
    for index, point in enumerate(brief.pros):
        yield f"pros[{index}].text", point.text
    for index, point in enumerate(brief.cons):
        yield f"cons[{index}].text", point.text
    for index, decision in enumerate(brief.decisions):
        yield f"decisions[{index}].question", decision.question
    if brief.size is not None:
        yield "size.text", brief.size.text
    yield "recommendation", brief.recommendation


# --- the analysis brief --------------------------------------------------------------------------


def brief_finding_ids(payload: AnalysisPayload) -> list[str]:
    """The findings a brief must name: the material ones and the decisions, in the analysis's
    order."""
    return [
        finding.id for finding in payload.findings if finding.category in BRIEF_FINDING_CATEGORIES
    ]


def named_findings(brief: HumanBrief) -> list[str]:
    """Every finding id the brief's items name, once each, in the order they are named."""
    items = [*brief.obstacles, *brief.pros, *brief.cons, *brief.decisions]
    return list(dict.fromkeys(finding_id for item in items for finding_id in item.finding_ids))


def brief_coverage_missing(brief: HumanBrief, payload: AnalysisPayload) -> list[str]:
    """The findings the brief must name and no item names."""
    named = set(named_findings(brief))
    return [finding_id for finding_id in brief_finding_ids(payload) if finding_id not in named]


def brief_text_problems(brief: HumanBrief, payload: AnalysisPayload) -> list[str]:
    """``field: problem`` for every visible text that is not for people."""
    known = [finding.id for finding in payload.findings]
    return [
        f"{path}: {problem}"
        for path, text in _analysis_texts(brief)
        for problem in text_problems(text, known)
    ]


def check_analysis_brief(brief: HumanBrief, payload: AnalysisPayload) -> BriefCheck:
    found = _Findings()
    known = {finding.id for finding in payload.findings}
    found.unknown = [finding_id for finding_id in named_findings(brief) if finding_id not in known]
    if found.unknown:
        found.problems.append(
            "finding_ids: the technical analysis has no finding " + ", ".join(found.unknown)
        )
    found.missing = brief_coverage_missing(brief, payload)
    if found.missing:
        found.problems.append(
            "finding_ids: no item names " + ", ".join(found.missing) + "; every risk, blocker, "
            "legal, security, question and decision finding must be named by an item"
        )
    ids = [finding.id for finding in payload.findings]
    for path, text in _analysis_texts(brief):
        for problem in text_problems(text, ids):
            found.wording(path, problem)
    return found.result()


# --- the RoadMap brief ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanOutline:
    """What a RoadMap brief is checked against: the Phases (id, number, name) and the Tickets (id,
    key, title, whether a person must do it) of the technical RoadMap, in its order."""

    phases: tuple[tuple[str, int, str], ...]
    tickets: tuple[tuple[str, str, str, bool], ...]


def _text_of(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def plan_outline(plan: Mapping[str, JsonValue]) -> PlanOutline:
    """The outline of a technical RoadMap, from its canonical payload as stored."""
    phases: list[tuple[str, int, str]] = []
    tickets: list[tuple[str, str, str, bool]] = []
    raw_phases = plan.get("phases")
    for phase in raw_phases if isinstance(raw_phases, list) else []:
        if not isinstance(phase, dict):
            continue
        number = phase.get("number")
        phases.append(
            (
                _text_of(phase.get("id")),
                number if isinstance(number, int) else 0,
                _text_of(phase.get("name")),
            )
        )
        raw_tickets = phase.get("tickets")
        tickets.extend(
            (
                _text_of(ticket.get("id")),
                _text_of(ticket.get("key")),
                _text_of(ticket.get("title")),
                ticket.get("required_actor") == "human",
            )
            for ticket in (raw_tickets if isinstance(raw_tickets, list) else [])
            if isinstance(ticket, dict)
        )
    return PlanOutline(tuple(phases), tuple(tickets))


def check_roadmap_brief(brief: RoadmapBrief) -> BriefCheck:
    """The RoadMap brief's goal: one line of at most ``GOAL_MAX_WORDS`` words in plain text. The
    page shows the Phases and Tickets from the plan, so the brief names none of them."""
    found = _Findings()
    words = word_count(brief.goal)
    if words > GOAL_MAX_WORDS:
        found.wording("goal", f"{words} words, at most {GOAL_MAX_WORDS}")
    if len(brief.goal.splitlines()) > 1:
        found.wording("goal", "more than one line; say it in one")
    for problem in text_problems(brief.goal, []):
        found.wording("goal", problem)
    return found.result()


def refuse_problems(check: BriefCheck) -> None:
    """``422 brief_rejected`` naming every problem, or nothing when there is none."""
    if not check["problems"]:
        return
    raise ValidationFailure(
        "The brief was not accepted: " + "; ".join(check["problems"]),
        code="brief_rejected",
        details={
            "problems": [*check["problems"]],
            "fields": [*check["fields"]],
            "unknown_ids": [*check["unknown_ids"]],
            "missing_ids": [*check["missing_ids"]],
        },
    )


# --- storing a brief -----------------------------------------------------------------------------


def _technical(repos: BoardRepositories, loop_id: str, kind: str) -> LoopDocumentsRow:
    technical_kind = f"{kind}_ai"
    technical = repos.documents.current(loop_id, technical_kind)
    if technical is None or not technical.payload_json:
        what = "technical analysis" if kind == "analysis" else "technical RoadMap"
        raise Conflict(
            f"There is no {what} to write a brief for",
            code="document_empty",
            details={"kind": technical_kind},
        )
    return technical


def _payload(row: LoopDocumentsRow) -> dict[str, JsonValue]:
    value: JsonValue = json.loads(row.payload_json or "{}")
    return dict(value) if isinstance(value, dict) else {}


def check_brief(
    brief: HumanBrief | RoadmapBrief, technical: Mapping[str, JsonValue]
) -> BriefCheck:
    """The brief against the technical revision's payload: an analysis or a canonical plan."""
    if isinstance(brief, HumanBrief):
        return check_analysis_brief(brief, AnalysisPayload.model_validate(technical))
    return check_roadmap_brief(brief)


def render_brief(
    brief: HumanBrief | RoadmapBrief, technical: Mapping[str, JsonValue]
) -> str:
    """The brief as Markdown: what the revision's content holds and an export shows."""
    if isinstance(brief, HumanBrief):
        return render_analysis_brief(brief)
    return render_roadmap_brief(brief, len(plan_outline(technical).tickets))


def store_brief(
    repos: BoardRepositories,
    loop: LoopsRow,
    brief: HumanBrief | RoadmapBrief,
    actor: ActorContext,
    *,
    provenance: Mapping[str, object],
    clock: Callable[[], str],
    new_id: Callable[[], str],
    expected_revision_id: str | None = None,
    run_id: str | None = None,
) -> LoopDocumentsRow:
    """The brief as the scope's current human revision, written from the current technical one:
    the brief is its payload and its rendering the content. A brief that breaks a rule is refused
    with every problem named (an analysis brief that breaks the sign as ``brief_invalid``); a new
    brief invalidates what was approved of the scope and after it, as any new revision of the
    human view does."""
    kind = "analysis" if isinstance(brief, HumanBrief) else "roadmap"
    technical = _technical(repos, loop.id, kind)
    if expected_revision_id is not None and expected_revision_id != technical.id:
        raise VersionConflict(
            "The brief was written from a technical revision that is no longer current",
            code="document_stale",
            details={
                "kind": technical.kind,
                "expected_revision_id": expected_revision_id,
                "current_revision_id": technical.id,
            },
        )
    payload = _payload(technical)
    check = check_brief(brief, payload)
    if isinstance(brief, HumanBrief):
        refuse_sign(sign_findings(brief), check["problems"])
    refuse_problems(check)
    sources: dict[str, str | None] = {"roadmap_ai": technical.id}
    if kind == "analysis":
        info = repos.documents.current(loop.id, "info")
        sources = {"analysis_ai": technical.id, "info": info.id if info else None}
    human = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind=kind,
        content=render_brief(brief, payload),
        payload=brief.model_dump(),
        actor=actor,
        sources=sources,
        generation_run_id=run_id,
        provenance={**provenance, "written": True},
    )
    invalidate_downstream(repos, loop.id, kind, clock=clock)
    log_loop_activity(
        repos,
        actor,
        f"loop.{kind}_brief_written",
        loop.id,
        {
            f"{kind}_revision": human.revision_number,
            f"{kind}_ai_revision": technical.revision_number,
        },
        clock=clock,
        new_id=new_id,
    )
    return human


__all__ = [
    "BRIEF_FINDING_CATEGORIES",
    "MATERIAL_FINDING_CATEGORIES",
    "BriefCheck",
    "PlanOutline",
    "brief_coverage_missing",
    "brief_finding_ids",
    "brief_text_problems",
    "check_analysis_brief",
    "check_brief",
    "check_roadmap_brief",
    "named_findings",
    "plan_outline",
    "refuse_problems",
    "render_brief",
    "store_brief",
    "text_problems",
]
