"""Discussion rounds: reading an agent's position and counting what a round cost."""

from __future__ import annotations

import pytest

from app.services import runtime
from app.services.orchestrator import board_briefing, content_hash, usage_tokens
from tests.unit.fakes.registry import board_row


def test_extract_position_parses_the_trailing_verdict() -> None:
    verdict, justification = runtime.extract_position("Use sessions.\nDISAGREE")
    assert verdict == "disagree"
    assert justification == "Use sessions."
    assert runtime.extract_position("No verdict here")[0] == "abstain"


def test_extract_position_never_reads_a_negation_as_agreement() -> None:
    # Matching the bare word anywhere made "I do not AGREE" a vote for agreement, which is how a
    # discussion reached consensus while its agents disagreed.
    assert runtime.extract_position("I do not AGREE with this proposal.")[0] == "abstain"
    assert runtime.extract_position("Honestly, I can not AGREE here.\nIt leaks.")[0] == "abstain"
    assert runtime.extract_position("Some AGREE, some do not.")[0] == "abstain"


def test_extract_position_prefers_a_structured_verdict() -> None:
    answer = (
        "The plan is sound but the rollback is missing.\n"
        '{"verdict": "disagree", "reasoning": "No rollback path for the migration."}'
    )
    assert runtime.extract_position(answer) == (
        "disagree",
        "No rollback path for the migration.",
    )


def test_extract_position_uses_the_last_labelled_line() -> None:
    answer = (
        "My first reading said AGREE.\n"
        "Then I checked the storage layer.\n"
        "Verdict: DISAGREE\nI still think the shape is right."
    )
    assert runtime.extract_position(answer)[0] == "disagree"


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ("Looks right.\nVerdict: AGREE", "agree"),
        ("Looks right.\n**Final verdict:** disagree", "disagree"),
        ("> Position = Abstain", "abstain"),
        ('{"position": "AGREE", "justification": "Fine."}', "agree"),
        ('{"verdict": "maybe"}', "abstain"),
        ("", "abstain"),
    ],
)
def test_a_verdict_is_read_only_from_an_unambiguous_form(answer: str, verdict: str) -> None:
    assert runtime.extract_position(answer)[0] == verdict
    assert runtime.extract_position(answer) == runtime.extract_position(answer)


@pytest.mark.parametrize(
    ("result", "tokens"),
    [
        ({"usage": {"total_tokens": 42}}, 42),
        ({"usage": {"total_tokens": 41.9}}, 41),
        ({"usage": {"prompt_tokens": 30, "completion_tokens": 12}}, 42),
        ({"usage": {"input_tokens": 30, "output_tokens": 12}}, 42),
        ({"usage": {"prompt_tokens": "30", "completion_tokens": 12}}, 0),
        ({"usage": "not a dict"}, 0),
        ({"usage": None}, 0),
        ({}, 0),
    ],
)
def test_a_round_counts_the_tokens_the_provider_reported(
    result: dict[str, object], tokens: int
) -> None:
    assert usage_tokens(result) == tokens


def test_a_message_hash_ignores_surrounding_whitespace() -> None:
    assert content_hash("  Same answer.\n") == content_hash("Same answer.")
    assert content_hash("Same answer.") != content_hash("Other answer.")
    assert len(content_hash("Same answer.")) == 64


def test_a_thread_on_the_board_is_briefed_with_the_board_and_its_title() -> None:
    board = board_row("b-1", name="Homepage").__replace__(description="Our web site.")
    assert board_briefing(board, "Pick a licence") == (
        "Board: Homepage\nBoard description:\nOur web site.\n"
        "Discussion on the board, not on a Ticket: Pick a licence"
    )


def test_a_board_briefing_cuts_the_description_as_a_tickets_and_survives_no_board() -> None:
    long = board_row("b-1", name="Homepage").__replace__(description="x" * 5000)
    assert "x" * 4000 + "\n" in board_briefing(long, "T")
    assert "x" * 4001 not in board_briefing(long, "T")
    assert board_briefing(None, "T").startswith("Board: (unknown)\nBoard description:\n(empty)\n")
