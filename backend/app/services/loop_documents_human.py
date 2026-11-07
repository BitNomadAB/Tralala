"""The brief a person reads, checked against the technical revision it explains, and stored.

A person and a model read differently. The technical analysis (``analysis_ai``) and the technical
RoadMap (``roadmap_ai``) are structure for engineers and models; the human view (``analysis``,
``roadmap``) is a decision brief (``schemas/briefs.py``): can it be done, what stands in the way,
the highlights for and against, what a person must decide. Until somebody writes one, the human
view is rendered from the structure and says so in its provenance (``rendered``).

Whoever writes a brief (a connected worker over ``/mcp``, a board agent's run, a person), it is
held to the same rules before it is stored:

- **coverage**: the items of an analysis brief together name, in their ``finding_ids``, every
  finding of a material category or of category ``decision``; a RoadMap brief lists every Phase in
  ``order`` exactly once and every Ticket a person must do in ``your_part``;
- **known ids**: an id the technical revision does not hold is refused;
- **plain text**: the visible text holds no finding id, no other id, no file path and no code; the
  ids carry the traceability, the text is for people.

A refusal is ``422 brief_rejected`` with every problem named, field by field. Everything here is
pure except ``store_brief``, which writes the revision inside the caller's unit of work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypedDict

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import Conflict, ValidationFailure, VersionConflict
from ..db.generated.board import LoopDocumentsRow, LoopsRow
from ..repositories.board import BoardRepositories
from ..schemas.briefs import HumanBrief, RoadmapBrief
from ..schemas.loops import AnalysisPayload
from .loop_documents_render import render_analysis_brief, render_roadmap_brief
from .loop_documents_revisions import invalidate_downstream, log_loop_activity, write_revision

# The findings a person must be told about; a brief names the decisions as well, since a decision is
# what a person must take.
MATERIAL_FINDING_CATEGORIES = frozenset({"risk", "blocker", "legal", "security", "question"})
BRIEF_FINDING_CATEGORIES = frozenset({*MATERIAL_FINDING_CATEGORIES, "decision"})
# What visible text must not hold. A code fence or an inline code span is code formatting; a token
# with a slash (or a backslash) and a file extension is a path (a URL's path is not, since a host
# name comes before it); a UUID is an id; ``F-1``, ``F01`` and ``[F01]`` are finding ids whatever
# the technical revision calls its findings.
_FENCE = re.compile(r"```|~~~")
_CODE_SPAN = re.compile(r"`[^`\n]+`")
_PATH = re.compile(r"(?<![\w/\\.:-])(?:[\w.-]+[/\\])+[\w-]+\.[A-Za-z][A-Za-z0-9]{0,7}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_FINDING_LIKE = re.compile(r"\[\s*[A-Za-z]{1,4}-?\d{1,4}\s*\]|\bF-\d{1,4}\b|\bF\d{2,4}\b")
_LETTER = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"\d")


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


def _shown_ids(finding_ids: Sequence[str]) -> list[re.Pattern[str]]:
    """How each finding id shows up in prose. An id that looks like one (a letter and a digit, or a
    separator) is found as a whole word; a bare number or word only in square brackets, since
    ``3`` or ``mail`` alone is ordinary text."""
    patterns: list[re.Pattern[str]] = []
    for finding_id in finding_ids:
        escaped = re.escape(finding_id)
        looks_like_id = (
            _LETTER.search(finding_id) is not None and _DIGIT.search(finding_id) is not None
        ) or any(mark in finding_id for mark in "-_.")
        if looks_like_id and len(finding_id) >= 2:
            patterns.append(re.compile(rf"(?<![\w-]){escaped}(?![\w-])"))
        else:
            patterns.append(re.compile(rf"\[\s*{escaped}\s*\]"))
    return patterns


def text_problems(text: str, known_ids: Sequence[str]) -> list[str]:
    """Why ``text`` is not for people, as short phrases; empty when it is."""
    problems: list[str] = []
    if _FENCE.search(text):
        problems.append("contains a code fence")
    span = _CODE_SPAN.search(text)
    if span is not None:
        problems.append(f"contains code ({span.group(0)})")
    path = _PATH.search(text)
    if path is not None:
        problems.append(f"contains a file path ({path.group(0)})")
    uuid = _UUID.search(text)
    if uuid is not None:
        problems.append(f"contains an id ({uuid.group(0)})")
    shown = next(
        (match.group(0) for pattern in _shown_ids(known_ids) if (match := pattern.search(text))),
        None,
    ) or next((match.group(0) for match in _FINDING_LIKE.finditer(text)), None)
    if shown is not None:
        problems.append(f"contains a finding id ({shown}); ids belong in finding_ids only")
    return problems


def _analysis_texts(brief: HumanBrief) -> Iterator[tuple[str, str]]:
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
    yield "recommendation", brief.recommendation


def _roadmap_texts(brief: RoadmapBrief) -> Iterator[tuple[str, str]]:
    yield "summary", brief.summary
    for index, step in enumerate(brief.order):
        yield f"order[{index}].what_happens", step.what_happens
        yield f"order[{index}].done_when", step.done_when
    for index, part in enumerate(brief.your_part):
        yield f"your_part[{index}].text", part.text
    for index, risk in enumerate(brief.could_block):
        yield f"could_block[{index}].text", risk.text


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


def check_roadmap_brief(brief: RoadmapBrief, plan: PlanOutline) -> BriefCheck:
    found = _Findings()
    phase_ids = [phase[0] for phase in plan.phases]
    ticket_ids = [ticket[0] for ticket in plan.tickets]
    ordered = [step.phase_id for step in brief.order]
    named_phases = [
        *ordered,
        *(phase_id for part in brief.your_part for phase_id in part.phase_ids),
        *(phase_id for risk in brief.could_block for phase_id in risk.phase_ids),
    ]
    named_tickets = [ticket_id for part in brief.your_part for ticket_id in part.ticket_ids]
    found.unknown = list(
        dict.fromkeys(
            [
                *(phase_id for phase_id in named_phases if phase_id not in phase_ids),
                *(ticket_id for ticket_id in named_tickets if ticket_id not in ticket_ids),
            ]
        )
    )
    if found.unknown:
        found.problems.append(
            "phase_ids/ticket_ids: the RoadMap has no Phase or Ticket " + ", ".join(found.unknown)
        )
    twice = sorted({phase_id for phase_id in ordered if ordered.count(phase_id) > 1})
    if twice:
        found.problems.append("order: lists a Phase more than once: " + ", ".join(twice))
    absent = [phase_id for phase_id in phase_ids if phase_id not in ordered]
    if absent:
        found.problems.append("order: leaves out the Phase(s) " + ", ".join(absent))
    human = [ticket[0] for ticket in plan.tickets if ticket[3]]
    unnamed = [ticket_id for ticket_id in human if ticket_id not in named_tickets]
    if unnamed:
        found.problems.append(
            "your_part: leaves out the Ticket(s) a person must do " + ", ".join(unnamed)
        )
    found.missing = [*absent, *unnamed]
    for path, text in _roadmap_texts(brief):
        for problem in text_problems(text, []):
            found.wording(path, problem)
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
    return check_roadmap_brief(brief, plan_outline(technical))


def render_brief(
    brief: HumanBrief | RoadmapBrief, technical: Mapping[str, JsonValue]
) -> str:
    """The brief as Markdown: what the revision's content holds and an export shows."""
    if isinstance(brief, HumanBrief):
        return render_analysis_brief(brief)
    outline = plan_outline(technical)
    return render_roadmap_brief(brief, {phase[0]: (phase[1], phase[2]) for phase in outline.phases})


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
    with every problem named; a new brief invalidates what was approved of the scope and after it,
    as any new revision of the human view does."""
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
    refuse_problems(check_brief(brief, payload))
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
