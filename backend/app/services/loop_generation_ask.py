"""Asking the model for a generation's answer: one call with the snapshot, then the repairs.

``generate`` sends the run's request (the Loop's documents and, when the agent's provider does not
take tools, the repository snapshot) in one call and parses the answer as the purpose's schema
reads it. An answer that does not validate goes back to the model with what was wrong, at most
``MAX_REPAIRS`` times. Every call, answer and repair is a step of the run's process tree
(``loop_generation_trace``), so a person sees how the answer came about. The model that reads the
repositories through tools asks through ``loop_generation_tools`` and shares the repair rules here.

A RoadMap whose face for people breaks its template is told every problem first, one per line, each
naming the Ticket, the field and the rule (``ticket_face``), and every problem of every round is a
``roadmap_face_repair`` log line, so a model that keeps failing the template is visible.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from pydantic import ValidationError

from ..core.errors import ValidationFailure
from ..db.generated.registry import AgentsRow
from .loop_generation_prompts import (
    JsonObject,
    context_labels,
    parse_output,
    response_schema_for,
    rule_text,
    user_message,
)
from .loop_generation_report import error_details
from .loop_generation_runs import Outcome
from .loop_generation_trace import RunTrace, clip, note
from .runtime import Completion, ResponseSchema
from .runtime_tools import Message, ToolChoice, ToolDefinition
from .ticket_face import FACE_INVALID, FaceRefusal

logger = logging.getLogger("tralala.loop_generation")

MAX_REPAIRS = 2
FACE_REPAIR = (
    "That response did not validate: each line above names a Ticket, the field and the rule it "
    "breaks. Fix every line and return the corrected JSON object only."
)


@dataclass(frozen=True, slots=True)
class RunIds:
    """The run an answer belongs to, for the log lines of its repair rounds."""

    loop_id: str
    run_id: str


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
    message with its details (the Phase and the reference that is missing), or the parser's text.
    A face that breaks its template is told by its messages, one per line, each naming the Ticket,
    the field and the rule."""
    if isinstance(exc, FaceRefusal):
        return exc.lines()
    if isinstance(exc, ValidationFailure):
        return rule_text(exc)
    return str(exc)


def invalid_outcome(exc: Exception) -> Outcome:
    """The failed run's outcome: ``face_invalid`` with the face's first messages for a face that
    still breaks its template, ``invalid_output`` for anything else."""
    if isinstance(exc, FaceRefusal):
        return Outcome(
            error_code=FACE_INVALID,
            error_message=exc.message,
            error_details=error_details({"rule": exc.code, **(exc.details or {})}),
            retryable=False,
        )
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


def repair_step(problem: str, more: int = 0) -> str:
    """The repair round as the process tree shows it: the first problem, and how many follow."""
    also = f" (and {more} more)" if more else ""
    return f"The answer broke a rule: {clip(problem, 300)}{also} \u2014 asked the model to fix it"


def repair_message(exc: Exception) -> str:
    """The repair request for ``exc``: a face that breaks its template is told by its messages
    first, one per line, then what to do; anything else as ``repair_request`` says it."""
    if isinstance(exc, FaceRefusal):
        return f"{exc.lines()}\n{FACE_REPAIR}"
    return repair_request(problem_of(exc))


def log_face_problems(exc: Exception, ids: RunIds | None, attempt: int) -> int:
    """One ``roadmap_face_repair`` line per face problem of the answer ``attempt`` (1 for the first
    answer, 2 for the answer to the first repair, and so on); answers how many there were."""
    if not isinstance(exc, FaceRefusal):
        return 0
    for problem in exc.problems:
        logger.info(
            "roadmap_face_repair",
            extra={
                "loop_id": ids.loop_id if ids else None,
                "run_id": ids.run_id if ids else None,
                "attempt": attempt,
                "ticket_id": problem.ticket_id,
                "field": problem.field,
                "rule": problem.rule,
            },
        )
    return len(exc.problems)


def repair_round(
    trace: RunTrace | None, exc: Exception, *, ids: RunIds | None, attempt: int
) -> Message:
    """One repair round for answer ``attempt``: its face problems logged, a repair step whose text
    is the first problem (with how many face problems the round had), and the request to send."""
    faces = log_face_problems(exc, ids, attempt)
    if trace is not None:
        if isinstance(exc, FaceRefusal):
            messages = exc.messages()
            step = repair_step(messages[0], len(messages) - 1)
        else:
            step = repair_step(problem_of(exc))
        trace.add("checking", "repair", step, face=faces or None)
    return {"role": "user", "content": repair_message(exc)}


def give_up(
    trace: RunTrace | None, exc: Exception, *, ids: RunIds | None, attempt: int
) -> Outcome:
    """The last answer still broke a rule: its face problems logged, the error step, the run's
    failure."""
    log_face_problems(exc, ids, attempt)
    note(trace, "checking", gave_up(exc), kind="error")
    return invalid_outcome(exc)


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
    ids: RunIds | None = None,
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
                return give_up(trace, exc, ids=ids, attempt=attempt + 1)
            repair = repair_round(trace, exc, ids=ids, attempt=attempt + 1)
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
