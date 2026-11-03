"""Loop-owned Kanban columns.

Columns belong to exactly one Loop. Ordering, counts, reorder normalization and archive queries
are all scoped to that Loop, so two Loops in one Board never share or reorder each other's lists.

The service reaches the board database only through the repository Protocols and the board unit of
work (``app/repositories``), and the registry only through ``BoardChecks``; the clock and the id
source are passed in, so every rule here runs in a unit test without a database.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, TypedDict
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..db.generated.board import ListsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..schemas.lists import ListCreate, ListMove, ListUpdate
from .activity import activity_entry
from .ordering import place


class BoardChecks(Protocol):
    """What ListService needs from BoardService: the board is registered, and it takes writes."""

    def require_row(self, board_id: str) -> object: ...

    def ensure_active(self, board_id: str) -> object: ...


class ListEntry(TypedDict):
    """A list as the API returns it: the row's columns, its board and its unarchived cards."""

    id: str
    name: str
    position: int
    created_at: str
    updated_at: str
    archived_at: str | None
    loop_id: str
    board_id: str
    card_count: int


type ListEntries = list[ListEntry]


def _new_id() -> str:
    return str(uuid4())


class ListService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self._clock = clock
        self._new_id = new_id

    # --- reads -----------------------------------------------------------------------------------

    @staticmethod
    def serialize(board_id: str, row: ListsRow, card_count: int = 0) -> ListEntry:
        return {
            "id": row.id,
            "name": row.name,
            "position": row.position,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "archived_at": row.archived_at,
            "loop_id": row.loop_id,
            "board_id": board_id,
            "card_count": card_count,
        }

    def list(self, board_id: str, loop_id: str, *, include_archived: bool = False) -> ListEntries:
        self.boards.require_row(board_id)
        if not self.store.exists(board_id):
            raise NotFound("Board database not found")
        with self.store.reader(board_id) as repos:
            self._loop(repos, loop_id)
            lists = repos.lists.for_loop(loop_id, include_archived=include_archived)
            counts = repos.lists.active_card_counts(loop_id)
        return [self.serialize(board_id, row, counts.get(row.id, 0)) for row in lists]

    def get(self, board_id: str, loop_id: str, list_id: str) -> ListEntry:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            self._loop(repos, loop_id)
            row = self._list(repos, loop_id, list_id)
            count = repos.lists.active_card_count(list_id)
        return self.serialize(board_id, row, count)

    # --- writes ----------------------------------------------------------------------------------

    def create(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: ListCreate
    ) -> ListEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        list_id = self._new_id()
        now = self._clock()
        with self.store.writer(board_id) as repos:
            self._require_writable(self._loop(repos, loop_id))
            position = self._position(repos, loop_id, payload.position)
            repos.lists.add(
                ListsRow(
                    id=list_id,
                    name=payload.name,
                    position=position,
                    created_at=now,
                    updated_at=now,
                    archived_at=None,
                    loop_id=loop_id,
                )
            )
            self._log(
                repos,
                actor,
                "list.created",
                list_id,
                {"name": payload.name, "loop_id": loop_id},
            )
            row = self._list(repos, loop_id, list_id)
        return self.serialize(board_id, row)

    def update(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        list_id: str,
        payload: ListUpdate,
    ) -> ListEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            self._require_writable(self._loop(repos, loop_id))
            existing = self._list(repos, loop_id, list_id)
            if payload.name is None:
                return self.serialize(board_id, existing)
            repos.lists.rename(list_id, payload.name, now=self._clock())
            self._log(
                repos,
                actor,
                "list.renamed",
                list_id,
                {"before": existing.name, "after": payload.name},
            )
            row = self._list(repos, loop_id, list_id)
        return self.serialize(board_id, row)

    def move(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        list_id: str,
        payload: ListMove,
    ) -> ListEntries:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        now = self._clock()
        with self.store.writer(board_id) as repos:
            self._require_writable(self._loop(repos, loop_id))
            self._list(repos, loop_id, list_id)
            position = self._position(repos, loop_id, payload.position, exclude=list_id)
            repos.lists.move(list_id, position, now=now)
            self._log(repos, actor, "list.moved", list_id, {"position": payload.position})
        return self.list(board_id, loop_id)

    def archive(
        self, actor: ActorContext, board_id: str, loop_id: str, list_id: str
    ) -> ListEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            self._require_writable(self._loop(repos, loop_id))
            existing = self._list(repos, loop_id, list_id)
            if existing.archived_at is None:
                repos.lists.archive(list_id, now=self._clock())
            self._log(repos, actor, "list.archived", list_id)
            row = self._list(repos, loop_id, list_id)
        return self.serialize(board_id, row)

    def restore(
        self, actor: ActorContext, board_id: str, loop_id: str, list_id: str
    ) -> ListEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        now = self._clock()
        with self.store.writer(board_id) as repos:
            self._require_writable(self._loop(repos, loop_id))
            existing = self._list(repos, loop_id, list_id)
            if existing.archived_at is not None:
                position = self._position(repos, loop_id, None)
                repos.lists.restore(list_id, position, now=now)
            self._log(repos, actor, "list.restored", list_id)
            row = self._list(repos, loop_id, list_id)
        return self.serialize(board_id, row)

    def delete(self, actor: ActorContext, board_id: str, loop_id: str, list_id: str) -> None:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            self._require_writable(self._loop(repos, loop_id))
            existing = self._list(repos, loop_id, list_id)
            if existing.archived_at is None:
                raise Conflict("Archive the list before deleting it")
            active_cards = repos.lists.active_card_count(list_id)
            if active_cards:
                raise ValidationFailure(
                    "Archive or move the cards in this list before deleting it",
                    details={"active_cards": active_cards},
                )
            planned = repos.lists.planned_card_count(list_id)
            if planned:
                raise Conflict(
                    "This column still holds planned Tickets; keep them traceable",
                    code="plan_change_required",
                    details={"planned_cards": planned},
                )
            repos.lists.delete(list_id)
            self._log(repos, actor, "list.deleted", list_id, {"name": existing.name})

    # --- rules -----------------------------------------------------------------------------------

    @staticmethod
    def _loop(repos: BoardRepositories, loop_id: str) -> LoopsRow:
        loop = repos.loops.get(loop_id)
        if loop is None:
            raise NotFound("Loop not found", code="loop_not_found")
        return loop

    @staticmethod
    def _list(repos: BoardRepositories, loop_id: str, list_id: str) -> ListsRow:
        row = repos.lists.get(list_id)
        if row is None:
            raise NotFound("List not found")
        if row.loop_id != loop_id:
            raise Conflict(
                "The list belongs to another Loop",
                code="loop_mismatch",
                details={"loop_id": loop_id, "list_loop_id": row.loop_id},
            )
        return row

    @staticmethod
    def _position(
        repos: BoardRepositories, loop_id: str, index: int | None, *, exclude: str | None = None
    ) -> int:
        placement = place(repos.lists.positions(loop_id, exclude=exclude), index)
        if placement.renumbered:
            repos.lists.renumber(placement.renumbered)
        return placement.position

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        list_id: str,
        changes: Mapping[str, object] | None = None,
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="list",
                entity_id=list_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=self._clock(),
            )
        )

    @staticmethod
    def _require_writable(loop: LoopsRow) -> None:
        if loop.completed_at is not None or loop.stage == "completed":
            raise Conflict(
                "This Loop is completed and read-only",
                code="loop_read_only",
                details={"loop_id": loop.id},
            )
        if loop.archived_at is not None or loop.cancelled_at is not None:
            raise Conflict(
                "This Loop is not editable",
                code="loop_read_only",
                details={"loop_id": loop.id},
            )
