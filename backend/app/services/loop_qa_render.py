"""The QA instructions as Markdown: the agent view, the human view and the Task that carries both.

Both views are built from the same scenario ids, so a result reported against one names the same
scenario in the other. Pure functions: nothing here reads or writes a board.
"""

from __future__ import annotations

from ..schemas.loops import QaInstructions


def render_qa_ai(instructions: QaInstructions) -> str:
    lines = ["## QA instructions (agent view)", ""]
    if instructions.summary:
        lines += [instructions.summary, ""]
    lines.append(
        "Report each scenario id with an outcome of passed, failed, blocked, not_run or "
        "not_applicable. State which of your own tools are available; never infer a pass from "
        "the absence of an error report."
    )
    lines += ["", "Prerequisites and environment must be supplied by whoever runs this task.", ""]
    if instructions.known_risks:
        lines += ["**Known risks**", ""] + [f"- {risk}" for risk in instructions.known_risks] + [""]
    for scenario in instructions.scenarios:
        lines += [f"### {scenario.id} — {scenario.title} ({scenario.kind})", ""]
        if scenario.prerequisites:
            lines += ["Prerequisites:"] + [f"- {item}" for item in scenario.prerequisites] + [""]
        lines += [f"{index}. {step}" for index, step in enumerate(scenario.steps_ai, start=1)]
        lines += ["", f"Expected result: {scenario.expected_result}", ""]
        if scenario.evidence:
            lines += ["Capture:"] + [f"- {item}" for item in scenario.evidence] + [""]
    return "\n".join(lines).strip() + "\n"


def render_qa_human(instructions: QaInstructions) -> str:
    lines = ["## QA instructions (human view)", ""]
    if instructions.summary:
        lines += [instructions.summary, ""]
    for scenario in instructions.scenarios:
        lines += [f"### Scenario {scenario.id}: {scenario.title}", ""]
        if scenario.prerequisites:
            lines += ["Before you start:"] + [f"- {item}" for item in scenario.prerequisites] + [""]
        lines += [f"{index}. {step}" for index, step in enumerate(scenario.steps_human, start=1)]
        lines += ["", f"Expected result: {scenario.expected_result}", ""]
    return "\n".join(lines).strip() + "\n"


def render_qa_task(instructions: QaInstructions, cycle_number: int) -> str:
    return (
        f"QA cycle {cycle_number}. One task, both views, the same scenario ids.\n\n"
        + render_qa_human(instructions)
        + "\n---\n\n"
        + render_qa_ai(instructions)
    )
