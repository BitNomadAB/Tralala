"""The text of a Loop document, rendered from its validated structure.

Human-facing Markdown is rendered from the validated analysis or plan, and the technical revision
is that structure as JSON, so the human and machine views cannot drift apart.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from ..schemas.briefs import HumanBrief, RoadmapBrief
from ..schemas.loops import AnalysisPayload
from .loop_plans import CanonicalPlan


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def render_analysis(payload: AnalysisPayload) -> str:
    """Plain-language decision support; technical detail stays in a separate traceability block."""
    lines: list[str] = ["# Analysis", "", "## What this Loop sets out to achieve", ""]
    lines.append(payload.outcome or "Not described.")
    if payload.scope:
        lines += ["", "**In scope**", ""] + [f"- {item}" for item in payload.scope]
    if payload.non_goals:
        lines += ["", "**Not in scope**", ""] + [f"- {item}" for item in payload.non_goals]
    lines += ["", "## What was found", ""]
    if not payload.findings:
        lines.append("No findings were recorded.")
    for finding in payload.findings:
        lines.append(f"- **{finding.title}** — {finding.plain_language}")
    if payload.assumptions:
        lines += ["", "## Assumptions", ""] + [f"- {item}" for item in payload.assumptions]
    if payload.open_questions:
        lines += ["", "## Open questions", ""] + [f"- {item}" for item in payload.open_questions]
    if payload.options:
        lines += ["", "## Options considered", ""] + [f"- {item}" for item in payload.options]
    if payload.recommendation:
        lines += ["", "## Recommended direction", "", payload.recommendation]
    if payload.verification:
        lines += ["", "## How success can be checked", ""] + [
            f"- {item}" for item in payload.verification
        ]
    return "\n".join(lines).strip() + "\n\n---\n\n" + render_traceability(payload)


def render_traceability(payload: AnalysisPayload) -> str:
    """Each finding's id, category and technical detail, the sources and the baseline: what ties a
    view written for people back to the technical analysis, whoever wrote the view."""
    lines: list[str] = ["## Traceability", ""]
    for finding in payload.findings:
        detail = finding.technical_detail.replace("\n", " ").strip()
        lines.append(f"- `{finding.id}` ({finding.category}) {finding.title}: {detail}")
    if payload.sources:
        lines += ["", "**Sources**", ""] + [f"- {item}" for item in payload.sources]
    if payload.repository_revision:
        lines += ["", f"Baseline revision: `{payload.repository_revision}`"]
    return "\n".join(lines).strip() + "\n"


def render_roadmap(payload: CanonicalPlan) -> str:
    """Render the validated plan; prose is additive and structure comes from the server."""
    lines: list[str] = ["# RoadMap", ""]
    if payload["summary"]:
        lines += [payload["summary"], ""]
    phases = payload["phases"]
    by_id = {phase["id"]: phase for phase in phases}
    tickets_by_id = {ticket["id"]: ticket for phase in phases for ticket in phase["tickets"]}
    for phase in phases:
        lines += [f"## Phase {phase['number']} — {phase['name']}", ""]
        if phase["objective"]:
            lines += [phase["objective"], ""]
        if phase["narrative"]:
            lines += [phase["narrative"], ""]
        prerequisites: list[str] = []
        for reference in phase["prerequisite_phase_ids"]:
            other_phase = by_id.get(reference)
            if other_phase:
                prerequisites.append(f"Phase {other_phase['number']} ({other_phase['name']})")
        for reference in phase["prerequisite_ticket_ids"]:
            other_ticket = tickets_by_id.get(reference)
            if other_ticket:
                prerequisites.append(f"Ticket {other_ticket['key']}")
        if prerequisites:
            lines += ["**Starts after:** " + ", ".join(prerequisites), ""]
        if phase["entry_conditions"]:
            lines += ["**Before it can start:**"] + [
                f"- {item}" for item in phase["entry_conditions"]
            ] + [""]
        if phase["exit_conditions"]:
            lines += ["**Done when:**"] + [f"- {item}" for item in phase["exit_conditions"]] + [""]
        tickets = phase["tickets"]
        if tickets:
            lines += ["**Tickets**", ""]
        for ticket in tickets:
            human = ticket["required_actor"] == "human"
            gate = ticket["execution_mode"] == "pre_phase_gate"
            suffix = " — **Human action required**" if human else ""
            lines.append(f"- `{ticket['key']}` {ticket['title']}{suffix}")
            if gate:
                lines.append("  - This is a gate: the Phase cannot start until it is confirmed.")
            if ticket["objective"]:
                lines.append(f"  - Why: {ticket['objective']}")
            if ticket["note"]:
                lines.append(f"  - {ticket['note']}")
            if human:
                lines.append(f"  - Why a human is needed: {ticket['human_action_reason']}")
                lines.append(f"  - What you must do: {ticket['human_instructions']}")
            blocking: list[str] = []
            for reference in ticket["prerequisite_ticket_ids"]:
                other_ticket = tickets_by_id.get(reference)
                if other_ticket:
                    blocking.append(f"Ticket {other_ticket['key']}")
            for reference in ticket["prerequisite_phase_ids"]:
                other_phase = by_id.get(reference)
                if other_phase:
                    blocking.append(f"Phase {other_phase['number']}")
            if blocking:
                lines.append("  - Can be done after: " + ", ".join(blocking))
            if ticket["acceptance_criteria"]:
                lines.append("  - Accepted when: " + "; ".join(ticket["acceptance_criteria"]))
        lines.append("")
    lines += ["---", "", "Generated from the validated structured plan; the plan is authoritative."]
    return "\n".join(lines).strip() + "\n"


VERDICT_TEXT = {
    "yes": "Yes",
    "yes_with_conditions": "Yes, with conditions",
    "no": "No",
    "unclear": "Unclear",
}
LEVEL_TEXT = {
    "business": "Business",
    "technical": "Technical",
    "security": "Security",
    "legal": "Legal",
    "people_time": "People and time",
}


def render_analysis_brief(brief: HumanBrief) -> str:
    """The analysis brief for people: the verdict first, then what stands in the way, the
    highlights for and against, the decisions and the recommendation. No id, path or traceability
    block: the brief's ids carry that, and the technical analysis holds the detail."""
    verdict = VERDICT_TEXT.get(brief.verdict, brief.verdict)
    lines = ["# Analysis", "", f"**Can it be done?** {verdict}. {brief.verdict_reason}", ""]
    lines += [brief.summary, "", "## What stands in the way", ""]
    if brief.obstacles:
        lines += [
            f"- **{LEVEL_TEXT.get(item.level, item.level)}:** {item.text}"
            for item in brief.obstacles
        ]
    else:
        lines.append("Nothing was found that stands in the way.")
    for heading, points in (("For", brief.pros), ("Against", brief.cons)):
        if points:
            lines += ["", f"## {heading}", ""] + [f"- {point.text}" for point in points]
    if brief.decisions:
        lines += ["", "## What you need to decide", ""]
        lines += [f"- {decision.question}" for decision in brief.decisions]
    lines += ["", "## Recommendation", "", brief.recommendation]
    return "\n".join(lines).strip() + "\n"


