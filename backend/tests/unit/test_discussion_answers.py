"""The discussion answer standard: reading an untrusted answer, the sign's limits and plain-text
rules with one good and one bad example per rule, and the decision support computed from the
latest answers. Pure functions; asking and repairing are ``test_discussion_ask``'s."""

from __future__ import annotations

import json

import pytest

from app.db.generated.board import DiscussionMessagesRow, DiscussionParticipantsRow
from app.services.discussion_answers import (
    ITEM_CHARS,
    ITEMS,
    MAX_FINDINGS,
    REASONING_CHARS,
    RECOMMENDATION_CHARS,
    RECOMMENDATION_WORDS,
    AnswerShapeError,
    DiscussionAnswer,
    answer_instructions,
    answer_line,
    answer_schema,
    finding,
    parse_answer,
    prose_answer,
    read_answer,
)
from app.services.discussion_synthesis import (
    Stance,
    latest_answers,
    positions,
    read_synthesis,
    suggest,
    synthesize,
)
from app.services.plain_text import sentence_count, word_count

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


def findings_of(payload: dict[str, object]) -> list[str]:
    with pytest.raises(AnswerShapeError) as broken:
        parse_answer(json.dumps(payload))
    return [item.message for item in broken.value.findings]


# --- reading an answer -------------------------------------------------------------------------


def test_the_limits_are_the_signs() -> None:
    assert (RECOMMENDATION_WORDS, RECOMMENDATION_CHARS) == (20, 200)
    assert (ITEMS, ITEM_CHARS, REASONING_CHARS) == (3, 140, 8000)


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


# A sign that keeps every limit: twenty words in one sentence, three items of 140 characters.
GOOD_SIGN = standard(
    recommendation=" ".join(["word"] * 19) + " end.",
    pros=["a" * ITEM_CHARS, "Users asked for it.", "It is small."],
    cons=["One more flag to remove.", "", "Support must learn it."],
    conditions=["A rollback exists."],
    open_questions=["Who owns the export after launch?"],
    reasoning="See `BannerView` in src/app/Banner.tsx:12 and "
    "1f0e2d3c-0000-4000-8000-000000000000.\n" + "x" * (REASONING_CHARS - 100),
)


def test_a_sign_at_every_limit_passes_and_the_reasoning_holds_anything() -> None:
    answer, prose = parse_answer(json.dumps(GOOD_SIGN))
    assert word_count(answer["recommendation"]) == RECOMMENDATION_WORDS
    assert answer["cons"] == ["One more flag to remove.", "Support must learn it."]
    assert answer["position"] == "yes_with_conditions"
    assert prose.startswith("See `BannerView` in src/app/Banner.tsx:12")


# One bad example per rule, with the one line it gets.
BAD_ANSWERS: list[tuple[str, dict[str, object], str]] = [
    (
        "words",
        standard(recommendation=" ".join(["word"] * 27)),
        "recommendation: 27 words; at most 20",
    ),
    (
        "sentences",
        standard(recommendation="Ship it. Then watch it."),
        "recommendation: 2 sentences; at most 1",
    ),
    (
        "chars",
        standard(recommendation=" ".join(["x" * 20] * 10)),
        "recommendation: 209 characters; at most 200",
    ),
    (
        "missing",
        standard(recommendation=" "),
        "recommendation: missing; say in one sentence of at most 20 words what the person "
        "should do",
    ),
    ("too_many", standard(pros=["a", "b", "c", "d", "e"]), "pros: 5 items; at most 3"),
    ("item_chars", standard(cons=["x" * 141]), "cons[0]: 141 characters; at most 140"),
    (
        "file_path",
        standard(conditions=["A rollback exists.", "Keep Banner.tsx as it is."]),
        "conditions[1]: looks like a file path (Banner.tsx)",
    ),
    (
        "folder_path",
        standard(pros=["It changes src/app/Banner.tsx only."]),
        "pros[0]: looks like a file path (src/app/Banner.tsx)",
    ),
    (
        "code_span",
        standard(cons=["The `banner` flag stays."]),
        "cons[0]: contains code (`banner`)",
    ),
    ("code_fence", standard(pros=["Put it in a ``` block."]), "pros[0]: contains a code fence"),
    (
        "code_symbol",
        standard(recommendation="Rename loop_questions before the release."),
        "recommendation: looks like a code symbol (loop_questions)",
    ),
    (
        "id",
        standard(cons=["Ticket 1f0e2d3c-0000-4000-8000-000000000000 is open."]),
        "cons[0]: contains an id (1f0e2d3c-0000-4000-8000-000000000000)",
    ),
    (
        "finding_id",
        standard(position="unclear", open_questions=["Is F-12 still true?"]),
        "open_questions[0]: contains a finding id (F-12)",
    ),
    (
        "conditions",
        standard(position="yes_with_conditions"),
        "conditions: missing; yes_with_conditions needs at least one",
    ),
    (
        "open_questions",
        standard(position="unclear"),
        "open_questions: missing; unclear needs at least one",
    ),
    (
        "position",
        standard(position="agree"),
        "position: must be one of yes, yes_with_conditions, no, unclear",
    ),
    (
        "confidence",
        standard(confidence="sure"),
        "confidence: must be one of high, medium, low",
    ),
    ("list_type", standard(cons="one"), "cons: must be a list of strings"),
    ("item_type", standard(cons=["one", 2]), "cons: must be a list of strings"),
    ("text_type", standard(recommendation=["Ship."]), "recommendation: must be a string"),
    (
        "reasoning",
        standard(reasoning="x" * (REASONING_CHARS + 1)),
        "reasoning: 8001 characters; at most 8000",
    ),
]


