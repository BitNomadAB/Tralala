"""The discussion answer standard: reading an untrusted answer, asking with one repair, and the
decision support computed from the latest answers. Pure functions and a scripted provider."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from app.db.generated.board import DiscussionMessagesRow, DiscussionParticipantsRow
from app.services.discussion_answers import (
    AnswerShapeError,
    DiscussionAnswer,
    answer_instructions,
    answer_line,
    answer_schema,
    parse_answer,
    prose_answer,
    read_answer,
)
from app.services.discussion_ask import ask_participant, usage_tokens
from app.services.discussion_synthesis import (
    latest_answers,
    positions,
    read_synthesis,
    synthesize,
)
from app.services.runtime import Completion, ResponseSchema
from app.services.runtime_tools import Message

NOW = "2026-11-07T10:00:00Z"


def standard(**fields: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "position": "yes",
        "recommendation": "Ship it behind a flag.",
        "pros": ["Users asked for it."],
        "cons": ["One more flag to remove."],
        "confidence": "high",
        "reasoning": "The **change** is small.",
    }
    payload.update(fields)
    return payload


# --- reading an answer -------------------------------------------------------------------------


def test_a_whole_json_answer_is_read_with_its_reasoning_as_the_prose() -> None:
    answer, prose = parse_answer(json.dumps(standard(extra="ignored")))
    assert prose == "The **change** is small."
    assert answer == {
        "version": 1,
        "format": "structured",
        "position": "yes",
        "recommendation": "Ship it behind a flag.",
        "pros": ["Users asked for it."],
        "cons": ["One more flag to remove."],
        "conditions": [],
        "open_questions": [],
        "confidence": "high",
        "problem": None,
    }


def test_prose_around_the_object_is_the_prose_when_reasoning_is_missing() -> None:
    payload = standard(reasoning=None, note={"nested": True})
    text = "I looked at the storage layer.\n\n" + json.dumps(payload)
    answer, prose = parse_answer(text)
    assert answer["position"] == "yes"
    assert prose == "I looked at the storage layer."


def test_a_fenced_object_is_read_and_the_text_around_it_kept() -> None:
    text = "My view first.\n```json\n" + json.dumps(standard(reasoning="")) + "\n```\nThanks."
    answer, prose = parse_answer(text)
    assert answer["recommendation"] == "Ship it behind a flag."
    assert prose == "My view first.\n\nThanks."


def test_an_answer_without_prose_keeps_its_recommendation_as_content() -> None:
    _, prose = parse_answer(json.dumps(standard(reasoning="")))
    assert prose == "Ship it behind a flag."


def test_a_yes_with_conditions_reads_as_yes_with_conditions() -> None:
    answer, _ = parse_answer(json.dumps(standard(conditions=["A rollback exists."])))
    assert (answer["position"], answer["conditions"]) == (
        "yes_with_conditions",
        ["A rollback exists."],
    )


@pytest.mark.parametrize(
    ("payload", "problem"),
    [
        (standard(position="agree"), "`position` must be one of"),
        (standard(position="yes_with_conditions"), "needs at least one item in `conditions`"),
        (standard(position="unclear"), "needs at least one item in `open_questions`"),
        (standard(recommendation=" "), "`recommendation` must not be empty"),
        (standard(recommendation="x" * 301), "at most 300"),
        (standard(pros=["a", "b", "c", "d", "e", "f"]), "`pros` has 6 items; at most 5"),
        (standard(cons=["x" * 201]), "an item of `cons` has 201 characters"),
        (standard(cons="one"), "`cons` must be a list of strings"),
        (standard(confidence="sure"), "`confidence` must be one of high, medium, low"),
    ],
)
def test_an_answer_that_breaks_the_standard_names_the_rule(
    payload: dict[str, object], problem: str
) -> None:
    with pytest.raises(AnswerShapeError) as broken:
        parse_answer(json.dumps(payload))
    assert problem in str(broken.value)


def test_an_answer_without_an_object_is_refused() -> None:
    with pytest.raises(AnswerShapeError, match="no JSON object"):
        parse_answer("I agree with Beta.\nVerdict: AGREE")
    with pytest.raises(AnswerShapeError, match="at most 60000"):
        parse_answer("x" * 60_001)


def test_a_stored_answer_reads_back_and_anything_else_reads_as_none() -> None:
    answer, _ = parse_answer(json.dumps(standard()))
    assert read_answer(json.dumps(answer)) == answer
    assert read_answer("{}") is None
    assert read_answer("not json") is None
    assert read_answer('{"version": 1, "position": "maybe", "pros": "x"}') == {
        **prose_answer(""),
        "problem": None,
    }


def test_the_transcript_line_names_the_position_and_recommendation() -> None:
    answer, _ = parse_answer(json.dumps(standard()))
    assert answer_line(answer) == "(position: yes; recommendation: Ship it behind a flag.)"
    assert answer_line(prose_answer("no object")) == "(position: unclear; answered in prose only)"
    assert answer_line(None) == ""


def test_the_prompt_and_the_schema_name_the_same_closed_sets() -> None:
    schema = answer_schema()
    properties = schema["schema"]["properties"]
    assert isinstance(properties, dict)
    assert properties["position"] == {
        "type": "string",
        "enum": ["yes", "yes_with_conditions", "no", "unclear"],
    }
    instructions = answer_instructions()
    assert '"yes" | "yes_with_conditions" | "no" | "unclear"' in instructions
    assert "A person decides" in instructions


# --- asking with one repair --------------------------------------------------------------------


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


def test_a_valid_answer_costs_one_call() -> None:
    provider = Provider([said(json.dumps(standard()), tokens=7)])
    asked = ask_participant(provider, object(), {"id": "a"}, system_prompt="s", messages=QUESTION)
    assert (asked["answer"]["format"], asked["tokens"], asked["repairs"]) == ("structured", 7, 0)
    assert len(provider.asked) == 1


def test_an_answer_that_needs_repair_is_asked_once_more_with_the_problem() -> None:
    provider = Provider([said("Verdict: AGREE", tokens=5), said(json.dumps(standard()), tokens=6)])
    asked = ask_participant(provider, object(), {"id": "a"}, system_prompt="s", messages=QUESTION)
    assert (asked["answer"]["format"], asked["tokens"], asked["repairs"]) == ("repaired", 11, 1)
    assert asked["content"] == "The **change** is small."
    repair = provider.asked[1]
    assert [message["role"] for message in repair] == ["user", "assistant", "user"]
    assert repair[1]["content"] == "Verdict: AGREE"
    assert "did not validate" in repair[2]["content"]
    assert "the answer holds no JSON object" in repair[2]["content"]


def test_an_answer_that_stays_invalid_is_kept_as_prose_and_unclear() -> None:
    provider = Provider([said("I think yes.", tokens=5), said('{"position": "agree"}', tokens=6)])
    asked = ask_participant(provider, object(), {"id": "a"}, system_prompt="s", messages=QUESTION)
    assert asked["ok"] is True
    assert asked["content"] == "I think yes."
    assert asked["answer"]["format"] == "prose"
    assert asked["answer"]["position"] == "unclear"
    assert (
        asked["answer"]["problem"]
        == "`position` must be one of yes, yes_with_conditions, no, unclear"
    )
    assert (asked["tokens"], asked["repairs"]) == (11, 1)


def test_a_failed_repair_call_keeps_the_first_answer_as_prose() -> None:
    provider = Provider([said("I think yes."), failed("timeout")])
    asked = ask_participant(provider, object(), {"id": "a"}, system_prompt="s", messages=QUESTION)
    assert (asked["ok"], asked["content"]) == (True, "I think yes.")
    assert asked["answer"]["problem"] == "the repair call failed: timeout"


def test_a_failed_first_call_is_a_failure_not_an_answer() -> None:
    asked = ask_participant(
        Provider([failed("unreachable")]), object(), {}, system_prompt="s", messages=QUESTION
    )
    assert (asked["ok"], asked["error"], asked["tokens"]) == (False, "unreachable", 0)


def test_usage_reads_the_total_or_adds_the_parts() -> None:
    assert usage_tokens({"usage": {"input_tokens": 2, "output_tokens": 3}}) == 5
    assert usage_tokens({"usage": []}) == 0


# --- the synthesis ------------------------------------------------------------------------------


def participant(agent_id: str) -> DiscussionParticipantsRow:
    return DiscussionParticipantsRow(
        id=f"p-{agent_id}",
        discussion_id="t",
        participant_id=agent_id,
        participant_type="agent",
        display_name=agent_id.title(),
        role_template_id=None,
        role_template_name="Reviewer",
        role_template_updated_at=None,
        role_source="default",
        system_prompt="Review it.",
        system_prompt_sha256="0" * 64,
        snapshot_at=NOW,
        joined_at=NOW,
    )


def message(
    agent_id: str, answer: DiscussionAnswer | None, number: int = 1
) -> DiscussionMessagesRow:
    return DiscussionMessagesRow(
        id=f"m-{agent_id}-{number}",
        discussion_id="t",
        parent_message_id=None,
        author_actor_id=agent_id,
        author_type="agent",
        author_name=agent_id.title(),
        author_role="Reviewer",
        content="prose",
        status="posted",
        model="m",
        created_at=NOW,
        deleted_at=None,
        round_number=number,
        content_sha256=None,
        answer_json="{}" if answer is None else json.dumps(answer),
    )


def stated(**fields: object) -> DiscussionAnswer:
    answer, _ = parse_answer(json.dumps(standard(**fields)))
    return answer


PEOPLE = [participant("alpha"), participant("beta"), participant("gamma")]


def synthesis_of(*rows: DiscussionMessagesRow) -> dict[str, object]:
    latest = latest_answers(list(rows), PEOPLE)
    made = synthesize(PEOPLE, latest, round_number=2, thread_round=3)
    return dict(made)


def test_every_yes_suggests_yes() -> None:
    made = synthesis_of(*(message(p.participant_id, stated()) for p in PEOPLE))
    assert made["suggestion"] == {
        "verdict": "yes",
        "reason": "Every participant supports going ahead.",
    }
    assert made["kind"] == "decision_support"
    assert (made["round_number"], made["thread_round"]) == (2, 3)


def test_a_yes_with_conditions_suggests_it_and_lists_each_condition_once() -> None:
    made = synthesis_of(
        message("alpha", stated()),
        message("beta", stated(conditions=["A rollback exists."])),
        message("gamma", stated(conditions=["a rollback  exists.", "Docs are updated."])),
    )
    assert made["suggestion"] == {
        "verdict": "yes_with_conditions",
        "reason": "Every participant supports going ahead; read the conditions before you do.",
    }
    assert made["conditions"] == [
        {"text": "A rollback exists.", "participants": ["Beta", "Gamma"]},
        {"text": "Docs are updated.", "participants": ["Gamma"]},
    ]


def test_every_no_suggests_no() -> None:
    made = synthesis_of(*(message(p.participant_id, stated(position="no")) for p in PEOPLE))
    assert made["suggestion"] == {
        "verdict": "no",
        "reason": "Every participant advises against going ahead.",
    }


def test_a_split_an_unclear_and_a_missing_answer_suggest_unclear_and_say_why() -> None:
    made = synthesis_of(
        message("alpha", stated()),
        message("beta", stated(position="no", recommendation="Wait for the rollback.")),
    )
    assert made["suggestion"] == {
        "verdict": "unclear",
        "reason": (
            "The participants differ: 1 for going ahead, 1 against. No answer yet from Gamma."
        ),
    }
    assert made["missing"] == ["Gamma"]
    assert made["counts"] == {
        "yes": 1,
        "yes_with_conditions": 0,
        "no": 1,
        "unclear": 0,
        "missing": 1,
    }
    made = synthesis_of(
        message("alpha", stated()),
        message("beta", prose_answer("no object")),
        message("gamma", stated(position="unclear", open_questions=["Who owns the export?"])),
    )
    assert made["suggestion"] == {
        "verdict": "unclear",
        "reason": "Beta and Gamma cannot tell yet; read the open questions.",
    }
    assert made["open_questions"] == [{"text": "Who owns the export?", "participants": ["Gamma"]}]


def test_nobody_answering_and_answers_before_the_standard_read_as_missing() -> None:
    made = synthesis_of(message("alpha", None))
    assert made["suggestion"] == {
        "verdict": "unclear",
        "reason": "Nobody has answered in the standard form yet.",
    }
    assert made["missing"] == ["Alpha", "Beta", "Gamma"]


def test_positions_are_the_latest_answer_of_each_participant_in_joining_order() -> None:
    rows = [
        message("beta", stated(position="no"), 1),
        message("alpha", stated(), 1),
        message("beta", stated(), 2),
    ]
    current = positions(PEOPLE, latest_answers(rows, PEOPLE))
    assert [(s["participant"], s["position"], s["round_number"]) for s in current] == [
        ("Alpha", "yes", 1),
        ("Beta", "yes", 2),
    ]


def test_a_stored_synthesis_reads_back_and_anything_else_reads_as_none() -> None:
    made = synthesis_of(message("alpha", stated()))
    assert read_synthesis(json.dumps(made)) == made
    assert read_synthesis("{}") is None
    assert read_synthesis("[") is None
