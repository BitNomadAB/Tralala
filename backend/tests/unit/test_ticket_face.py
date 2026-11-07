"""The Ticket's face for people as pure functions: the counts, one row per rule of the check, the
refusal and its structured problems, the storage round trip and a payload stored before faces."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from pydantic import JsonValue

from app.core.errors import ValidationFailure
from app.schemas.loops import PlanPayload
from app.services.ticket_face import (
    FACE_ALLOWED_WORDS,
    FACE_INVALID,
    FACE_MAX_POINTS,
    FACE_MAX_SENTENCES,
    FACE_MAX_STEPS,
    FACE_MAX_SUMMARY_WORDS,
    FACE_MIN_STEPS,
    FaceProblem,
    FaceRefusal,
    code_symbol,
    face_findings,
    face_from_text,
    face_missing,
    face_problems,
    face_to_text,
    face_view,
    make_face,
    plan_face_findings,
    refuse_face,
    sentence_count,
    word_count,
)
from tests.unit.faces import FACE

TICKET = "PLN-023"


@dataclass(frozen=True, slots=True)
class Face:
    summary: str = "Show the answer under each open question."
    why: str = "A person cannot answer a question today. The Loop stops until they do."
    if_skipped: str = "Questions stay open and the work waits."
    pros: Sequence[str] = ("Answers land where the question is",)
    cons: Sequence[str] = ("One more field on the page",)
    steps: Sequence[str] = (
        "Under each open question, put an answer field",
        "Add a Go on without my answer button",
    )

    def problems(self) -> list[str]:
        return face_problems(
            TICKET, self.summary, self.why, self.if_skipped, self.pros, self.cons, self.steps
        )

    def findings(self) -> list[FaceProblem]:
        return face_findings(
            TICKET, self.summary, self.why, self.if_skipped, self.pros, self.cons, self.steps
        )


GOOD = Face()


def test_the_limits_are_the_owners_template() -> None:
    assert (FACE_MAX_SUMMARY_WORDS, FACE_MAX_SENTENCES, FACE_MAX_POINTS) == (20, 3, 3)
    assert (FACE_MIN_STEPS, FACE_MAX_STEPS) == (1, 5)
    assert FACE_ALLOWED_WORDS == ("RoadMap",)


def test_words_are_whitespace_separated_tokens() -> None:
    assert word_count("") == 0
    assert word_count("  one\ttwo\nthree  ") == 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes. No. Maybe?", 3),
        # An abbreviation ends a sentence; the text after it is one more.
        ("e.g. this", 2),
        ("", 0),
        ("   ", 0),
        ("No stop at the end", 1),
        ("Wait... what?!", 2),
        ("Version 3.5 ships.", 1),
    ],
)
def test_sentences_end_at_a_run_of_stops_before_whitespace_or_the_end(
    text: str, expected: int
) -> None:
    assert sentence_count(text) == expected


def test_a_face_that_keeps_the_template_has_no_problem() -> None:
    assert GOOD.problems() == []
    assert not face_missing(GOOD.summary, "", "", [], [], [])


# One row per rule: the face that breaks it and the one message it gets.
BAD_FACES: list[tuple[str, Face, str]] = [
    (
        "words",
        Face(summary=" ".join(["word"] * 26)),
        "Ticket PLN-023, summary: 26 words, at most 20.",
    ),
    (
        "sentences",
        Face(why="One. Two. Three. Four."),
        "Ticket PLN-023, why: 4 sentences, at most 3.",
    ),
    (
        "points",
        Face(pros=("a", "b", "c", "d")),
        "Ticket PLN-023, pros: 4 items, at most 3.",
    ),
    (
        "steps maximum",
        Face(steps=tuple(f"Step {n}" for n in range(7))),
        "Ticket PLN-023, steps: 7 items, at most 5. Split the Ticket into two.",
    ),
    (
        "steps minimum",
        Face(steps=()),
        "Ticket PLN-023, steps: missing. Write one to five steps, each saying what changes for "
        "the person.",
    ),
    (
        "a missing text",
        Face(if_skipped=" "),
        "Ticket PLN-023, if_skipped: missing. Say in at most 3 sentences what happens if we skip "
        "it.",
    ),
    (
        "an empty item",
        Face(cons=("Fine", " ")),
        "Ticket PLN-023, cons[1]: empty. Remove it or write it.",
    ),
    (
        "file name",
        Face(steps=("Show the list", "Open BriefView.tsx")),
        "Ticket PLN-023, steps[1]: looks like a file path (BriefView.tsx). Say what changes for "
        "the person, not where in the code.",
    ),
    (
        "path",
        Face(why="It lives in frontend/src/brief.ts today."),
        "Ticket PLN-023, why: looks like a file path (frontend/src/brief.ts).",
    ),
    (
        "code symbol",
        Face(cons=("Fine", "It touches loop_questions")),
        "Ticket PLN-023, cons[1]: looks like a code symbol (loop_questions).",
    ),
    (
        "camelCase",
        Face(steps=("Rename loopQuestions",)),
        "Ticket PLN-023, steps[0]: looks like a code symbol (loopQuestions). Say what changes for "
        "the person, not where in the code.",
    ),
    (
        "a call",
        Face(summary="Call save() before leaving."),
        "Ticket PLN-023, summary: looks like a code symbol (save()).",
    ),
    (
        "an arrow",
        Face(why="Draft -> review."),
        "Ticket PLN-023, why: looks like a code symbol (->).",
    ),
    (
        "fence",
        Face(why="See ``` below."),
        "Ticket PLN-023, why: contains a code fence.",
    ),
    (
        "code span",
        Face(pros=("Uses `answer` as it is",)),
        "Ticket PLN-023, pros[0]: contains code (`answer`).",
    ),
    (
        "UUID",
        Face(why="Ticket 3f2a0c1e-1111-4222-8333-444455556666 asked for it."),
        "Ticket PLN-023, why: contains an id (3f2a0c1e-1111-4222-8333-444455556666).",
    ),
    (
        "finding-like id",
        Face(if_skipped="The risk in F-12 stays open."),
        "Ticket PLN-023, if_skipped: contains a finding id (F-12).",
    ),
]


@pytest.mark.parametrize(("rule", "face", "message"), BAD_FACES, ids=[row[0] for row in BAD_FACES])
def test_each_rule_is_named_by_ticket_field_and_rule(rule: str, face: Face, message: str) -> None:
    assert face.problems() == [message], rule


def test_the_product_word_roadmap_is_not_a_code_symbol() -> None:
    assert Face(summary="Show the RoadMap's Tickets").problems() == []
    assert Face(steps=("Open the RoadMaps tab",)).problems() == []
    assert code_symbol("A link https://example.com/a_b and a word") is None
    assert code_symbol("Roadmap words only") is None


def test_a_missing_face_is_every_field_empty_and_checked_whole_names_each_field() -> None:
    assert face_missing("", " ", "", [], [" "], [])
    assert not face_missing("", "", "", [], [], ["One step"])
    empty = Face(summary="", why="", if_skipped="", pros=(), cons=(), steps=())
    assert [problem.field for problem in empty.findings()] == [
        "summary",
        "why",
        "if_skipped",
        "steps",
    ]
    assert {problem.rule for problem in empty.findings()} == {"missing"}


def test_a_problem_keeps_its_ticket_field_and_rule_and_the_messages_derive_from_it() -> None:
    face = Face(steps=tuple(f"Step {n}" for n in range(6)), cons=("Uses loop_questions",))
    findings = face.findings()
    assert [(p.ticket_id, p.field, p.rule) for p in findings] == [
        (TICKET, "cons[0]", "code_symbol"),
        (TICKET, "steps", "too_many"),
    ]
    assert [p.message for p in findings] == face.problems()
    assert findings[0].entry() == {"ticket_id": TICKET, "field": "cons[0]", "rule": "code_symbol"}


def test_a_refusal_is_face_invalid_with_every_message_and_the_structured_problems() -> None:
    refuse_face([])
    findings = Face(why="", steps=()).findings()
    with pytest.raises(FaceRefusal) as refused:
        refuse_face(findings)
    error = refused.value
    assert isinstance(error, ValidationFailure)
    assert (error.status_code, error.code) == (422, FACE_INVALID)
    messages = [problem.message for problem in findings]
    assert error.details == {
        "errors": messages,
        "error_count": 2,
        "faces": [dict(problem.entry()) for problem in findings],
    }
    assert error.message == "The face for people does not keep its template: " + " ".join(
        messages
    )
    assert error.lines() == "\n".join(messages)


def plan(**ticket: JsonValue) -> PlanPayload:
    return PlanPayload.model_validate(
        {
            "phases": [
                {
                    "id": "p1",
                    "number": 1,
                    "name": "Build",
                    "tickets": [{"id": "t1", "title": "Add the answer field", **ticket}],
                }
            ]
        }
    )


def test_every_planned_ticket_is_checked_by_the_id_its_writer_gave_it() -> None:
    assert plan_face_findings(plan(**FACE)) == []
    seven: dict[str, JsonValue] = {**FACE, "steps": [f"Step {n}" for n in range(7)]}
    findings = plan_face_findings(plan(**seven))
    assert [problem.message for problem in findings] == [
        "Ticket t1, steps: 7 items, at most 5. Split the Ticket into two."
    ]
    # A RoadMap Ticket without a face is checked whole: every field it must have is named.
    assert {problem.field for problem in plan_face_findings(plan())} == {
        "summary",
        "why",
        "if_skipped",
        "steps",
    }


def test_a_payload_stored_before_the_face_still_parses_with_an_empty_face() -> None:
    old = plan(summary="Adds the field.")
    (ticket,) = old.phases[0].tickets
    assert (ticket.why, ticket.if_skipped, ticket.pros, ticket.cons, ticket.steps) == (
        "",
        "",
        [],
        [],
        [],
    )
    # The face fields come last, so a model writes them with the whole Ticket before them.
    assert list(type(ticket).model_fields)[-5:] == ["why", "if_skipped", "pros", "cons", "steps"]


def test_the_face_is_stored_as_json_and_an_empty_one_is_no_face() -> None:
    face = make_face("Why.", "Skipped.", ["for"], ["against"], ["One", "Två"])
    text = face_to_text(face)
    assert json.loads(text) == face
    assert "Två" in text
    assert face_from_text(text) == face
    assert face_to_text(make_face()) == ""
    assert face_from_text("") is None
    assert face_view("Sum.", text) == {"summary": "Sum.", **face}
    assert face_view("Sum.", "") is None


@pytest.mark.parametrize(
    "stored",
    ["not json", "[]", '{"why": 3}', '{"steps": "one"}', '{"pros": ["a", 1]}'],
)
def test_a_column_that_does_not_hold_a_face_reads_as_none(stored: str) -> None:
    assert face_from_text(stored) is None


def test_a_stored_face_missing_a_field_reads_it_as_empty() -> None:
    assert face_from_text('{"steps": ["One"]}') == make_face(steps=["One"])
