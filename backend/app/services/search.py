"""Ticket search, scoped to one Loop, and App-wide search that keeps Loop context.

A search reads the board through the board unit of work, the boards to search through the registry
unit of work, a planned Ticket's readiness through ``PlanViews`` and whether a board has its FTS5
index through ``FullTextIndex``; a board without the index is searched with ``LIKE``. The clock is
passed in (the overdue filter), so every rule here runs in a unit test without a database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import NotRequired, TypedDict

from ..core.dates import iso_utc
from ..core.errors import NotFound, ValidationFailure
from ..db.generated.board import CardsRow, LabelsRow, LoopsRow
from ..repositories.board import BoardUnitOfWork
from ..repositories.cards import CardCounts
from ..repositories.registry import RegistryUnitOfWork
from ..repositories.search import CardSearch, FullTextIndex
from .activity import activity_feed
from .cards import CardRecord, card_record
from .lists import BoardChecks
from .loops import require_loop
from .plan_views import Blocker, PlanViews, ReadinessItem
from .subresources import LabelEntry, label_entries


class SearchHit(CardRecord):
    """A Ticket a search found: its row, labels and counts, its Loop and its readiness."""

    board_id: str
    labels: list[LabelEntry]
    checklist_total: int
    checklist_completed: int
    comment_count: int
    loop_key: str
    loop_name: str
    ready: bool
    human_action_required: bool
    blockers: list[Blocker]
    # The App-wide search adds the board's name.
    board_name: NotRequired[str]


class SearchPage(TypedDict):
    items: list[SearchHit]
    total: int
    limit: int
    offset: int
    has_more: bool
    engine: str
    """``fts5`` when the text was matched by the index, else ``like``."""


class GlobalSearch(TypedDict):
    items: list[SearchHit]
    board_count: int
    loop_count: int
    query: str
    engine: str
    """``fts5`` when every Loop searched was matched by its index, ``like`` when none was,
    ``mixed`` otherwise (see ``search_engine``)."""


def fts_query(value: str) -> str:
    """A safe FTS5 MATCH expression: every token is quoted and prefix-matched."""
    tokens = [token.replace('"', " ") for token in value.split() if token.strip()]
    return " AND ".join(f'"{token}"*' for token in tokens)


def search_engine(engines: Iterable[str]) -> str:
    """One word for the engines several searches used: ``fts5`` when every one was the index,
    ``like`` when none was (or nothing was searched), ``mixed`` otherwise."""
    used = set(engines)
    if used == {"fts5"}:
        return "fts5"
    if used <= {"like"}:
        return "like"
    return "mixed"


def search_hit(
    board_id: str,
    loop: LoopsRow,
    row: CardsRow,
    labels: list[LabelsRow],
    counts: CardCounts,
    item: ReadinessItem | None,
) -> SearchHit:
    """A found Ticket's JSON; ``item`` is its planned Ticket's readiness, if the plan has one."""
    return {
        **card_record(row),
        "board_id": board_id,
        "labels": label_entries(labels),
        "checklist_total": counts.checklist_total,
        "checklist_completed": counts.checklist_completed,
        "comment_count": counts.comment_count,
        "loop_key": loop.key,
        "loop_name": loop.name,
        "ready": bool(item["ready"]) if item is not None else True,
        "human_action_required": (
            bool(item["human_action_required"]) if item is not None else False
        ),
        "blockers": item["blockers"] if item is not None else [],
    }


def _now() -> datetime:
    return datetime.now(UTC)


class SearchService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        accounts: RegistryUnitOfWork,
        *,
        plans: PlanViews,
        index: FullTextIndex,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.boards = boards
        self.store = store
        self.accounts = accounts
        self.plans = plans
        self.index = index
        self._clock = clock

    def board(
        self,
        board_id: str,
        loop_id: str,
        *,
        q: str | None = None,
        priority: str | None = None,
        label: str | None = None,
        completed: bool | None = None,
        overdue: bool = False,
        list_id: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchPage:
        self.boards.require_row(board_id)
        if not self.store.exists(board_id):
            raise NotFound("Board database not found")
        # Blank text is no text filter on either engine, as an empty ``q`` always was: FTS5 refuses
        # the empty MATCH it would become, and LIKE would look for the spaces themselves.
        words = q.strip() if q else ""
        full_text = bool(words) and self.index.fts_available(board_id)
        search = CardSearch(
            loop_id=loop_id,
            match=fts_query(words) if full_text else None,
            contains=words if words and not full_text else None,
            include_archived=include_archived,
            priority=priority or None,
            label=label or None,
            completed=completed,
            overdue_at=iso_utc(self._clock()) if overdue else None,
            list_id=list_id or None,
        )
        with self.store.reader(board_id) as repos:
            loop = require_loop(repos, loop_id)
            total = repos.search.count(search)
            rows = repos.search.page(search, limit=limit, offset=offset)
            ids = [row.id for row in rows]
            labels = repos.cards.labels(ids)
            counts = repos.cards.counts(ids)
            readiness: dict[str, ReadinessItem] = {}
            if loop.current_plan_id:
                for item in self.plans.readiness(repos, loop)["items"]:
                    if item["card_id"]:
                        readiness[item["card_id"]] = item
        return {
            "items": [
                search_hit(
                    board_id, loop, row, labels[row.id], counts[row.id], readiness.get(row.id)
                )
                for row in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
            "engine": "fts5" if full_text else "like",
        }

    def global_search(
        self, *, q: str, limit_per_loop: int = 10, max_boards: int = 25
    ) -> GlobalSearch:
        """Every open Loop of the most recently updated active boards; a board or Loop that is
        gone by the time it is searched is skipped. Blank text is refused, as an empty ``q`` is at
        the route: a Loop's search would read it as no filter and answer every Ticket."""
        if not q.strip():
            raise ValidationFailure("Search text must not be blank")
        with self.accounts.reader() as registry:
            boards = registry.boards.most_recent(status="active", limit=max_boards)
        results: list[SearchHit] = []
        engines: list[str] = []
        loop_count = 0
        for board in boards:
            try:
                with self.store.reader(board.id) as repos:
                    loops = repos.loops.listing(
                        include_archived=False, include_completed=False, stage=None
                    )
            except NotFound:
                continue
            for loop in loops:
                loop_count += 1
                try:
                    found = self.board(
                        board.id, loop.id, q=q, limit=limit_per_loop, include_archived=False
                    )
                except NotFound:
                    continue
                engines.append(found["engine"])
                for item in found["items"]:
                    item["board_name"] = board.name
                    results.append(item)
        return {
            "items": results,
            "board_count": len(boards),
            "loop_count": loop_count,
            "query": q,
            "engine": search_engine(engines),
        }


# The activity route imports the feed from here.
__all__ = ["SearchService", "activity_feed"]
