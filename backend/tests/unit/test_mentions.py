"""Mentions: which agents a comment or a discussion message asks to answer."""

from __future__ import annotations

import pytest

from app.services.discussions import requests_agent_reply
from app.services.mentions import extract_mentions

MENTION_AGENTS = [
    {"id": "a1", "name": "Review Bot"},
    {"id": "a2", "name": "Review"},
    {"id": "a3", "name": "Local Code Helper"},
]


def test_mention_parser_resolves_names_without_swallowing_words() -> None:
    found = extract_mentions(
        "@[Local Code Helper] and @Review, not reviewer@Review.example or @Reviewer",
        MENTION_AGENTS,
    )
    assert [agent["name"] for agent in found] == ["Local Code Helper", "Review"]
    assert extract_mentions("@Review and @[Review]", MENTION_AGENTS) == MENTION_AGENTS[1:2]


@pytest.mark.parametrize(
    ("content", "names"),
    [
        ("@Review Bot please look", ["Review Bot"]),
        ("@review bot, case does not matter", ["Review Bot"]),
        ("@Review, then @Review Bot", ["Review", "Review Bot"]),
        ("@[Review Bot] @[Review Bot] once is enough", ["Review Bot"]),
        ("@[Nobody] is not an agent", []),
        ("mail me at someone@Review.example", []),
        ("@Reviewer is a longer word, not an agent", []),
        ("no mention at all", []),
        ("", []),
    ],
)
def test_mentions_are_found_in_order_without_duplicates(content: str, names: list[str]) -> None:
    found = extract_mentions(content, MENTION_AGENTS)
    assert [agent["name"] for agent in found] == names
    assert extract_mentions(content, MENTION_AGENTS) == found


PARTICIPANTS = [
    {"participant_id": "a1", "display_name": "Review Bot"},
    {"participant_id": "a2", "display_name": "Architect"},
]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("@agents what do you think?", True),
        ("@Agent, your view?", True),
        ("Over to @Architect", True),
        ("A plain note for the humans", False),
        ("mail@agents.example is an address", False),
        ("@agentsmith is someone else", False),
    ],
)
def test_a_message_asks_for_an_agent_reply_only_when_it_says_so(
    content: str, expected: bool
) -> None:
    assert requests_agent_reply(content, PARTICIPANTS) is expected
