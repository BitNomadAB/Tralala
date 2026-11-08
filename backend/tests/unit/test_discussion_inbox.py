"""The Discussions inbox on the in-memory fakes: who a thread waits for, the counts, the verdict,
who decided, the order across boards, and the two additions the Ticket's tab reads (the
``card_id`` filter and ``decided_by_name``)."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager

import pytest

from app.core.context import ActorContext
from app.core.errors import Forbidden, NotFound
from app.db.generated.board import DiscussionOutcomesRow, DiscussionRoundsRow
from app.repositories.board import BoardRepositories
from app.services.discussion_inbox import (
    InboxCounts,
    InboxRow,
    counts_of,
    decided_by,
    ordered,
    read_inbox,
    verdict_of,
    waits_for,
)
from app.services.discussions import DiscussionService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    discussion_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import RegistryState, board_row, registry_unit_of_work
from tests.unit.test_discussion_services import ADA, Ids, Snapshots, participant

NOW = "2026-11-08T10:00:00Z"
READER = ActorContext(
    actor_id="actor-1",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"boards:read", "discussions:read"}),
)


def synthesis(
    verdict: str, *, go: int = 0, stop: int = 0, unclear: int = 0, missing: int = 0
) -> str:
    """A stored round synthesis with that many stances on each side."""

    def stances(count: int) -> list[dict[str, object]]:
        return [{"participant": f"P{index}"} for index in range(count)]

    return json.dumps(
        {
            "version": 1,
            "suggestion": {"verdict": verdict, "reason": "Every participant agrees."},
            "go": stances(go),
            "stop": stances(stop),
            "unclear": stances(unclear),
            "missing": [f"M{index}" for index in range(missing)],
        }
    )


def round_row(
    discussion_id: str, stored: str, *, created_at: str = NOW, round_id: str = ""
) -> DiscussionRoundsRow:
    return DiscussionRoundsRow(
        id=round_id or f"round-{discussion_id}-{created_at}",
        discussion_id=discussion_id,
        run_id="run-1",
        round_number=1,
        status="completed",
        answers=1,
        failures=0,
        repeats=0,
        tokens_used=0,
        elapsed_ms=0,
        created_at=created_at,
        finished_at=created_at,
        synthesis_json=stored,
    )


def outcome_row(
    discussion_id: str, summary: str, payload: dict[str, object], *, created_at: str = NOW
) -> DiscussionOutcomesRow:
    return DiscussionOutcomesRow(
        id=f"outcome-{discussion_id}-{created_at}",
        discussion_id=discussion_id,
        summary=summary,
        payload_json=json.dumps(payload),
        created_at=created_at,
    )


def board_state() -> BoardState:
    """One Loop with two Tickets; the first carries a key."""
    state = BoardState()
    state.loops["loop-a"] = loop_row("loop-a")
    state.lists["list-a"] = list_row("list-a", "loop-a", 1)
    state.cards["card-1"] = card_row("card-1", "list-a", "loop-a").__replace__(
        ticket_key="L-1-001", title="Pick a template"
    )
    state.cards["card-2"] = card_row("card-2", "list-a", "loop-a")
    return state


def thread(
    state: BoardState,
    discussion_id: str,
    *,
    status: str = "consensus_proposed",
    run_state: str = "idle",
    at: str = NOW,
    card_id: str = "card-1",
) -> None:
    state.discussions[discussion_id] = discussion_row(
        discussion_id, card_id=card_id, status=status, run_state=run_state
    ).__replace__(goal=f"Question {discussion_id}?", last_activity_at=at, round_count=1)


class Boards:
    """A board unit of work per board id, as the manager opens one database per board."""

    def __init__(self, stores: dict[str, FakeBoardUnitOfWork]) -> None:
        self.stores = stores

    def exists(self, board_id: str) -> bool:
        return board_id in self.stores

    def _store(self, board_id: str) -> FakeBoardUnitOfWork:
        store = self.stores.get(board_id)
        if store is None:
            raise NotFound("Board database not found")
        return store

    @contextmanager
    def reader(self, board_id: str) -> Generator[BoardRepositories]:
        with self._store(board_id).reader(board_id) as repos:
            yield repos

    @contextmanager
    def writer(self, board_id: str) -> Generator[BoardRepositories]:
        with self._store(board_id).writer(board_id) as repos:
            yield repos


# --- the rules ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "run_state", "expected"),
    [
        ("consensus_proposed", "idle", "your_decision"),
        ("human_review", "idle", "your_decision"),
        ("discussing", "idle", "your_decision"),
        ("open", "idle", "your_decision"),
        ("discussing", "running", "agents"),
        ("consensus_proposed", "paused", "agents"),
        ("approved", "idle", "nobody"),
        ("vetoed", "idle", "nobody"),
        ("rework_requested", "idle", "nobody"),
        # A reply after rework starts a round: the agents talk again.
        ("rework_requested", "running", "agents"),
    ],
)
def test_who_a_thread_waits_for(status: str, run_state: str, expected: str) -> None:
    assert waits_for(status, run_state) == expected


def test_the_verdict_and_counts_come_from_the_newest_synthesis() -> None:
    stored = json.loads(synthesis("yes_with_conditions", go=2, stop=1, unclear=1, missing=1))
    assert verdict_of(stored) == "yes_with_conditions"
    expected: InboxCounts = {"go": 2, "stop": 1, "unclear": 1, "missing": 1}
    assert counts_of(stored, 5) == expected


def test_before_a_round_there_is_no_verdict_and_everyone_is_missing() -> None:
    assert verdict_of(None) is None
    assert counts_of(None, 3) == {"go": 0, "stop": 0, "unclear": 0, "missing": 3}
    assert verdict_of({"suggestion": "yes"}) is None
    assert verdict_of({"suggestion": {"verdict": 1}}) is None
    assert counts_of({"go": "two"}, 2) == {"go": 0, "stop": 0, "unclear": 0, "missing": 0}


def test_who_decided_reads_the_name_from_the_payload_or_cuts_it_from_the_summary() -> None:
    assert decided_by(None) is None
    named = outcome_row("t", "approve by Ada", {"decision": "approve", "actor_name": "Ada L."})
    assert decided_by(named) == "Ada L."
    # Before the payload carried the name: the summary is cut by the decision and the reason.
    plain = outcome_row("t", "approve by Ada", {"decision": "approve", "reason": ""})
    assert decided_by(plain) == "Ada"
    reasoned = outcome_row(
        "t", "veto by Grace Hopper: no: not now", {"decision": "veto", "reason": "no: not now"}
    )
    assert decided_by(reasoned) == "Grace Hopper"
    foreign = outcome_row("t", "approved", {"decision": "approve", "reason": ""})
    assert decided_by(foreign) is None
    broken = outcome_row("t", "approve by Ada", {}).__replace__(payload_json="not json")
    assert decided_by(broken) is None


def row(discussion_id: str, waits: str, at: str) -> InboxRow:
    return {
        "discussion_id": discussion_id,
        "board_id": BOARD_ID,
        "board_name": "Board",
        "loop_id": None,
        "loop_key": None,
        "loop_name": None,
        "card_id": None,
        "ticket_key": None,
        "card_title": None,
        "question": "?",
        "status": "open",
        "run_state": "idle",
        "verdict": None,
        "counts": {"go": 0, "stop": 0, "unclear": 0, "missing": 0},
        "participant_count": 0,
        "round_count": 0,
        "max_rounds": 3,
        "asked_by_name": "Ada",
        "last_activity_at": at,
        "decided_by_name": None,
        "waits_for": waits,
    }


def test_rows_go_decision_first_then_talking_then_decided_each_newest_first() -> None:
    rows = [
        row("done-old", "nobody", "2026-11-01"),
        row("talk", "agents", "2026-11-02"),
        row("wait-old", "your_decision", "2026-11-03"),
        row("done-new", "nobody", "2026-11-09"),
        row("wait-new", "your_decision", "2026-11-04"),
    ]
    page = ordered(rows)
    assert [entry["discussion_id"] for entry in page["items"]] == [
        "wait-new",
        "wait-old",
        "talk",
        "done-new",
        "done-old",
    ]
    assert page["total"] == 5
    capped = ordered(rows, limit=2)
    assert [entry["discussion_id"] for entry in capped["items"]] == ["wait-new", "wait-old"]
    assert capped["total"] == 5


# --- across boards, through the repositories ------------------------------------------------------


def test_the_inbox_reads_every_board_it_can_open_and_leaves_out_cancelled_threads() -> None:
    first = board_state()
    thread(first, "wait", at="2026-11-08T09:00:00Z")
    first.rounds.append(round_row("wait", synthesis("no", stop=1), created_at="2026-11-07"))
    first.rounds.append(
        round_row("wait", synthesis("yes", go=2, missing=1), created_at="2026-11-08")
    )
    first.participants += [
        participant("alpha").__replace__(discussion_id="wait"),
        participant("beta").__replace__(id="p-beta", discussion_id="wait"),
    ]
    thread(first, "gone", status="cancelled", at="2026-11-09T00:00:00Z")
    thread(first, "done", status="vetoed", card_id="card-2", at="2026-11-09T00:00:00Z")
    first.outcomes.append(
        outcome_row("done", "veto by Grace", {"decision": "veto", "actor_name": "Grace"})
    )
    second = board_state()
    thread(second, "talk", status="discussing", run_state="running", at="2026-11-01T00:00:00Z")
    registry = RegistryState()
    registry.boards[BOARD_ID] = board_row(BOARD_ID, name="Homepage")
    registry.boards["b-2"] = board_row("b-2", name="Memorial")
    registry.boards["b-3"] = board_row("b-3", name="Repairing")
    boards = Boards(
        {
            BOARD_ID: FakeBoardUnitOfWork(first),
            "b-2": FakeBoardUnitOfWork(second, databases=("b-2",)),
            "b-3": FakeBoardUnitOfWork(BoardState(), databases=("b-3",), unavailable=("b-3",)),
        }
    )
    page = read_inbox(registry_unit_of_work(registry), boards)
    assert [(r["discussion_id"], r["waits_for"]) for r in page["items"]] == [
        ("wait", "your_decision"),
        ("talk", "agents"),
        ("done", "nobody"),
    ]
    assert page["total"] == 3
    wait = page["items"][0]
    assert (wait["board_id"], wait["board_name"]) == (BOARD_ID, "Homepage")
    assert (wait["loop_id"], wait["loop_key"], wait["loop_name"]) == (
        "loop-a",
        "L-1",
        "Loop loop-a",
    )
    assert (wait["card_id"], wait["ticket_key"], wait["card_title"]) == (
        "card-1",
        "L-1-001",
        "Pick a template",
    )
    assert (wait["question"], wait["status"], wait["run_state"]) == (
        "Question wait?",
        "consensus_proposed",
        "idle",
    )
    assert (wait["verdict"], wait["counts"]) == (
        "yes",
        {"go": 2, "stop": 0, "unclear": 0, "missing": 1},
    )
    assert (wait["participant_count"], wait["round_count"], wait["max_rounds"]) == (2, 1, 3)
    assert (wait["asked_by_name"], wait["decided_by_name"]) == ("Ada", None)
    done = page["items"][2]
    assert (done["decided_by_name"], done["verdict"], done["board_name"]) == (
        "Grace",
        None,
        "Homepage",
    )
    assert page["items"][1]["board_name"] == "Memorial"


def test_a_thread_whose_ticket_has_gone_reads_without_ticket_or_loop() -> None:
    state = board_state()
    thread(state, "orphan")
    del state.cards["card-1"]
    registry = RegistryState()
    registry.boards[BOARD_ID] = board_row(BOARD_ID, name="Board")
    page = read_inbox(registry_unit_of_work(registry), FakeBoardUnitOfWork(state))
    (orphan,) = page["items"]
    assert (orphan["loop_id"], orphan["ticket_key"], orphan["card_title"]) == (None, None, None)
    assert orphan["card_id"] == "card-1"


def service(state: BoardState) -> DiscussionService:
    registry = RegistryState()
    registry.boards[BOARD_ID] = board_row(BOARD_ID, name="Board")
    return DiscussionService(
        FakeBoardChecks(),
        Snapshots(),
        FakeBoardUnitOfWork(state),
        registry_unit_of_work(registry),
        clock=lambda: NOW,
        new_id=Ids(),
    )


def test_the_inbox_names_boards_so_it_needs_both_read_scopes() -> None:
    state = board_state()
    thread(state, "wait")
    discussions = service(state)
    assert [r["discussion_id"] for r in discussions.inbox(READER)["items"]] == ["wait"]
    no_boards = ActorContext(
        actor_id="k", actor_type="agent", actor_name="Key", scopes=frozenset({"discussions:read"})
    )
    with pytest.raises(Forbidden):
        discussions.inbox(no_boards)


# --- what the Ticket's Discussions tab reads ------------------------------------------------------


def test_the_board_list_narrows_to_one_ticket() -> None:
    state = board_state()
    thread(state, "first", card_id="card-1", at="2026-11-01T00:00:00Z")
    thread(state, "second", card_id="card-2", at="2026-11-02T00:00:00Z")
    thread(state, "third", card_id="card-1", at="2026-11-03T00:00:00Z")
    discussions = service(state)
    assert [e["id"] for e in discussions.list(BOARD_ID, card_id="card-1")] == ["third", "first"]
    assert [e["id"] for e in discussions.list(BOARD_ID)] == ["third", "second", "first"]
    assert discussions.list(BOARD_ID, card_id="card-1", status="vetoed") == []


def test_a_decision_carries_the_deciders_name_on_the_thread() -> None:
    state = board_state()
    thread(state, "wait")
    discussions = service(state)
    assert discussions.get(BOARD_ID, "wait")["decided_by_name"] is None
    decided = discussions.review(ADA, BOARD_ID, "wait", decision="veto", reason="Too early.")
    assert decided["decided_by_name"] == "Ada"
    assert json.loads(state.outcomes[-1].payload_json)["actor_name"] == "Ada"
    assert discussions.list(BOARD_ID, card_id="card-1")[0]["decided_by_name"] == "Ada"