def render_roadmap_brief(brief: RoadmapBrief, phases: Mapping[str, tuple[int, str]]) -> str:
    """The RoadMap brief for people: the order of work by Phase (numbered and named from the
    plan, in its order), what the person must do and what could block it."""
    lines = ["# RoadMap", "", brief.summary, "", "## The order of work", ""]
    steps = sorted(brief.order, key=lambda step: phases.get(step.phase_id, (0, ""))[0])
    for step in steps:
        number, name = phases.get(step.phase_id, (0, ""))
        lines += [f"### Phase {number} — {name}", "", step.what_happens, ""]
        lines += [f"**Done when:** {step.done_when}", ""]
    if brief.your_part:
        lines += ["## Your part", ""] + [f"- {part.text}" for part in brief.your_part] + [""]
    if brief.could_block:
        lines += ["## What could block it", ""]
        lines += [f"- {risk.text}" for risk in brief.could_block]
    return "\n".join(lines).strip() + "\n"


def render_analysis_technical(payload: AnalysisPayload) -> str:
    return "```json\n" + json.dumps(payload.model_dump(), indent=2, ensure_ascii=False) + "\n```\n"


def render_roadmap_technical(payload: CanonicalPlan) -> str:
    return "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```\n"


__all__ = [
    "LEVEL_TEXT",
    "VERDICT_TEXT",
    "content_hash",
    "render_analysis",
    "render_analysis_brief",
    "render_analysis_technical",
    "render_roadmap",
    "render_roadmap_brief",
    "render_roadmap_technical",
    "render_traceability",
]
