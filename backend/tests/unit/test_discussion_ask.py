"""Asking a participant for its answer: one call, one repair that quotes every finding, and the
prose kept as ``unclear`` when the repair fails too. A scripted provider; the log read back as the
lines the backend writes."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from app.services.discussion_ask import (
    ANSWER_REPAIR,
    MAX_REPAIRS,
    AnswerFor,
    ask_participant,
    usage_tokens,
)
from app.services.runtime import Completion, ResponseSchema
from app.services.runtime_tools import Message
from tests.unit.log_lines import events

ABOUT = AnswerFor(discussion_id="d-1", participant_id="a-1", round_number=2)
WHERE = {"discussion_id": "d-1", "participant_id": "a-1", "round_number": 2}


def standard(**fields: object) -> str:
    payload: dict[str, object] = {
        "position": "yes",
        "recommendation": "Ship it behind a flag.",
        "pros": ["Users asked for it."],
        "cons": ["One more flag to remove."],
        "confidence": "high",
        "reasoning": "The **change** is small.",
    }
    payload.update(fields)
    return json.dumps(payload)


# Two findings in one answer: a recommendation of 25 words and a condition naming a file.
LONG = " ".join(["word"] * 25)
BROKEN = standard(recommendation=LONG, conditions=["Keep Banner.tsx as it is."])


def said(text: str, tokens: int = 10) -> Completion:
    return {
        "ok": True,
        "error": None,
        "text": text,
        "tool_calls": [],
        "model": "m",
        "usage": {"total_tokens": tokens},
    }


def failed(error: str) -> Completion:
    return {"ok": False, "error": error, "text": "", "tool_calls": []}


@dataclass
class Provider:
    answers: list[Completion]
    asked: list[Sequence[Message]] = field(default_factory=list[Sequence[Message]])

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: Sequence[Message],
        response_schema: ResponseSchema | None,
    ) -> Completion:
        del settings, agent_row, system_prompt
        assert response_schema is not None and response_schema["name"] == "discussion_answer"
        self.asked.append(messages)
        return self.answers.pop(0)


QUESTION: list[Message] = [{"role": "user", "content": "Ship it?"}]


def ask(provider: Provider) -> dict[str, object]:
    asked = ask_participant(
        provider, object(), {"id": "a"}, system_prompt="s", messages=QUESTION, about=ABOUT
    )
    return dict(asked)


def logged(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        event
        for event in events(caplog.records)
        if str(event["event"]).startswith("discussion_answer_")
    ]


def test_one_repair_is_the_bound() -> None:
    assert MAX_REPAIRS == 1


def test_a_valid_answer_costs_one_call_and_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    provider = Provider([said(standard(), tokens=7)])
    with caplog.at_level(logging.INFO, logger="tralala.discussions"):
        asked = ask(provider)
    answer = asked["answer"]
    assert isinstance(answer, dict)
    assert (answer["format"], asked["tokens"], asked["repairs"]) == ("structured", 7, 0)
    assert len(provider.asked) == 1
    assert logged(caplog) == []


def test_the_repair_quotes_every_finding_and_the_repaired_answer_is_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = Provider([said(BROKEN, tokens=5), said(standard(), tokens=6)])
    with caplog.at_level(logging.INFO, logger="tralala.discussions"):
        asked = ask(provider)
    answer = asked["answer"]
    assert isinstance(answer, dict)
    assert (answer["format"], answer["position"]) == ("repaired", "yes")
    assert (asked["tokens"], asked["repairs"]) == (11, 1)
    assert asked["content"] == "The **change** is small."
    repair = provider.asked[1]
    assert [message["role"] for message in repair] == ["user", "assistant", "user"]
    assert repair[1]["content"] == BROKEN
    assert repair[2]["content"] == (
        "recommendation: 25 words; at most 20\n"
        "conditions[0]: looks like a file path (Banner.tsx)\n" + ANSWER_REPAIR
    )
    assert logged(caplog) == [
        {
            "event": "discussion_answer_repair",
            **WHERE,
            "findings": [
                {"field": "recommendation", "rule": "words"},
                {"field": "conditions[0]", "rule": "file_path"},
            ],
        }
    ]


def test_the_repair_says_the_limits_and_where_technical_detail_goes() -> None:
    assert "one sentence of at most 20 words" in ANSWER_REPAIR
    assert "at most 3 items of at most 140 characters" in ANSWER_REPAIR
    assert "no file name, code or id" in ANSWER_REPAIR
    assert "reasoning" in ANSWER_REPAIR


def test_an_answer_without_an_object_is_repaired_with_that_finding() -> None:
    provider = Provider([said("Verdict: AGREE", tokens=5), said(standard(), tokens=6)])
    ask(provider)
    assert provider.asked[1][2]["content"] == f"answer: holds no JSON object\n{ANSWER_REPAIR}"


def test_a_second_failure_keeps_the_first_prose_as_unclear_and_logs_the_give_up(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = Provider([said("I think yes.", tokens=5), said(BROKEN, tokens=6)])
    with caplog.at_level(logging.INFO, logger="tralala.discussions"):
        asked = ask(provider)
    answer = asked["answer"]
    assert isinstance(answer, dict)
    assert asked["ok"] is True
    assert asked["content"] == "I think yes."
    assert (answer["format"], answer["position"]) == ("prose", "unclear")
    assert answer["problem"] == (
        "recommendation: 25 words; at most 20\nconditions[0]: looks like a file path (Banner.tsx)"
    )
    assert (asked["tokens"], asked["repairs"]) == (11, 1)
    assert logged(caplog) == [
        {
            "event": "discussion_answer_repair",
            **WHERE,
            "findings": [{"field": "answer", "rule": "no_object"}],
        },
        {
            "event": "discussion_answer_prose",
            **WHERE,
            "findings": [
                {"field": "recommendation", "rule": "words"},
                {"field": "conditions[0]", "rule": "file_path"},
            ],
        },
    ]


def test_a_failed_repair_call_keeps_the_first_answer_as_prose(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = Provider([said("I think yes."), failed("timeout")])
    with caplog.at_level(logging.INFO, logger="tralala.discussions"):
        asked = ask(provider)
    answer = asked["answer"]
    assert isinstance(answer, dict)
    assert (asked["ok"], asked["content"]) == (True, "I think yes.")
    assert answer["problem"] == "the repair call failed: timeout"
    assert [event["event"] for event in logged(caplog)] == [
        "discussion_answer_repair",
        "discussion_answer_prose",
    ]


def test_a_failed_first_call_is_a_failure_not_an_answer() -> None:
    asked = ask(Provider([failed("unreachable")]))
    assert (asked["ok"], asked["error"], asked["tokens"]) == (False, "unreachable", 0)


def test_usage_reads_the_total_or_adds_the_parts() -> None:
    assert usage_tokens({"usage": {"input_tokens": 2, "output_tokens": 3}}) == 5
    assert usage_tokens({"usage": []}) == 0
