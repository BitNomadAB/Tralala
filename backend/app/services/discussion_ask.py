"""Asking one participant for its answer to a round: one call, then at most one repair.

The call sends the standard's schema where the agent's provider takes one. An answer that does not
follow the standard goes back once with what was wrong, in the words the generation runs use
(``loop_generation_ask.repair_request``). An answer that still does not follow it, or whose repair
call failed, is kept as prose with the position ``unclear``: what the participant said is never
dropped. Both calls' tokens count.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypedDict, TypeGuard

from .discussion_answers import (
    AnswerShapeError,
    DiscussionAnswer,
    answer_schema,
    parse_answer,
    prose_answer,
)
from .loop_generation_ask import repair_request
from .runtime import Completion, ResponseSchema
from .runtime_tools import Message

# A round asks every participant, so each repair multiplies the spend; one is the bound.
MAX_REPAIRS = 1


class AnswerCall(Protocol):
    """``runtime.call_completion`` as a discussion round calls it."""

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: Sequence[Message],
        response_schema: ResponseSchema | None,
    ) -> Completion: ...


class Asked(TypedDict):
    """What a participant answered: the prose, its structure, the model and the tokens; or the
    error of a first call that failed."""

    ok: bool
    error: str | None
    content: str
    answer: DiscussionAnswer
    model: str | None
    tokens: int
    repairs: int


def _is_counts(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def usage_tokens(result: Mapping[str, object]) -> int:
    """The tokens a provider reported for one call: the total, or prompt plus completion."""
    counts = result.get("usage")
    if not _is_counts(counts):
        return 0
    total = counts.get("total_tokens")
    if isinstance(total, (int, float)):
        return int(total)
    prompt = counts.get("prompt_tokens") or counts.get("input_tokens") or 0
    completion = counts.get("completion_tokens") or counts.get("output_tokens") or 0
    if isinstance(prompt, (int, float)) and isinstance(completion, (int, float)):
        return int(prompt) + int(completion)
    return 0


def _model(result: Completion) -> str | None:
    model = result.get("model")
    return model if isinstance(model, str) else None


def ask_participant(
    call: AnswerCall,
    settings: object,
    agent_row: Mapping[str, object],
    *,
    system_prompt: str,
    messages: Sequence[Message],
) -> Asked:
    """One participant's answer in the standard shape, repaired once, else kept as prose."""
    schema = answer_schema()
    row = dict(agent_row)
    first = call(
        settings, row, system_prompt=system_prompt, messages=messages, response_schema=schema
    )
    if not first["ok"]:
        return {
            "ok": False,
            "error": str(first["error"]),
            "content": "",
            "answer": prose_answer("the provider call failed"),
            "model": None,
            "tokens": 0,
            "repairs": 0,
        }
    tokens = usage_tokens(first)
    model = _model(first)
    text = first["text"]
    try:
        answer, content = parse_answer(text)
    except AnswerShapeError as problem:
        last = str(problem)
    else:
        return {
            "ok": True,
            "error": None,
            "content": content,
            "answer": answer,
            "model": model,
            "tokens": tokens,
            "repairs": 0,
        }
    repairs = 0
    attempt = text
    while repairs < MAX_REPAIRS:
        repairs += 1
        repair: Message = {"role": "user", "content": repair_request(last)}
        again = call(
            settings,
            row,
            system_prompt=system_prompt,
            messages=[*messages, {"role": "assistant", "content": attempt}, repair],
            response_schema=schema,
        )
        if not again["ok"]:
            last = f"the repair call failed: {again['error']}"
            break
        tokens += usage_tokens(again)
        model = _model(again) or model
        attempt = again["text"]
        try:
            answer, content = parse_answer(attempt)
        except AnswerShapeError as problem:
            last = str(problem)
            continue
        answer["format"] = "repaired"
        return {
            "ok": True,
            "error": None,
            "content": content,
            "answer": answer,
            "model": model,
            "tokens": tokens,
            "repairs": repairs,
        }
    # The first answer is what the participant meant to say; a failed repair is not kept over it.
    return {
        "ok": True,
        "error": None,
        "content": text,
        "answer": prose_answer(last),
        "model": model,
        "tokens": tokens,
        "repairs": repairs,
    }
