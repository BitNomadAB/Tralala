"""The pure rules of a POC decision: the limits and the plain-text check, the key, the same
record again, the review order, when a record is due, the counts, and the text of the Ticket
feedback becomes."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationFailure
from app.db.generated.board import PocDecisionsRow
from app.repositories.poc_decisions import PocDecisionMark
from app.services.loop_identifiers import format_poc_key
from app.services.plan_views import PhaseView, Readiness, ReadinessItem, UnplannedTicket
from app.services.poc_decision_rules import (
    POC_DECISION_INVALID,
    POC_DETAILS_MAX_CHARS,
    POC_TEXT_MAX_CHARS,
    POC_TEXT_MAX_SENTENCES,
    POC_TITLE_MAX_CHARS,
    TICKET_DESCRIPTION_MAX_CHARS,
    TICKET_TITLE_MAX_CHARS,
    LoopProgress,
    PocDecisionRefusal,
    TicketPhase,
    check_record,
    duplicate_of,
    feedback_description,
    feedback_title,
    is_due,
    loop_progress,
    next_sequence,
    poc_counts,
    poc_problems,
    review_order,
    review_rank,
)
from tests.unit.fakes.plans import readiness_item

DECISION = {
    "title": "Store the list in the browser",
    "chosen": "The list lives in the browser for now.",
    "reason": "It is the quickest way to show the page.",
    "alternative": "Keep it on the server.",
    "change_path": "Move the list to the server later; nothing else changes.",
}
MISSING = {
    "title": "No mail account",
    "missing": "An account for the mail service.",
    "reason": "The invitation mail needs it.",
    "chosen": "Invitations are shown as a link to copy.",
    "change_path": "Send the mail once the account is there.",
}


def poc_row(
    sequence: int,
    *,
    kind: str = "decision",
    status: str = "open",
    builds_on: str = "",
    card_id: str | None = None,
    title: str = "A choice",
    chosen: str = "This one.",
) -> PocDecisionsRow:
    answered = None if status == "open" else "2026-11-26T10:00:00Z"
    return PocDecisionsRow(
        id=f"poc-{sequence}",
        loop_id="loop-a",
        card_id=card_id,
        sequence=sequence,
        key=format_poc_key("L-1", sequence),
        kind=kind,
        title=title,
        chosen=chosen,
        reason="Because.",
        alternative="That one.",
        change_path="Change it later.",
        missing="",
        builds_on=builds_on,
        details="",
        status=status,
        feedback="",
        feedback_card_id=None,
        created_by_actor_id="agent-1",
        created_by_type="agent",
        created_by_name="Worker",
        created_at="2026-11-26T09:00:00Z",
        answered_by_actor_id=None if answered is None else "user-ada",
        answered_by_name=None if answered is None else "Ada",
        answered_at=answered,
    )


def mark(
    *,
    status: str = "open",
    kind: str = "decision",
    built_on: bool = False,
    card_id: str | None = "card-1",
) -> PocDecisionMark:
    return PocDecisionMark(
        loop_id="loop-a", card_id=card_id, kind=kind, status=status, built_on=built_on
    )


# --- the limits and the plain-text rules ---------------------------------------------------------


def test_a_decision_and_a_missing_record_that_keep_the_rules_have_no_problems() -> None:
    assert poc_problems("decision", DECISION) == []
    assert poc_problems("missing", MISSING) == []
    check_record("decision", {**DECISION, "builds_on": "The export reads the list."})


def test_each_kind_names_its_own_required_fields() -> None:
    found = poc_problems("decision", {})
    assert [(p.field, p.rule) for p in found] == [
        ("title", "missing"),
        ("chosen", "missing"),
        ("reason", "missing"),
        ("alternative", "missing"),
        ("change_path", "missing"),
    ]
    missing = poc_problems("missing", {})
    assert [p.field for p in missing] == ["title", "chosen", "reason", "change_path", "missing"]
    assert missing[-1].message == "missing: missing. Say what a person has to provide."
    # A missing record may leave the alternative out; a decision may leave out what is missing.
    assert poc_problems("missing", {**MISSING, "alternative": ""}) == []
    assert poc_problems("decision", {**DECISION, "missing": ""}) == []


def test_the_title_and_the_fields_are_held_to_their_lengths_and_sentences() -> None:
    long_title = "x" * (POC_TITLE_MAX_CHARS + 1)
    found = poc_problems("decision", {**DECISION, "title": long_title})
    assert [(p.field, p.rule, p.message) for p in found] == [
        ("title", "chars", f"title: {POC_TITLE_MAX_CHARS + 1} characters, at most 120.")
    ]
    assert poc_problems("decision", {**DECISION, "title": "x" * POC_TITLE_MAX_CHARS}) == []
    sentences = " ".join(["It is so."] * (POC_TEXT_MAX_SENTENCES + 1))
    found = poc_problems("decision", {**DECISION, "reason": sentences})
    assert [(p.field, p.rule) for p in found] == [("reason", "sentences")]
    long_text = "word " * (POC_TEXT_MAX_CHARS // 5 + 1)
    assert [
        (p.field, p.rule) for p in poc_problems("decision", {**DECISION, "builds_on": long_text})
    ] == [("builds_on", "chars")]


def test_text_for_people_holds_no_code_path_id_or_symbol_and_details_may() -> None:
    texts = {
        **DECISION,
        "chosen": "Use `localStorage` for it.",
        "reason": "See app/services/cards.py for why.",
        "alternative": "Keep 0b6f3c1e-7a52-4d8e-9c41-2f5a6b7c8d9e as it is.",
        "change_path": "Rename list_items later.",
        "details": "app/services/cards.py, `localStorage`, list_items and ```code```",
    }
    found = [(p.field, p.rule) for p in poc_problems("decision", texts)]
    assert found == [
        ("chosen", "code_span"),
        ("chosen", "code_symbol"),
        ("reason", "file_path"),
        ("alternative", "id"),
        ("change_path", "code_symbol"),
    ]


def test_details_are_bounded_only_in_length() -> None:
    texts = {**DECISION, "details": "x" * (POC_DETAILS_MAX_CHARS + 1)}
    assert [(p.field, p.rule) for p in poc_problems("decision", texts)] == [("details", "chars")]
    assert poc_problems("decision", {**DECISION, "details": "x" * POC_DETAILS_MAX_CHARS}) == []


def test_a_refusal_is_poc_decision_invalid_naming_each_field_and_rule() -> None:
    with pytest.raises(PocDecisionRefusal) as caught:
        check_record("decision", {**DECISION, "chosen": "", "reason": "Use `x` here."})
    refusal = caught.value
    assert isinstance(refusal, ValidationFailure)
    assert (refusal.status_code, refusal.code) == (422, POC_DECISION_INVALID)
    assert refusal.details == {
        "errors": [
            "chosen: missing. Say what was chosen.",
            "reason: contains code (`x`). Files, symbols and ids belong in details.",
        ],
        "error_count": 2,
        "fields": [
            {"field": "chosen", "rule": "missing"},
            {"field": "reason", "rule": "code_span"},
        ],
    }


# --- the key and the same record again -----------------------------------------------------------


def test_the_key_is_the_loop_key_poc_and_three_digits_and_never_reused() -> None:
    assert format_poc_key("WE012", 7) == "WE012-POC-007"
    assert next_sequence([]) == 1
    assert next_sequence([poc_row(1), poc_row(4), poc_row(2)]) == 5


def test_the_same_open_record_is_found_by_kind_title_and_choice() -> None:
    rows = [
        poc_row(1, title="Store it", chosen="In the browser."),
        poc_row(2, title="Store it", chosen="On the server.", status="ok"),
    ]
    found = duplicate_of(rows, kind="decision", title="  store   IT ", chosen="in the browser.")
    assert found is rows[0]
    assert duplicate_of(rows, kind="missing", title="Store it", chosen="In the browser.") is None
    # An answered record is no retry of an open one.
    assert duplicate_of(rows, kind="decision", title="Store it", chosen="On the server.") is None


# --- the review order, due and the counts --------------------------------------------------------


def test_the_review_order_is_built_on_then_missing_then_open_then_answered() -> None:
    rows = [
        poc_row(1, status="ok"),
        poc_row(2),
        poc_row(3, kind="missing"),
        poc_row(4, builds_on="The export reads it."),
        poc_row(5),
        poc_row(6, kind="missing", builds_on="The login uses it."),
        poc_row(7, status="feedback", builds_on="Something."),
    ]
    assert [row.sequence for row in review_order(rows)] == [4, 6, 3, 2, 5, 1, 7]
    assert review_rank(mark(built_on=True, kind="missing")) == 0
    assert review_rank(mark(status="ok", built_on=True)) == 3


def phase(phase_id: str, number: int, state: str) -> PhaseView:
    return {
        "id": phase_id,
        "number": number,
        "name": f"Phase {number}",
        "objective": "",
        "entry_conditions": [],
        "exit_conditions": [],
        "prerequisite_phase_ids": [],
        "prerequisite_ticket_ids": [],
        "state": state,
        "blocked_by": [],
        "tickets": [],
    }


def readiness(
    items: list[tuple[str, str, int, bool]], phases: list[PhaseView]
) -> Readiness:
    """Planned Tickets as (card id, phase id, phase number, completed)."""
    built: list[ReadinessItem] = []
    for card_id, phase_id, number, done in items:
        item = readiness_item(card_id, phase_number=number)
        item["phase_id"] = phase_id
        item["completed_at"] = "2026-11-26T08:00:00Z" if done else None
        built.append(item)
    return {
        "loop_id": "loop-a",
        "stage": "in_progress",
        "execution_allowed": True,
        "blocked_reason": None,
        "items": built,
        "phases": phases,
    }


def unplanned(card_id: str, *, done: bool, archived: bool = False) -> UnplannedTicket:
    return {
        "id": card_id,
        "key": f"L-1-UNP-{card_id}",
        "title": card_id,
        "completed_at": "2026-11-26T08:00:00Z" if done else None,
        "archived_at": "2026-11-26T08:00:00Z" if archived else None,
        "workplace": "unknown",
        "waiting_for": "nothing",
        "state": None if done else "ready",
    }


def test_the_progress_reads_each_planned_tickets_phase_and_whether_all_are_done() -> None:
    plan = readiness(
        [("c1", "p1", 1, True), ("c2", "p2", 2, False)],
        [phase("p1", 1, "complete"), phase("p2", 2, "in_progress")],
    )
    progress = loop_progress(plan, [unplanned("u1", done=True)])
    assert progress.phases == {"c1": TicketPhase(1, True), "c2": TicketPhase(2, False)}
    assert progress.all_completed is False
    done = readiness([("c1", "p1", 1, True)], [phase("p1", 1, "complete")])
    # An archived Ticket added by hand is left out, as the Loop summary leaves it out.
    assert loop_progress(done, [unplanned("u1", done=False, archived=True)]).all_completed
    assert loop_progress(readiness([], []), []).all_completed is False
    assert loop_progress(readiness([], []), [unplanned("u1", done=True)]).all_completed


def test_an_open_record_is_due_when_all_is_done_or_its_phase_is_and_work_builds_on_it() -> None:
    phases = {"done": TicketPhase(1, True), "busy": TicketPhase(2, False)}
    busy = LoopProgress(all_completed=False, phases=phases)
    finished = LoopProgress(all_completed=True, phases=phases)
    assert is_due(mark(built_on=True, card_id="done"), busy)
    assert not is_due(mark(built_on=False, card_id="done"), busy)
    assert not is_due(mark(built_on=True, card_id="busy"), busy)
    assert not is_due(mark(built_on=True, card_id="unplanned"), busy)
    assert not is_due(mark(built_on=True, card_id=None), busy)
    assert is_due(mark(card_id=None), finished)
    assert not is_due(mark(status="ok"), finished)


def test_the_counts_say_open_built_on_missing_due_and_answered() -> None:
    progress = LoopProgress(all_completed=False, phases={"done": TicketPhase(1, True)})
    marks = [
        mark(built_on=True, card_id="done"),
        mark(kind="missing"),
        mark(kind="missing", built_on=True),
        mark(),
        mark(status="ok"),
        mark(status="feedback", built_on=True, card_id="done"),
    ]
    assert poc_counts(marks, progress) == {
        "open": 4,
        "built_on_open": 2,
        "missing_open": 2,
        "due": 1,
        "answered": 2,
    }
    assert poc_counts([], progress) == {
        "open": 0,
        "built_on_open": 0,
        "missing_open": 0,
        "due": 0,
        "answered": 0,
    }


# --- the Ticket feedback becomes -----------------------------------------------------------------


def test_the_feedback_title_names_the_key_and_is_cut_to_a_ticket_title() -> None:
    assert feedback_title(poc_row(3, title="Store it")) == "Feedback on L-1-POC-003: Store it"
    long = feedback_title(poc_row(3, title="x" * 400))
    assert len(long) == TICKET_TITLE_MAX_CHARS and long.endswith("…")


def test_the_feedback_description_puts_the_feedback_first_and_then_its_basis() -> None:
    row = poc_row(2, builds_on="The export reads it.").__replace__(details="See cards.py.")
    text = feedback_description(row, "Keep it on the server.", ("L-1-UNP-001", "Show the list"))
    assert text == (
        "## Feedback\n\nKeep it on the server.\n\n"
        "## The basis: a POC decision, L-1-POC-002\n\n**A choice**\n\n"
        "- What was chosen: This one.\n- Why: Because.\n- The alternative: That one.\n"
        "- How to change it: Change it later.\n- What builds on it: The export reads it.\n"
        "- Taken on: L-1-UNP-001 Show the list\n"
        "\n### Details\n\nSee cards.py."
    )
    missing = poc_row(4, kind="missing").__replace__(missing="An account.", alternative="")
    text = feedback_description(missing, "Use mine.", None)
    assert "## The basis: something missing, L-1-POC-004" in text
    assert "- What a person has to provide: An account.\n" in text
    assert "The alternative" not in text and "Taken on" not in text and "Details" not in text


def test_long_details_are_cut_so_the_description_fits_a_card() -> None:
    row = poc_row(1).__replace__(details="d" * POC_DETAILS_MAX_CHARS)
    text = feedback_description(row, "f" * 2000, None)
    assert len(text) <= TICKET_DESCRIPTION_MAX_CHARS
    assert text.endswith("(The details are cut here; L-1-POC-001 holds them whole.)")