@pytest.mark.parametrize(
    ("rule", "payload", "message"), BAD_ANSWERS, ids=[r[0] for r in BAD_ANSWERS]
)
def test_an_answer_that_breaks_one_rule_gets_its_one_line(
    rule: str, payload: dict[str, object], message: str
) -> None:
    del rule
    assert findings_of(payload) == [message]


def test_every_finding_is_collected_before_the_answer_is_refused() -> None:
    payload = standard(
        recommendation=" ".join(["word"] * 26) + ". More.",
        pros=["a", "b", "c", "d"],
        conditions=["Keep Banner.tsx as it is."],
        confidence="sure",
    )
    with pytest.raises(AnswerShapeError) as broken:
        parse_answer(json.dumps(payload))
    assert str(broken.value) == (
        "recommendation: 27 words; at most 20\n"
        "recommendation: 2 sentences; at most 1\n"
        "pros: 4 items; at most 3\n"
        "conditions[0]: looks like a file path (Banner.tsx)\n"
        "confidence: must be one of high, medium, low"
    )
    assert broken.value.entries() == [
        {"field": "recommendation", "rule": "words"},
        {"field": "recommendation", "rule": "sentences"},
        {"field": "pros", "rule": "too_many"},
        {"field": "conditions[0]", "rule": "file_path"},
        {"field": "confidence", "rule": "choice"},
    ]


def test_the_lines_of_a_refusal_stop_at_the_bound_and_say_how_many_more() -> None:
    error = AnswerShapeError([finding(f"pros[{n}]", "chars", "long") for n in range(25)])
    lines = error.lines().splitlines()
    assert len(lines) == MAX_FINDINGS + 1
    assert lines[-1] == "(and 5 more)"


def test_an_answer_without_an_object_is_refused() -> None:
    with pytest.raises(AnswerShapeError, match=r"^answer: holds no JSON object$"):
        parse_answer("I agree with Beta.\nVerdict: AGREE")
    with pytest.raises(AnswerShapeError, match=r"^answer: 60001 characters; at most 60000$"):
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


def test_an_answer_stored_under_the_old_limits_reads_as_it_was_written() -> None:
    old: DiscussionAnswer = {
        "version": 1,
        "format": "structured",
        "position": "yes",
        "recommendation": "x" * 290 + " see Banner.tsx.",
        "pros": ["one", "two", "three", "four", "five"],
        "cons": ["y" * 200],
        "conditions": [],
        "open_questions": [],
        "confidence": "high",
        "problem": None,
    }
    assert read_answer(json.dumps(old)) == old


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


