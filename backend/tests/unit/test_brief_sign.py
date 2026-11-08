"""The analysis brief as a sign, as pure rules: the verdict in one line, at most three reasons and
three points each way, at most five questions on one line each, how big the work is, and every item
short. A brief written before the sign still reads; the schema a writer is shown carries the
sign's limits."""

from __future__ import annotations

import json

import pytest
from pydantic import JsonValue

from app.core.errors import ValidationFailure
from app.schemas.briefs import HumanBrief
from app.schemas.loops import AnalysisPayload
from app.services.loop_documents_human import check_analysis_brief, render_brief
from app.services.loop_documents_human_limits import (
    SIGN_QUESTION_EXAMPLE,
    BriefRefusal,
    refuse_sign,
    sign_findings,
)
from app.services.plain_text import text_problems
from tests.unit.signs import SIGN

ANALYSIS = AnalysisPayload.model_validate(
    {
        "outcome": "Verify addresses",
        "findings": [
            {
                "id": "F-1",
                "title": "Bounces",
                "category": "risk",
                "technical_detail": "No bounce handling.",
                "plain_language": "Some mail is lost.",
            }
        ],
    }
)
OBSTACLE: dict[str, JsonValue] = {
    "level": "technical",
    "text": "Some e-mails never arrive.",
    "finding_ids": ["F-1"],
}
POINT: dict[str, JsonValue] = {"text": "The sign-in can already send mail."}
QUESTION: dict[str, JsonValue] = {"question": "Which mail provider do we use?"}


def brief(**fields: JsonValue) -> HumanBrief:
    base: dict[str, JsonValue] = {
        **SIGN,
        "obstacles": [OBSTACLE],
        "pros": [POINT],
        "cons": [POINT],
        "decisions": [QUESTION],
        "verdict": "yes_with_conditions",
        "verdict_reason": "It works once bounces are handled.",
        "summary": "People confirm their address by e-mail.",
        "recommendation": "Go ahead.",
    }
    return HumanBrief.model_validate({**base, **fields})


def many(item: JsonValue, count: int) -> list[JsonValue]:
    return [item] * count


def words(count: int) -> str:
    return " ".join(["word"] * count)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="the fixture"),
        pytest.param({"verdict_line": words(20)}, id="20 words"),
        pytest.param({"obstacles": many(OBSTACLE, 3)}, id="3 obstacles"),
        pytest.param({"obstacles": []}, id="no obstacle"),
        pytest.param({"pros": many(POINT, 3), "cons": many(POINT, 3)}, id="3 pros and 3 cons"),
        pytest.param({"decisions": many(QUESTION, 5)}, id="5 questions"),
        pytest.param({"decisions": []}, id="nothing to decide"),
        pytest.param({"obstacles": [{**OBSTACLE, "text": "x" * 140}]}, id="140 characters"),
        pytest.param({"size": {"kind": "large", "text": "y" * 140}}, id="a size of 140"),
        pytest.param({"size": {"kind": "medium", "text": "Two screens, 3.5 days."}}, id="3.5"),
    ],
)
def test_a_brief_that_keeps_the_sign_has_no_problem(fields: dict[str, JsonValue]) -> None:
    assert sign_findings(brief(**fields)) == []


@pytest.mark.parametrize(
    ("fields", "field", "rule", "message"),
    [
        (
            {"verdict_line": ""},
            "verdict_line",
            "missing",
            "Brief, verdict_line: missing. Say the verdict in one line of at most 20 words.",
        ),
        (
            {"verdict_line": words(21)},
            "verdict_line",
            "words",
            "Brief, verdict_line: 21 words, at most 20.",
        ),
        (
            {"verdict_line": "Yes.\nBut later."},
            "verdict_line",
            "lines",
            "Brief, verdict_line: 2 lines, at most 1.",
        ),
        (
            {"obstacles": many(OBSTACLE, 4)},
            "obstacles",
            "too_many",
            "Brief, obstacles: 4 items, at most 3.",
        ),
        (
            {"obstacles": [{**OBSTACLE, "text": "x" * 141}]},
            "obstacles[0].text",
            "chars",
            "Brief, obstacles[0].text: 141 characters, at most 140.",
        ),
        ({"pros": many(POINT, 4)}, "pros", "too_many", "Brief, pros: 4 items, at most 3."),
        ({"cons": many(POINT, 5)}, "cons", "too_many", "Brief, cons: 5 items, at most 3."),
        (
            {"cons": [POINT, {"text": "z" * 150}]},
            "cons[1].text",
            "chars",
            "Brief, cons[1].text: 150 characters, at most 140.",
        ),
        (
            {"decisions": many(QUESTION, 6)},
            "decisions",
            "too_many",
            "Brief, decisions: 6 items, at most 5.",
        ),
        (
            {"decisions": [QUESTION, {"question": "q" * 141}]},
            "decisions[1].question",
            "chars",
            "Brief, decisions[1].question: 141 characters, at most 140.",
        ),
        (
            {"decisions": [{"question": "Which provider?\nAnd when?"}]},
            "decisions[0].question",
            "lines",
            "Brief, decisions[0].question: 2 lines, at most 1.",
        ),
        (
            {"size": None},
            "size",
            "missing",
            "Brief, size: missing. Say how big the work is: small, medium or large, and why in "
            "one sentence.",
        ),
        (
            {"size": {"kind": "small", "text": "One screen. One e-mail."}},
            "size.text",
            "sentences",
            "Brief, size.text: 2 sentences, at most 1.",
        ),
        (
            # The face's count: an abbreviation ends a sentence too, so the size avoids one.
            {"size": {"kind": "medium", "text": "Two screens, e.g. the list."}},
            "size.text",
            "sentences",
            "Brief, size.text: 2 sentences, at most 1.",
        ),
        (
            {"size": {"kind": "small", "text": "s" * 141}},
            "size.text",
            "chars",
            "Brief, size.text: 141 characters, at most 140.",
        ),
    ],
)
def test_each_rule_of_the_sign_names_the_field_and_the_rule(
    fields: dict[str, JsonValue], field: str, rule: str, message: str
) -> None:
    (problem,) = sign_findings(brief(**fields))
    assert (problem.field, problem.rule, problem.message) == (field, rule, message)


