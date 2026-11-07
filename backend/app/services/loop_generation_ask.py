"""Asking the model for a generation's answer: one call with the snapshot, then the repairs.

``generate`` sends the run's request (the Loop's documents and, when the agent's provider does not
take tools, the repository snapshot) in one call and parses the answer as the purpose's schema
reads it. An answer that does not validate goes back to the model with what was wrong, at most
``MAX_REPAIRS`` times. Every call, answer and repair is a step of the run's process tree
(``loop_generation_trace``), so a person sees how the answer came about. The model that reads the
repositories through tools asks through ``loop_generation_tools`` and shares the repair rules here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from typing import Protocol

from pydantic import ValidationError

from ..core.errors import ValidationFailure
from ..db.generated.registry import AgentsRow
from .loop_generation_prompts import (
    JsonObject,
    context_labels,
    parse_output,
    response_schema_for,
    user_message,
)
from .loop_generation_report import error_details
from .loop_generation_runs import Outcome
from .loop_generation_trace import RunTrace, clip, note
from .runtime import Completion, ResponseSchema
from .runtime_tools import Message, ToolChoice, ToolDefinition

MAX_REPAIRS = 2


class CompletionCall(Protocol):
    """``runtime.call_completion`` as a generation calls it: the discussions' ``AgentCall`` plus the
    schema the answer must follow, which the runtime sends only where the agent's provider takes
    one (``agents.supports_json_schema``), and the tools it may call, which it sends only where
    the provider takes those (``agents.supports_tools``)."""

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: Sequence[Message],
        response_schema: ResponseSchema | None,
        tools: Sequence[ToolDefinition] | None = None,
        tool_choice: ToolChoice = "auto",
    ) -> Completion: ...


def call_failed(outcome: Completion) -> Outcome:
    return Outcome(
        error_code="provider_error",
        error_message=f"The provider call failed: {outcome['error']}",
        retryable=True,
    )


def problem_of(exc: Exception) -> str:
    """What a repair message and a failed run say about an answer that did not validate: a rule's
    message with its details (the Phase and the reference that is missing), or the parser's text."""
    if isinstance(exc, ValidationFailure):
        details = f" {json.dumps(dict(exc.details), default=str)}" if exc.details else ""
        return f"{exc.message}{details}"
    return str(exc)


def invalid_outcome(exc: Exception) -> Outcome:
    if isinstance(exc, ValidationFailure):
        return Outcome(
            error_code="invalid_output",
            error_message=f"Generated output broke a rule: {exc.message}",
            error_details=error_details({"rule": exc.code, **(exc.details or {})}),
            retryable=False,
        )
    return Outcome(
        error_code="invalid_output",
        error_message="Generated output did not match the schema",
        details=problem_of(exc)[:2000],
        retryable=False,
    )


def repair_request(problem: str) -> str:
    """What the model is told about an answer that did not validate."""
    return (
        "That response did not validate. Fix it and return the corrected JSON object only. "
        f"Error: {problem[:1500]}"
    )


def repair_step(problem: str) -> str:
    """The repair round as the process tree shows it."""
    return f"The answer broke a rule: {clip(problem, 300)} \u2014 asked the model to fix it"


def generate(
    purpose: str,
    captured: JsonObject,
    agent: AgentsRow,
    *,
    system_prompt: str,
    call_completion: CompletionCall,
    settings: object,
    context_chars: int,
    trace: RunTrace | None = None,
) -> Outcome:
    """One call with the snapshot in the message, then up to ``MAX_REPAIRS`` repair rounds."""
    messages: list[Message] = [
        {"role": "user", "content": user_message(captured, budget_chars=context_chars)}
    ]
    # The same schema the prompt shows; the runtime sends it only to a provider that takes one.
    response_schema = response_schema_for(purpose)
    note(trace, "writing", f"Asked {agent.name} for the {_document(purpose)} in one call")
    outcome = call_completion(
        settings,
        asdict(agent),
        system_prompt=system_prompt,
        messages=messages,
        response_schema=response_schema,
    )
    if not outcome["ok"]:
        note(trace, "writing", f"The provider call failed: {outcome['error']}", kind="error")
        return call_failed(outcome)
    usage = outcome.get("usage")
    model = outcome.get("model")
    model_name = model if isinstance(model, str) else None
    text = outcome["text"]
    for attempt in range(MAX_REPAIRS + 1):
        note(trace, "writing", f"The model answered ({len(text)} characters)")
        try:
            payload = parse_output(purpose, text, labels=context_labels(captured))
            note(trace, "checking", "The answer follows the schema and the rules")
            return Outcome(payload=payload, usage=usage, model=model_name)
        except (ValueError, ValidationError, ValidationFailure) as exc:
            if attempt >= MAX_REPAIRS:
                note(trace, "checking", gave_up(exc), kind="error")
                return invalid_outcome(exc)
            note(trace, "checking", repair_step(problem_of(exc)), kind="repair")
            repair: Message = {"role": "user", "content": repair_request(problem_of(exc))}
            outcome = call_completion(
                settings,
                asdict(agent),
                system_prompt=system_prompt,
                messages=[*messages, {"role": "assistant", "content": text}, repair],
                response_schema=response_schema,
            )
            if not outcome["ok"]:
                note(trace, "checking", f"The provider call failed: {outcome['error']}", "error")
                return call_failed(outcome)
            text = outcome["text"]
    return Outcome(
        error_code="invalid_output",
        error_message="Generated output did not match the schema",
        retryable=False,
    )


def gave_up(exc: Exception) -> str:
    problem = clip(problem_of(exc), 300)
    return f"The answer still broke a rule after {MAX_REPAIRS} repairs: {problem}"


def _document(purpose: str) -> str:
    return {"analysis": "analysis", "roadmap": "RoadMap"}.get(purpose, "QA instructions")