def test_the_schema_carries_the_limits() -> None:
    properties = answer_schema()["schema"]["properties"]
    assert isinstance(properties, dict)
    assert properties["recommendation"] == {"type": "string", "maxLength": 200}
    for name in ("pros", "cons", "conditions", "open_questions"):
        assert properties[name] == {
            "type": "array",
            "items": {"type": "string", "maxLength": 140},
            "maxItems": 3,
        }
    assert properties["reasoning"] == {"type": "string", "maxLength": 8000}


def test_the_prompt_says_the_limits_and_who_reads_which_part() -> None:
    instructions = answer_instructions()
    assert "one sentence of at most 20 words" in instructions
    assert "at most 3 items of at most 140 characters" in instructions
    assert "The recommendation and the lists are what the person reads" in instructions
    assert "no file name, code or id" in instructions
    assert "The reasoning is read by the other agents and shown to the person as raw text" in (
        instructions
    )
    assert "as long and technical as it needs to be" in instructions


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
        "reason": "The participants differ: 1 for going ahead, 1 against and 1 has not answered.",
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
        "reason": "Not settled yet: 1 for going ahead and 2 cannot tell; read the open questions.",
    }
    assert made["open_questions"] == [{"text": "Who owns the export?", "participants": ["Gamma"]}]


def stance(name: str, position: str) -> Stance:
    return {
        "participant_id": name.lower(),
        "participant": name,
        "position": position,
        "recommendation": "Go.",
        "confidence": "high",
        "format": "structured",
        "message_id": f"m-{name.lower()}",
        "round_number": 1,
    }


def many(count: int, position: str) -> list[Stance]:
    return [stance(f"Agent{n}", position) for n in range(count)]


# Every branch of the suggestion, the one with go, stop, unclear and missing at once included,
# with long names and two-digit counts, so a branch that names someone or chains clauses shows.
BRANCHES: list[tuple[str, list[Stance], list[Stance], list[Stance], list[str]]] = [
    ("nobody", [], [], [], ["A Very Long Participant Name"] * 12),
    ("yes", many(12, "yes"), [], [], []),
    ("yes_with_conditions", many(12, "yes_with_conditions"), [], [], []),
    ("no", [], many(12, "no"), [], []),
    ("split", many(11, "yes"), many(12, "no"), [], []),
    ("split_missing", many(11, "yes"), many(12, "no"), [], ["Missing One"] * 13),
    ("split_unclear", many(11, "yes"), many(12, "no"), many(14, "unclear"), []),
    (
        "go_stop_unclear_missing",
        many(11, "yes"),
        many(12, "no"),
        many(14, "unclear"),
        ["A Very Long Participant Name"] * 15,
    ),
    ("go_unclear_missing", many(11, "yes"), [], many(14, "unclear"), ["Late"] * 15),
    ("stop_unclear_missing", [], many(12, "no"), many(14, "unclear"), ["Late"] * 15),
    ("go_missing", many(11, "yes"), [], [], ["Late"]),
    ("stop_missing", [], many(12, "no"), [], ["Late"] * 2),
    ("unclear_only", [], [], many(14, "unclear"), []),
]


@pytest.mark.parametrize(
    ("branch", "go", "stop", "unclear", "missing"), BRANCHES, ids=[b[0] for b in BRANCHES]
)
def test_every_suggestion_is_one_sentence_of_at_most_twenty_words_naming_nobody(
    branch: str, go: list[Stance], stop: list[Stance], unclear: list[Stance], missing: list[str]
) -> None:
    del branch
    reason = suggest(go, stop, unclear, missing)["reason"]
    assert word_count(reason) <= RECOMMENDATION_WORDS, reason
    assert sentence_count(reason) == 1, reason
    names = {item["participant"] for item in (*go, *stop, *unclear)} | set(missing)
    assert not any(name in reason for name in names), reason


def test_the_unclear_suggestion_counts_every_side_in_one_sentence() -> None:
    suggestion = suggest(many(1, "yes"), many(1, "no"), many(1, "unclear"), ["Gamma", "Delta"])
    assert suggestion == {
        "verdict": "unclear",
        "reason": (
            "The participants differ: 1 for going ahead, 1 against, 1 cannot tell and 2 have not "
            "answered."
        ),
    }
    assert suggest(many(2, "yes"), [], [], ["Gamma"])["reason"] == (
        "Not settled yet: 2 for going ahead and 1 has not answered."
    )


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