def test_the_problems_come_in_the_order_a_person_reads_the_brief() -> None:
    broken = brief(verdict_line="", obstacles=many(OBSTACLE, 4), size=None)
    assert [problem.field for problem in sign_findings(broken)] == [
        "verdict_line",
        "obstacles",
        "size",
    ]


def test_a_refusal_is_brief_invalid_with_the_sign_first_and_the_other_rules_after() -> None:
    # Four points for, and the obstacle that named the risk finding gone.
    broken = brief(obstacles=[], pros=many(POINT, 4))
    others = check_analysis_brief(broken, ANALYSIS)["problems"]
    assert len(others) == 1 and "no item names F-1" in others[0]
    with pytest.raises(BriefRefusal) as refused:
        refuse_sign(sign_findings(broken), others)
    error = refused.value
    assert isinstance(error, ValidationFailure)
    assert error.code == "brief_invalid"
    assert error.messages() == ["Brief, pros: 4 items, at most 3.", *others]
    assert error.details is not None
    assert error.details["rules"] == [{"field": "pros", "rule": "too_many"}]
    assert error.details["other_errors"] == others
    assert error.details["error_count"] == 1 + len(others)
    assert error.lines() == "\n".join(error.messages())
    refuse_sign([])  # a sign that holds raises nothing


def test_a_refusal_without_a_sign_problem_keeps_the_content_code() -> None:
    refusal = BriefRefusal((), ["finding_ids: no item names F-1"])
    assert refusal.code == "brief_rejected"
    assert refusal.details is not None and refusal.details["rules"] == []


def test_the_verdict_line_and_the_size_are_held_to_the_plain_text_rules() -> None:
    noisy = brief(
        verdict_line="Yes, see mail/send.py first.",
        size={"kind": "small", "text": "One change in `send`."},
    )
    check = check_analysis_brief(noisy, ANALYSIS)
    assert check["fields"] == ["verdict_line", "size.text"]


def test_the_example_question_keeps_the_sign() -> None:
    assert sign_findings(brief(decisions=[{"question": SIGN_QUESTION_EXAMPLE}])) == []
    assert text_problems(SIGN_QUESTION_EXAMPLE, []) == []


# --- a brief written before the sign -------------------------------------------------------------

OLD_BRIEF: dict[str, JsonValue] = {
    "obstacles": many({**OBSTACLE, "text": "o" * 300}, 8),
    "pros": many({"text": "p" * 200}, 5),
    "cons": many({"text": "c" * 200}, 5),
    "decisions": many({"question": "d" * 200, "finding_ids": ["F-1"]}, 8),
    "verdict": "yes",
    "verdict_reason": "It can be done.",
    "summary": "People confirm by e-mail.",
    "recommendation": "Go ahead.",
}


def test_a_brief_stored_before_the_sign_still_reads_as_it_was() -> None:
    old = HumanBrief.model_validate(OLD_BRIEF)
    assert (old.verdict_line, old.size, len(old.obstacles), len(old.decisions)) == ("", None, 8, 8)
    dumped = old.model_dump()
    assert dumped["obstacles"] == OLD_BRIEF["obstacles"]
    assert (dumped["verdict_line"], dumped["size"]) == ("", None)
    # Rendered without the parts it does not have; only a new hand-in is held to the sign.
    text = render_brief(old, ANALYSIS.model_dump())
    assert "In short" not in text and "How big" not in text
    assert {problem.rule for problem in sign_findings(old)} == {"missing", "too_many", "chars"}


def test_a_new_brief_renders_its_verdict_line_and_its_size() -> None:
    text = render_brief(brief(), ANALYSIS.model_dump())
    assert "**In short:** Yes, once the e-mails that never arrive are handled." in text
    assert "## How big\n\n**Small.** One change to sign-in and one new e-mail." in text


def test_the_schema_a_writer_is_shown_carries_the_sign_and_parses_the_old_limits() -> None:
    schema = HumanBrief.model_json_schema()
    properties = json.dumps(schema["properties"])
    for name, most in (("obstacles", 3), ("pros", 3), ("cons", 3), ("decisions", 5)):
        shown = HumanBrief.model_json_schema()["properties"][name]
        assert f'"maxItems": {most}' in json.dumps(shown), name
    assert '"maxItems": 8' not in properties
    definitions = json.dumps(schema["$defs"])
    assert '"maxLength": 140' in definitions
    assert "small" in json.dumps(schema["$defs"]["BriefSize"])
    # A list longer than the old limit is refused by the schema itself, as before.
    with pytest.raises(ValueError):
        HumanBrief.model_validate({**OLD_BRIEF, "obstacles": many(OBSTACLE, 9)})
