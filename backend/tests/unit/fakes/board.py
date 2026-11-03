"""One board database in memory: the board repositories and their unit of work."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.core.errors import Conflict, NotFound, ServiceUnavailable
from app.db.generated.board import ActivityLogRow, CardsRow, LabelsRow, ListsRow, LoopsRow
from app.repositories.activity import ActivityRepository
from app.repositories.board import BoardUnitOfWork
from app.repositories.counters import BoardCounts, CounterRepository
from app.repositories.labels import LabelRepository
from app.repositories.lists import ListRepository
from app.repositories.loops import LoopRepository

BOARD_ID = "0b6f3c1e-7a52-4d8e-9c41-2f5a6b7c8d9e"
CREATED = "2026-11-01T09:00:00Z"


@dataclass(slots=True)
class BoardState:
    """The rows of one board database, as a test sets them up and the services change them."""

    lists: dict[str, ListsRow] = field(default_factory=dict[str, ListsRow])
    loops: dict[str, LoopsRow] = field(default_factory=dict[str, LoopsRow])
    cards: dict[str, CardsRow] = field(default_factory=dict[str, CardsRow])
    activity: list[ActivityLogRow] = field(default_factory=list[ActivityLogRow])
    labels: dict[str, LabelsRow] = field(default_factory=dict[str, LabelsRow])

    def snapshot(self) -> BoardState:
        return BoardState(
            dict(self.lists),
            dict(self.loops),
            dict(self.cards),
            list(self.activity),
            dict(self.labels),
        )

    def restore(self, snapshot: BoardState) -> None:
        self.lists = snapshot.lists
        self.loops = snapshot.loops
        self.cards = snapshot.cards
        self.activity = snapshot.activity
        self.labels = snapshot.labels


# --- rows for a test to start from ---------------------------------------------------------------


def loop_row(
    loop_id: str,
    *,
    stage: str = "implementation",
    completed_at: str | None = None,
    archived_at: str | None = None,
    cancelled_at: str | None = None,
) -> LoopsRow:
    return LoopsRow(
        id=loop_id,
        name=f"Loop {loop_id}",
        goal="",
        sequence=1,
        key_prefix="L",
        key="L-1",
        stage=stage,
        version=1,
        current_plan_id=None,
        analysis_approval_id=None,
        roadmap_approval_id=None,
        implementation_approval_id=None,
        qa_approval_id=None,
        active_qa_cycle_id=None,
        history_id=None,
        created_by_actor_id="actor-0",
        created_by_actor_type="user",
        created_by_name="Grace",
        created_at=CREATED,
        updated_at=CREATED,
        archived_at=archived_at,
        cancelled_at=cancelled_at,
        completed_at=completed_at,
    )


def list_row(
    list_id: str, loop_id: str, position: int, *, name: str = "", archived_at: str | None = None
) -> ListsRow:
    return ListsRow(
        id=list_id,
        name=name or f"List {list_id}",
        position=position,
        created_at=CREATED,
        updated_at=CREATED,
        archived_at=archived_at,
        loop_id=loop_id,
    )


def card_row(
    card_id: str,
    list_id: str,
    loop_id: str,
    *,
    archived_at: str | None = None,
    plan_item_id: str | None = None,
) -> CardsRow:
    return CardsRow(
        id=card_id,
        list_id=list_id,
        title=f"Card {card_id}",
        description="",
        position=1024,
        priority="medium",
        due_at=None,
        completed_at=None,
        created_at=CREATED,
        updated_at=CREATED,
        archived_at=archived_at,
        version=1,
        assignee_actor_id=None,
        assignee_type=None,
        assignee_name=None,
        assigned_at=None,
        assigned_by_actor_id=None,
        loop_id=loop_id,
        phase_id=None,
        plan_item_id=plan_item_id,
        ticket_key=None,
        kind="task",
        required_actor="any",
        execution_mode="manual",
        human_action_reason="",
        human_instructions="",
        human_confirmed_at=None,
        human_confirmed_by_actor_id=None,
        plan_revision_id=None,
    )


# --- repositories --------------------------------------------------------------------------------


def _display_order(row: ListsRow) -> tuple[int, str]:
    return row.position, row.id


class FakeListRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, list_id: str) -> ListsRow | None:
        return self._state.lists.get(list_id)

    def for_loop(self, loop_id: str, *, include_archived: bool) -> list[ListsRow]:
        rows = [
            row
            for row in self._state.lists.values()
            if row.loop_id == loop_id and (include_archived or row.archived_at is None)
        ]
        return sorted(rows, key=_display_order)

    def active_names(self, loop_id: str) -> list[str]:
        rows = [
            row
            for row in self._state.lists.values()
            if row.loop_id == loop_id and row.archived_at is None
        ]
        return [row.name for row in sorted(rows, key=lambda row: (row.position, row.created_at))]

    def positions(self, loop_id: str, *, exclude: str | None = None) -> list[tuple[str, int]]:
        return [
            (row.id, row.position)
            for row in self.for_loop(loop_id, include_archived=False)
            if row.id != exclude
        ]

    def add(self, row: ListsRow) -> None:
        if row.id in self._state.lists:
            raise Conflict(f"lists.id {row.id} exists")  # the primary key
        self._state.lists[row.id] = row

    def _change(self, row: ListsRow) -> None:
        self._state.lists[row.id] = row

    def rename(self, list_id: str, name: str, *, now: str) -> None:
        self._change(self._state.lists[list_id].__replace__(name=name, updated_at=now))

    def move(self, list_id: str, position: int, *, now: str) -> None:
        self._change(self._state.lists[list_id].__replace__(position=position, updated_at=now))

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for list_id, position in positions:
            self._change(self._state.lists[list_id].__replace__(position=position))

    def archive(self, list_id: str, *, now: str) -> None:
        self._change(self._state.lists[list_id].__replace__(archived_at=now, updated_at=now))

    def restore(self, list_id: str, position: int, *, now: str) -> None:
        row = self._state.lists[list_id]
        self._change(row.__replace__(archived_at=None, position=position, updated_at=now))

    def delete(self, list_id: str) -> None:
        del self._state.lists[list_id]

    def active_card_counts(self, loop_id: str) -> dict[str, int]:
        return dict(
            Counter(
                card.list_id
                for card in self._state.cards.values()
                if card.loop_id == loop_id and card.archived_at is None
            )
        )

    def active_card_count(self, list_id: str) -> int:
        return sum(
            1
            for card in self._state.cards.values()
            if card.list_id == list_id and card.archived_at is None
        )

    def planned_card_count(self, list_id: str) -> int:
        return sum(
            1
            for card in self._state.cards.values()
            if card.list_id == list_id and card.plan_item_id is not None
        )


class FakeLoopRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, loop_id: str) -> LoopsRow | None:
        return self._state.loops.get(loop_id)


class FakeActivityRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def add(self, entry: ActivityLogRow) -> None:
        self._state.activity.append(entry)


class FakeLabelRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def all(self) -> list[LabelsRow]:
        return sorted(self._state.labels.values(), key=lambda row: row.name)


class FakeCounterRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def counts(self) -> BoardCounts:
        return BoardCounts(
            loops=sum(
                1
                for loop in self._state.loops.values()
                if loop.archived_at is None and loop.completed_at is None
            ),
            lists=sum(1 for row in self._state.lists.values() if row.archived_at is None),
            cards=sum(1 for card in self._state.cards.values() if card.archived_at is None),
        )


class FakeBoardRepositories:
    def __init__(self, state: BoardState) -> None:
        # Typed as the Protocols: pyright proves each fake implements its repository here.
        self.lists: ListRepository = FakeListRepository(state)
        self.loops: LoopRepository = FakeLoopRepository(state)
        self.activity: ActivityRepository = FakeActivityRepository(state)
        self.labels: LabelRepository = FakeLabelRepository(state)
        self.counters: CounterRepository = FakeCounterRepository(state)


class FakeBoardUnitOfWork:
    """Commits a writer that ends normally, rolls back one that raises; a reader never commits."""

    def __init__(
        self,
        state: BoardState,
        *,
        databases: Collection[str] = (BOARD_ID,),
        unavailable: Collection[str] = (),
    ) -> None:
        self.state = state
        self.databases = set(databases)
        # Boards whose schema is being repaired: opening one answers 503, as the manager does.
        self.unavailable = set(unavailable)
        self.commits = 0
        self.rollbacks = 0

    def exists(self, board_id: str) -> bool:
        return board_id in self.databases

    def _open(self, board_id: str) -> BoardState:
        if board_id not in self.databases:
            raise NotFound("Board database not found")
        if board_id in self.unavailable:
            raise ServiceUnavailable(
                "Board schema is not at the current revision", code="board_schema_outdated"
            )
        return self.state.snapshot()

    @contextmanager
    def reader(self, board_id: str) -> Generator[FakeBoardRepositories]:
        snapshot = self._open(board_id)
        try:
            yield FakeBoardRepositories(self.state)
        finally:
            self.state.restore(snapshot)

    @contextmanager
    def writer(self, board_id: str) -> Generator[FakeBoardRepositories]:
        snapshot = self._open(board_id)
        try:
            yield FakeBoardRepositories(self.state)
        except BaseException:
            self.state.restore(snapshot)
            self.rollbacks += 1
            raise
        self.commits += 1


def board_unit_of_work(state: BoardState) -> BoardUnitOfWork:
    """The fake as the Protocol a service takes; pyright proves the contract."""
    return FakeBoardUnitOfWork(state)


@dataclass(slots=True)
class FakeBoardChecks:
    """The registry side of a board as BoardService answers it: registered, and taking writes."""

    unregistered: frozenset[str] = frozenset()
    archived: frozenset[str] = frozenset()
    calls: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def require_row(self, board_id: str) -> object:
        self.calls.append(("require_row", board_id))
        if board_id in self.unregistered:
            raise NotFound("Board not found")
        return board_id

    def ensure_active(self, board_id: str) -> object:
        self.calls.append(("ensure_active", board_id))
        if board_id in self.unregistered:
            raise NotFound("Board not found")
        if board_id in self.archived:
            raise Conflict("Board is archived", code="board_archived")
        return board_id
