"""Asking a board agent for the brief a person reads (an ``analysis_human`` or ``roadmap_human``
run).

The model gets the Info and the technical revision the brief explains, no repository and no tools,
and answers a JSON object of the brief's schema (``schemas/briefs.py``, sent as the response
format). The server holds the answer to the rules every brief keeps
(``loop_documents_human.check_brief``): it parses, names every finding (or every Phase and every
Ticket a person must do), knows only the ids the technical revision holds, and its text holds no id,
path or code. An answer that breaks a rule goes back to the model once, with every problem named
field by field; when the second answer still breaks one, the run fails with ``brief_rejected`` and
the view rendered from the structure stays. Each call and check is a step of the run's process
tree, as in ``loop_generation_ask``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict

from pydantic import JsonValue, ValidationError

from ..db.generated.registry import AgentsRow
from ..schemas.briefs import HumanBrief, RoadmapBrief
from .loop_documents_human import check_brief
from .loop_generation_ask import CompletionCall, call_failed
from .loop_generation_prompts import (
    MAX_OUTPUT_CHARS,
    JsonObject,
    human_view_message,
    response_schema_for,
    strip_fences,
)
from .loop_generation_report import error_details
from .loop_generation_runs import Outcome
from .loop_generation_trace import RunTrace, note
from .runtime_tools import Message

# One repair round: a second broken brief is a model that cannot follow the rules, not a slip.
MAX_BRIEF_REPAIRS = 1
# The most problems one repair request or one failure names.
MAX_PROBLEMS = 20
# The technical revision each purpose writes a brief of.
TECHNICAL_KIND = {"analysis_human": "analysis_ai", "roadmap_human": "roadmap_ai"}
_WHAT = {"analysis_human": "technical analysis", "roadmap_human": "technical RoadMap"}


def technical_payload(captured: JsonObject, purpose: str) -> JsonObject | None:
    """The technical revision the run was started for, as captured; None when there is none."""
    context = captured.get("context")
    documents = context.get("documents") if isinstance(context, dict) else None
    kind = TECHNICAL_KIND.get(purpose, "analysis_ai")
    technical = documents.get(kind) if isinstance(documents, dict) else None
    payload = technical.get("payload") if isinstance(technical, dict) else None
    return payload if isinstance(payload, dict) else None


def _schema_problems(error: ValidationError) -> list[str]:
    return [
        ".".join(str(part) for part in detail["loc"]) + f": {detail['msg']}"
        for detail in error.errors()
    ]


def read_brief(
    purpose: str, text: str, technical: Mapping[str, JsonValue]
) -> tuple[HumanBrief | RoadmapBrief | None, list[str]]:
    """The brief the model answered and what is wrong with it: a schema error, or a rule it
    breaks."""
    try:
        loaded: object = json.loads(strip_fences(text))
        validated: HumanBrief | RoadmapBrief = (
            HumanBrief.model_validate(loaded)
            if purpose == "analysis_human"
            else RoadmapBrief.model_validate(loaded)
        )
    except json.JSONDecodeError:
        return None, ["the answer is not a JSON object"]
    except ValidationError as error:
        return None, _schema_problems(error)
    return validated, check_brief(validated, technical)["problems"]


def repair_request(problems: list[str]) -> str:
    return (
        "Your brief was not accepted: "
        + "; ".join(problems[:MAX_PROBLEMS])
        + ". Correct each of these and answer with the whole corrected JSON object only."
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
    """The brief for people, checked, or why there is none."""
    purpose = str(captured.get("purpose") or "analysis_human")
    what = _WHAT.get(purpose, "technical analysis")
    technical = technical_payload(captured, purpose)
    if technical is None:
        note(trace, "writing", f"There is no {what} to write a brief for", kind="error")
        return Outcome(
            error_code="document_empty",
            error_message=f"There is no {what} to write a brief for",
            retryable=False,
        )
    schema = response_schema_for(purpose)
    messages: list[Message] = [{"role": "user", "content": human_view_message(captured)}]
    note(trace, "writing", f"Asked {agent.name} for the brief for people")
    outcome = call_completion(
        settings,
        asdict(agent),
        system_prompt=system_prompt,
        messages=messages,
        response_schema=schema,
    )
    if not outcome["ok"]:
        note(trace, "writing", f"The provider call failed: {outcome['error']}", kind="error")
        return call_failed(outcome)
    text = outcome["text"]
    repaired = False
    brief: HumanBrief | RoadmapBrief | None = None
    for attempt in range(MAX_BRIEF_REPAIRS + 1):
        note(trace, "writing", f"The model answered ({len(text)} characters)")
        if len(text) > MAX_OUTPUT_CHARS:
            problems = ["the answer is longer than a document may be"]
        else:
            brief, problems = read_brief(purpose, text, technical)
        if not problems:
            break
        brief = None
        if attempt >= MAX_BRIEF_REPAIRS:
            note(trace, "checking", f"The brief still breaks a rule: {problems[0]}", kind="error")
            return Outcome(
                error_code="brief_rejected",
                error_message=(
                    "The brief written for people breaks a rule; the view rendered from the "
                    "structure stays"
                ),
                error_details=error_details({"problems": problems[:MAX_PROBLEMS]}),
                retryable=True,
            )
        note(
            trace,
            "checking",
            f"The brief breaks {len(problems)} rule(s) — asked the model to correct them",
            kind="repair",
        )
        repair: Message = {"role": "user", "content": repair_request(problems)}
        outcome = call_completion(
            settings,
            asdict(agent),
            system_prompt=system_prompt,
            messages=[*messages, {"role": "assistant", "content": text}, repair],
            response_schema=schema,
        )
        if not outcome["ok"]:
            note(trace, "checking", f"The provider call failed: {outcome['error']}", kind="error")
            return call_failed(outcome)
        text = outcome["text"]
        repaired = True
    if brief is None:  # pragma: no cover - the loop either breaks with a brief or returns
        return Outcome(error_code="brief_rejected", error_message="No brief", retryable=True)
    note(trace, "checking", "The brief covers what it must and its text is for people")
    model = outcome.get("model")
    return Outcome(
        payload={"brief": brief.model_dump(), "repaired": repaired},
        usage=outcome.get("usage"),
        model=model if isinstance(model, str) else None,
    )


__all__ = [
    "MAX_BRIEF_REPAIRS",
    "TECHNICAL_KIND",
    "read_brief",
    "repair_request",
    "technical_payload",
    "write_for_people",
]
