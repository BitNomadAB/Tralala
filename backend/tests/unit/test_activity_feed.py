"""The activity feed on an in-memory board: filters, order, paging and the stored changes.

The feed runs its real code; the board check and the board unit of work are the typed fakes in
``tests/unit/fakes``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.core.context import ActorContext
from app.core.errors import NotFound
from app.db.generated.board import ActivityLogRow
from app.repositories.board import BoardUnitOfWork
from app.services.activity import ActivityBoards, activity_entry, activity_feed
from app.services.boards import BoardService
from tests.unit.fakes.board import BOARD_ID, BoardState, FakeBoardChecks, FakeBoardUnitOfWork


def board_service_is_what_the_feed_needs(service: BoardService) -> ActivityBoards:
    """Never called: pyright proves that the BoardService wired in Services fits the feed."""
    return service


@dataclass(slots=True)
class Source:
    """The board check and the board's database, as BoardService hands them to the feed."""

    boards: BoardUnitOfWork
    checks: FakeBoardChecks = field(default_factory=FakeBoardChecks)

    def require_row(self, board_id: str) -> object:
        return self.checks.require_row(board_id)


def entry(
    entry_id: str,
    timestamp: str,
    *,
    action: str = "card.updated",
    entity_type: str = "card",
    entity_id: str = "card-1",
    actor_type: str = "user",
    changes_json: str = "{}",
) -> ActivityLogRow:
    return ActivityLogRow(
        id=entry_id,
        actor_id="actor-1",
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=None,
        timestamp=timestamp,
        changes_json=changes_json,
    )


@pytest.fixture
def source() -> Source:
    state = BoardState()
    state.activity = [
        entry("b", "2026-11-01T10:00:00Z", changes_json='{"title": {"after": "x"}}'),
        entry("a", "2026-11-01T10:00:00Z", action="card.moved", changes_json="[1, 2]"),
        entry("c", "2026-11-01T11:00:00Z", entity_type="list", entity_id="list-1"),
        entry("d", "2026-11-01T09:00:00Z", actor_type="agent", changes_json="not json"),
    ]
    return Source(FakeBoardUnitOfWork(state))


def test_the_feed_is_newest_first_with_its_changes_parsed(source: Source) -> None:
    items, total = activity_feed(BOARD_ID, source)
    assert total == 4
    assert [item["id"] for item in items] == ["c", "a", "b", "d"]
    assert list(items[0]) == [
        "id",
        "actor_id",
        "actor_type",
        "action",
        "entity_type",
        "entity_id",
        "request_id",
        "timestamp",
        "changes",
    ]
    changes = {item["id"]: item["changes"] for item in items}
    # Any JSON is returned as stored; text that is not JSON reads as no changes.
    assert changes == {"c": {}, "a": [1, 2], "b": {"title": {"after": "x"}}, "d": {}}
    assert source.checks.calls == [("require_row", BOARD_ID)]


@pytest.mark.parametrize(
    ("filters", "ids"),
    [
        ({"entity_type": "list"}, ["c"]),
        ({"entity_type": "card", "entity_id": "card-1"}, ["a", "b", "d"]),
        ({"actor_type": "agent"}, ["d"]),
        ({"action": "card.moved"}, ["a"]),
        ({"action": "card.moved", "actor_type": "agent"}, []),
        ({"entity_type": "", "action": ""}, ["c", "a", "b", "d"]),
    ],
)
def test_each_filter_must_match_exactly_and_an_empty_one_is_no_filter(
    source: Source, filters: dict[str, str], ids: list[str]
) -> None:
    items, total = activity_feed(
        BOARD_ID,
        source,
        entity_type=filters.get("entity_type"),
        entity_id=filters.get("entity_id"),
        actor_type=filters.get("actor_type"),
        action=filters.get("action"),
    )
    assert ([item["id"] for item in items], total) == (ids, len(ids))


def test_a_page_is_a_window_and_the_total_counts_every_match(source: Source) -> None:
    items, total = activity_feed(BOARD_ID, source, limit=2, offset=1)
    assert ([item["id"] for item in items], total) == (["a", "b"], 4)
    items, total = activity_feed(BOARD_ID, source, limit=2, offset=10)
    assert (items, total) == ([], 4)


def test_an_unknown_board_is_refused_before_its_database_is_read(source: Source) -> None:
    source.checks = FakeBoardChecks(unregistered=frozenset({BOARD_ID}))
    with pytest.raises(NotFound, match="Board not found"):
        activity_feed(BOARD_ID, source)


def test_an_entry_records_the_actor_the_request_and_the_changes() -> None:
    actor = ActorContext(actor_id="a-1", actor_type="agent", actor_name="Robot", request_id="r-9")
    row = activity_entry(
        actor,
        action="board.updated",
        entity_type="board",
        entity_id=BOARD_ID,
        changes=None,
        entry_id="e-1",
        timestamp="2026-11-03T10:00:00Z",
    )
    assert row == ActivityLogRow(
        id="e-1",
        actor_id="a-1",
        actor_type="agent",
        action="board.updated",
        entity_type="board",
        entity_id=BOARD_ID,
        request_id="r-9",
        timestamp="2026-11-03T10:00:00Z",
        changes_json="{}",
    )
    without_request = ActorContext(actor_id="a-1", actor_type="user", actor_name="Ada")
    changed = activity_entry(
        without_request,
        action="board.updated",
        entity_type="board",
        entity_id=BOARD_ID,
        changes={"before": {"name": "A"}},
        entry_id="e-2",
        timestamp="2026-11-03T10:00:00Z",
    )
    assert (changed.request_id, changed.changes_json) == (None, '{"before": {"name": "A"}}')
