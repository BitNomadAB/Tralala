"""The Discussions inbox: across every board, what waits for the person, what the agents are
talking about and what was decided.

The boards are read through the repositories, one statement per board; the grouping, the counts,
the verdict and who decided are pure functions of the rows, so a unit test gives them a thread and
reads the answer.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import TypedDict, TypeIs

from pydantic import JsonValue

from ..core.errors import NotFound, ServiceUnavailable
from ..db.generated.board import DiscussionOutcomesRow
from ..db.generated.registry import BoardsRow
from ..repositories.board import BoardUnitOfWork
from ..repositories.discussions import InboxThread
from ..repositories.registry import RegistryUnitOfWork
from .discussion_synthesis import read_synthesis

# The order the inbox shows its groups in: a decision first, then what runs, then what is done.
WAITS_FOR = ("your_decision", "agents", "nobody")
DECIDED = frozenset({"approved", "vetoed", "rework_requested"})
TALKING = frozenset({"running", "paused"})
INBOX_LIMIT = 200
# What one board may contribute before the rows are grouped; a guard, not a page size.
BOARD_LIMIT = 1000


class InboxCounts(TypedDict):
    """How the newest round's answers stand: for going ahead, against, cannot tell, missing."""

    go: int
    stop: int
    unclear: int
    missing: int


class InboxRow(TypedDict):
    discussion_id: str
    board_id: str
    board_name: str
    loop_id: str | None
    loop_key: str | None
    loop_name: str | None
    card_id: str | None
    ticket_key: str | None
    card_title: str | None
    question: str
    status: str
    run_state: str
    verdict: str | None
    counts: InboxCounts
    participant_count: int
    round_count: int
    max_rounds: int
    asked_by_name: str
    last_activity_at: str
    decided_by_name: str | None
    waits_for: str


class InboxPage(TypedDict):
    items: list[InboxRow]
    total: int


def waits_for(status: str, run_state: str) -> str:
    """Who the thread waits for: ``agents`` while a run is running or paused, ``nobody`` once a
    person approved, vetoed or asked for rework, otherwise ``your_decision``. A thread with no
    round yet waits for the person too: nobody else will move it."""
    if run_state in TALKING:
        return "agents"
    if status in DECIDED:
        return "nobody"
    return "your_decision"


def _is_object(value: JsonValue) -> TypeIs[dict[str, JsonValue]]:
    return isinstance(value, dict)


def verdict_of(synthesis: Mapping[str, JsonValue] | None) -> str | None:
    """The newest round's suggested verdict, or ``None`` before a round."""
    if synthesis is None:
        return None
    suggestion = synthesis.get("suggestion")
    if suggestion is None or not _is_object(suggestion):
        return None
    verdict = suggestion.get("verdict")
    return verdict if isinstance(verdict, str) else None


def counts_of(synthesis: Mapping[str, JsonValue] | None, participant_count: int) -> InboxCounts:
    """Who stands where after the newest round; before a round every participant is missing."""
    if synthesis is None:
        return {"go": 0, "stop": 0, "unclear": 0, "missing": participant_count}

    def size(key: str) -> int:
        value = synthesis.get(key)
        return len(value) if isinstance(value, list) else 0

    return {
        "go": size("go"),
        "stop": size("stop"),
        "unclear": size("unclear"),
        "missing": size("missing"),
    }


def decided_by(outcome: DiscussionOutcomesRow | None) -> str | None:
    """The name of the person who recorded the outcome.

    A review writes ``actor_name`` into the payload. An outcome written before that has only the
    summary ``"{decision} by {name}"`` with ``": {reason}"`` after it when a reason was given; the
    payload holds the decision and the reason, so the name is cut out exactly, never guessed.
    """
    if outcome is None:
        return None
    try:
        payload: JsonValue = json.loads(outcome.payload_json or "{}")
    except ValueError:
        return None
    if not _is_object(payload):
        return None
    name = payload.get("actor_name")
    if isinstance(name, str) and name.strip():
        return name
    decision, reason = payload.get("decision"), payload.get("reason")
    if not isinstance(decision, str):
        return None
    prefix = f"{decision} by "
    suffix = f": {reason}" if isinstance(reason, str) and reason else ""
    summary = outcome.summary
    if not summary.startswith(prefix) or not summary.endswith(suffix):
        return None
    cut = summary[len(prefix) : len(summary) - len(suffix)]
    return cut.strip() or None


def inbox_row(board: BoardsRow, entry: InboxThread) -> InboxRow:
    """One thread as an inbox row. The Ticket and its Loop count only together, as the thread's
    own view reads them."""
    thread = entry.thread
    card, loop = entry.card, entry.loop
    joined = card is not None and loop is not None
    stored = entry.latest_round
    synthesis = None if stored is None else read_synthesis(stored.synthesis_json)
    run_state = thread.run_state or "idle"
    return {
        "discussion_id": thread.id,
        "board_id": board.id,
        "board_name": board.name,
        "loop_id": loop.id if joined and loop else None,
        "loop_key": loop.key if joined and loop else None,
        "loop_name": loop.name if joined and loop else None,
        "card_id": thread.card_id,
        "ticket_key": card.ticket_key if joined and card else None,
        "card_title": card.title if joined and card else None,
        "question": thread.goal,
        "status": thread.status,
        "run_state": run_state,
        "verdict": verdict_of(synthesis),
        "counts": counts_of(synthesis, entry.participant_count),
        "participant_count": entry.participant_count,
        "round_count": thread.round_count,
        "max_rounds": thread.max_rounds,
        "asked_by_name": thread.created_by_name,
        "last_activity_at": thread.last_activity_at,
        "decided_by_name": decided_by(entry.outcome),
        "waits_for": waits_for(thread.status, run_state),
    }


def ordered(rows: Iterable[InboxRow], *, limit: int = INBOX_LIMIT) -> InboxPage:
    """The rows by group (``WAITS_FOR``), each group newest activity first; at most ``limit``
    rows, with ``total`` counting all of them."""
    items = sorted(rows, key=lambda row: row["discussion_id"])
    items.sort(key=lambda row: row["last_activity_at"], reverse=True)
    items.sort(key=lambda row: WAITS_FOR.index(row["waits_for"]))
    return {"items": items[:limit], "total": len(items)}


def read_inbox(registry: RegistryUnitOfWork, store: BoardUnitOfWork) -> InboxPage:
    """Every thread that is not cancelled, on every board, as the inbox orders them. A board
    whose database cannot be read now (missing, or its schema under repair) is left out."""
    with registry.reader() as repos:
        boards = repos.boards.all()
    rows: list[InboxRow] = []
    for board in boards:
        try:
            with store.reader(board.id) as repos:
                threads = repos.threads.inbox(limit=BOARD_LIMIT)
        except (NotFound, ServiceUnavailable):
            continue
        rows.extend(inbox_row(board, entry) for entry in threads)
    return ordered(rows)
