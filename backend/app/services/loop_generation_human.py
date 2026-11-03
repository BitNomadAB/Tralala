"""Asking a board agent to write the analysis for people (an ``analysis_human`` run).

The model gets the Info and the technical analysis, no repository and no tools, and answers with
Markdown. The server holds the answer to one rule: every material finding is named by its id
(``loop_documents_human.coverage_missing``). An answer that leaves one out goes back to the model
once with the ids it missed; when it still leaves one out, the run fails with ``coverage_missing``
and the view rendered from the structure stays. Each call and check is a step of the run's
process tree, as in ``loop_generation_ask``.
"""

from __future__ import annotations

from dataclasses import asdict

from ..db.generated.registry import AgentsRow
from ..schemas.loops import AnalysisPayload
from .loop_documents_human import compose_human_view, coverage_missing, material_ids, written_text
from .loop_generation_ask import CompletionCall, call_failed
from .loop_generation_prompts import MAX_OUTPUT_CHARS, JsonObject, human_view_message
from .loop_generation_report import error_details
from .loop_generation_runs import Outcome
from .loop_generation_trace import RunTrace, note
from .runtime_tools import Message

# One repair round: a second omission is a model that cannot follow the rule, not a slip.
MAX_COVERAGE_REPAIRS = 1


def technical_analysis(captured: JsonObject) -> AnalysisPayload | None:
    """The technical analysis the run was started for, as captured; None when there is none."""
    context = captured.get("context")
    documents = context.get("documents") if isinstance(context, dict) else None
    technical = documents.get("analysis_ai") if isinstance(documents, dict) else None
    payload = technical.get("payload") if isinstance(technical, dict) else None
    if not isinstance(payload, dict):
        return None
    return AnalysisPayload.model_validate(payload)


def _problem(text: str, payload: AnalysisPayload) -> list[str]:
    """What the answer leaves out: the material ids it never names, or everything when it is
    empty."""
    if not written_text(text):
        return material_ids(payload) or ["the text"]
    return coverage_missing(text, payload)


def coverage_request(missing: list[str]) -> str:
    return (
        "Your text does not name these findings by id: "
        + ", ".join(missing)
        + ". Cover each of them for the reader, with its id in square brackets, and answer with "
        "the whole corrected text only."
    )


def write_for_people(
    captured: JsonObject,
    agent: AgentsRow,
    *,
    system_prompt: str,
    call_completion: CompletionCall,
    settings: object,
    trace: RunTrace | None = None,
) -> Outcome:
    """The view for people, composed with its traceability block, or why there is none."""
    payload = technical_analysis(captured)
    if payload is None:
        note(trace, "writing", "There is no technical analysis to write for people", kind="error")
        return Outcome(
            error_code="document_empty",
            error_message="There is no technical analysis to write for people",
            retryable=False,
        )
    messages: list[Message] = [{"role": "user", "content": human_view_message(captured)}]
    note(trace, "writing", f"Asked {agent.name} to write the analysis for people")
    outcome = call_completion(
        settings,
        asdict(agent),
        system_prompt=system_prompt,
        messages=messages,
        response_schema=None,
    )
    if not outcome["ok"]:
        note(trace, "writing", f"The provider call failed: {outcome['error']}", kind="error")
        return call_failed(outcome)
    text = outcome["text"]
    repaired = False
    for attempt in range(MAX_COVERAGE_REPAIRS + 1):
        note(trace, "writing", f"The model answered ({len(text)} characters)")
        missing = _problem(text, payload)
        if not missing:
            break
        if attempt >= MAX_COVERAGE_REPAIRS:
            note(trace, "checking", f"The text still leaves out {', '.join(missing)}", kind="error")
            return Outcome(
                error_code="coverage_missing",
                error_message=(
                    "The text written for people leaves out material findings; the view rendered "
                    "from the structure stays"
                ),
                error_details=error_details({"finding_ids": missing}),
                retryable=True,
            )
        note(
            trace,
            "checking",
            f"The text leaves out {', '.join(missing)} — asked the model to cover them",
            kind="repair",
        )
        repair: Message = {"role": "user", "content": coverage_request(missing)}
        outcome = call_completion(
            settings,
            asdict(agent),
            system_prompt=system_prompt,
            messages=[*messages, {"role": "assistant", "content": text}, repair],
            response_schema=None,
        )
        if not outcome["ok"]:
            note(trace, "checking", f"The provider call failed: {outcome['error']}", kind="error")
            return call_failed(outcome)
        text = outcome["text"]
        repaired = True
    content = compose_human_view(text, payload)
    if len(content) > MAX_OUTPUT_CHARS:
        note(trace, "checking", "The text is longer than a document may be", kind="error")
        return Outcome(
            error_code="invalid_output",
            error_message="The text written for people exceeds the size limit",
            retryable=False,
        )
    note(trace, "checking", "The text names every material finding")
    model = outcome.get("model")
    return Outcome(
        payload={"content": content, "covered": [*material_ids(payload)], "repaired": repaired},
        usage=outcome.get("usage"),
        model=model if isinstance(model, str) else None,
    )


__all__ = [
    "MAX_COVERAGE_REPAIRS",
    "coverage_request",
    "technical_analysis",
    "write_for_people",
]
