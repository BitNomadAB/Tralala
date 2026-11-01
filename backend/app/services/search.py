"""Ticket search, scoped to one Loop, and App-wide search that keeps Loop context."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from ..core.errors import NotFound
from ..storage.sqlite import utcnow
from .boards import BoardService
from .cards import CardService
from .common import decorate_cards, rows


def _fts_query(value: str) -> str:
    """Build a safe FTS5 MATCH expression: every token is quoted and prefix-matched."""
    tokens = [token.replace('"', " ") for token in value.split() if token.strip()]
    return " AND ".join(f'"{token}"*' for token in tokens)


class SearchService:
    def __init__(self, board_service: BoardService, card_service: CardService) -> None:
        self.board_service = board_service
        self.card_service = card_service
        self.boards = board_service.boards

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

        clauses: list[str] = ["c.loop_id = :loop_id"]
        params: dict[str, Any] = {"loop_id": loop_id}
        join = ""
        if q:
            if self.boards.fts_available(board_id):
                join += " JOIN cards_fts f ON f.rowid = c.rowid"
                clauses.append("cards_fts MATCH :match")
                params["match"] = _fts_query(q)
            else:
                clauses.append("(c.title LIKE :q OR c.description LIKE :q)")
                params["q"] = f"%{q}%"
        if not include_archived:
            clauses.append("c.archived_at IS NULL")
        if priority:
            clauses.append("c.priority = :priority")
            params["priority"] = priority
        if label:
            join += " JOIN card_labels cl ON cl.card_id = c.id JOIN labels l ON l.id = cl.label_id"
            clauses.append("(l.id = :label OR l.name = :label)")
            params["label"] = label
        if completed is not None:
            clauses.append("c.completed_at IS NOT NULL" if completed else "c.completed_at IS NULL")
        if overdue:
            clauses.append("c.due_at IS NOT NULL AND c.due_at < :now AND c.completed_at IS NULL")
            params["now"] = utcnow()
        if list_id:
            clauses.append("c.list_id = :list_id")
            params["list_id"] = list_id
        where = f" WHERE {' AND '.join(clauses)}"
        base = f"FROM cards c{join}{where}"
        with self.boards.reader(board_id) as conn:
            loop = rows(
                conn,
                "SELECT id, key, name, stage, current_plan_id FROM loops WHERE id = :id",
                {"id": loop_id},
            )
            if not loop:
                raise NotFound("Loop not found", code="loop_not_found")
            total = conn.execute(text(f"SELECT COUNT(DISTINCT c.id) {base}"), params).scalar_one()
            records = rows(
                conn,
                f"SELECT DISTINCT c.* {base} ORDER BY c.updated_at DESC, c.id"
                f" LIMIT :limit OFFSET :offset",
                {**params, "limit": limit, "offset": offset},
            )
            items = decorate_cards(conn, board_id, records)
            loop_row = loop[0]
            readiness: dict[str, dict[str, Any]] = {}
            if loop_row["current_plan_id"]:
                evaluation = self.card_service.plans.readiness(conn, loop_row)  # type: ignore[union-attr]
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
        boards = [
            row
            for row in self.board_service.registry.read(
                "SELECT id, name FROM boards WHERE status = 'active' ORDER BY updated_at DESC"
                " LIMIT :limit",
                {"limit": max_boards},
            )
        ]
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


def activity_feed(
    board_id: str,
    board_service: BoardService,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    board_service.require_row(board_id)
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if entity_type:
        clauses.append("entity_type = :entity_type")
        params["entity_type"] = entity_type
    if entity_id:
        clauses.append("entity_id = :entity_id")
        params["entity_id"] = entity_id
    if actor_type:
        clauses.append("actor_type = :actor_type")
        params["actor_type"] = actor_type
    if action:
        clauses.append("action = :action")
        params["action"] = action
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with board_service.boards.reader(board_id) as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM activity_log{where}"), params).scalar_one()
        records = rows(
            conn,
            f"SELECT * FROM activity_log{where}"
            " ORDER BY timestamp DESC, id LIMIT :limit OFFSET :offset",
            {**params, "limit": limit, "offset": offset},
        )
    items = []
    for record in records:
        entry = dict(record)
        raw = entry.pop("changes_json", "{}")
        try:
            entry["changes"] = json.loads(raw)
        except (TypeError, ValueError):
            entry["changes"] = {}
        items.append(entry)
    return items, int(total)
