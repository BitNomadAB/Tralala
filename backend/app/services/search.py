"""Ticket search, scoped to one Loop, and App-wide search that keeps Loop context."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ..core import sql
from ..core.errors import NotFound
from ..repositories.sql.cards import LABEL_JOIN
from ..storage.board_db import BoardDatabaseManager
from ..storage.registry import Registry
from ..storage.sqlite import utcnow
from .activity import activity_feed
from .boards import BoardService
from .common import decorate_cards, rows
from .loop_plans import LoopPlanService

# What the searches format into SQL text (see core/sql.py).
_CARD_FTS_JOIN = " JOIN cards_fts f ON f.rowid = c.rowid"
_CARD_SEARCH_FILTERS: sql.Filters = (
    ("loop", "c.loop_id = :loop_id"),
    ("match", "cards_fts MATCH :match"),
    ("q", "(c.title LIKE :q OR c.description LIKE :q)"),
    ("unarchived", "c.archived_at IS NULL"),
    ("priority", "c.priority = :priority"),
    ("label", "(l.id = :label OR l.name = :label)"),
    ("completed", "c.completed_at IS NOT NULL"),
    ("open", "c.completed_at IS NULL"),
    ("overdue", "c.due_at IS NOT NULL AND c.due_at < :now AND c.completed_at IS NULL"),
    ("list", "c.list_id = :list_id"),
)


def _fts_query(value: str) -> str:
    """Build a safe FTS5 MATCH expression: every token is quoted and prefix-matched."""
    tokens = [token.replace('"', " ") for token in value.split() if token.strip()]
    return " AND ".join(f'"{token}"*' for token in tokens)


class SearchService:
    def __init__(
        self,
        board_service: BoardService,
        plans: LoopPlanService,
        *,
        boards: BoardDatabaseManager,
        registry: Registry,
    ) -> None:
        self.board_service = board_service
        self.plans = plans
        self.boards = boards
        self.registry = registry

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
    ) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")

        filters = ["loop"]
        params: dict[str, Any] = {"loop_id": loop_id}
        joins = ""
        if q:
            if self.boards.fts_available(board_id):
                joins += _CARD_FTS_JOIN
                filters.append("match")
                params["match"] = _fts_query(q)
            else:
                filters.append("q")
                params["q"] = f"%{q}%"
        if not include_archived:
            filters.append("unarchived")
        if priority:
            filters.append("priority")
            params["priority"] = priority
        if label:
            joins += LABEL_JOIN
            filters.append("label")
            params["label"] = label
        if completed is not None:
            filters.append("completed" if completed else "open")
        if overdue:
            filters.append("overdue")
            params["now"] = utcnow()
        if list_id:
            filters.append("list")
            params["list_id"] = list_id
        where = sql.where(_CARD_SEARCH_FILTERS, filters)
        with self.boards.reader(board_id) as conn:
            loop = rows(
                conn,
                "SELECT id, key, name, stage, current_plan_id FROM loops WHERE id = :id",
                {"id": loop_id},
            )
            if not loop:
                raise NotFound("Loop not found", code="loop_not_found")
            total = conn.execute(
                text(
                    "SELECT"  # noqa: S608 - from _CARD_FTS_JOIN, LABEL_JOIN, _CARD_SEARCH_FILTERS
                    f" COUNT(DISTINCT c.id) FROM cards c{joins}{where}"
                ),
                params,
            ).scalar_one()
            records = rows(
                conn,
                "SELECT"  # noqa: S608 - from _CARD_FTS_JOIN, LABEL_JOIN, _CARD_SEARCH_FILTERS
                f" DISTINCT c.* FROM cards c{joins}{where} ORDER BY c.updated_at DESC, c.id"
                " LIMIT :limit OFFSET :offset",
                {**params, "limit": limit, "offset": offset},
            )
            items = decorate_cards(conn, board_id, records)
            loop_row = loop[0]
            readiness: dict[str, dict[str, Any]] = {}
            if loop_row["current_plan_id"]:
                evaluation = self.plans.readiness(conn, loop_row)
                readiness = {
                    item["card_id"]: item for item in evaluation["items"] if item["card_id"]
                }
        for item in items:
            item["board_id"] = board_id
            item["loop_id"] = loop_id
            item["loop_key"] = loop_row["key"]
            item["loop_name"] = loop_row["name"]
            detail = readiness.get(item["id"])
            item["ready"] = bool(detail["ready"]) if detail else True
            item["human_action_required"] = (
                bool(detail["human_action_required"]) if detail else False
            )
            item["blockers"] = detail["blockers"] if detail else []
        return {
            "items": items,
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < int(total),
            "engine": "fts5" if q and self.boards.fts_available(board_id) else "like",
        }

    def global_search(
        self, *, q: str, limit_per_loop: int = 10, max_boards: int = 25
    ) -> dict[str, Any]:
        boards = self.registry.read(
            "SELECT id, name FROM boards WHERE status = 'active' ORDER BY updated_at DESC"
            " LIMIT :limit",
            {"limit": max_boards},
        )
        results: list[dict[str, Any]] = []
        loop_count = 0
        for board in boards:
            try:
                with self.boards.reader(board["id"]) as conn:
                    loops = rows(
                        conn,
                        "SELECT id FROM loops WHERE archived_at IS NULL"
                        " AND completed_at IS NULL ORDER BY sequence",
                    )
            except NotFound:
                continue
            for loop in loops:
                loop_count += 1
                try:
                    found = self.board(
                        board["id"], loop["id"], q=q, limit=limit_per_loop, include_archived=False
                    )
                except NotFound:
                    continue
                for item in found["items"]:
                    item["board_name"] = board["name"]
                    results.append(item)
        return {
            "items": results,
            "board_count": len(boards),
            "loop_count": loop_count,
            "query": q,
        }


# The activity route imports the feed from here.
__all__ = ["SearchService", "activity_feed"]
