"""``LoopPlanRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import LOOP_PLANS_COLUMNS, LoopPlansRow
from ..loop_plans import PlanTotals

_PLANS = sql.column_list(LOOP_PLANS_COLUMNS)
_ACTIVE = text(
    f"SELECT {_PLANS} FROM loop_plans"  # noqa: S608 - from LOOP_PLANS_COLUMNS
    " WHERE loop_id = :id AND status = 'active'"
)
_ALL_ACTIVE = text(
    f"SELECT {_PLANS} FROM loop_plans"  # noqa: S608 - from LOOP_PLANS_COLUMNS
    " WHERE status = 'active' AND loop_id IN (SELECT id FROM loops)"
)
_PHASE_COUNTS = text(
    "SELECT loop_id, COUNT(*) AS total FROM loop_phases WHERE loop_id = :id GROUP BY loop_id"
)
_ALL_PHASE_COUNTS = text(
    "SELECT loop_id, COUNT(*) AS total FROM loop_phases"
    " WHERE loop_id IN (SELECT id FROM loops) GROUP BY loop_id"
)
_TICKET_TOTALS = text(
    "SELECT i.loop_id AS loop_id, COUNT(*) AS total,"
    " COALESCE(SUM(CASE WHEN c.completed_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS completed"
    " FROM loop_plan_items i LEFT JOIN cards c ON c.plan_item_id = i.id"
    " WHERE i.loop_id = :id GROUP BY i.loop_id"
)
_ALL_TICKET_TOTALS = text(
    "SELECT i.loop_id AS loop_id, COUNT(*) AS total,"
    " COALESCE(SUM(CASE WHEN c.completed_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS completed"
    " FROM loop_plan_items i LEFT JOIN cards c ON c.plan_item_id = i.id"
    " WHERE i.loop_id IN (SELECT id FROM loops) GROUP BY i.loop_id"
)


class SqlLoopPlanRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def active(self, loop_id: str) -> LoopPlansRow | None:
        row = self._connection.execute(_ACTIVE, {"id": loop_id}).mappings().first()
        return None if row is None else LoopPlansRow.from_mapping(row)

    def active_by_loop(self) -> dict[str, LoopPlansRow]:
        result = self._connection.execute(_ALL_ACTIVE).mappings()
        plans = [LoopPlansRow.from_mapping(row) for row in result]
        return {plan.loop_id: plan for plan in plans}

    def phase_counts(self, loop_id: str | None) -> dict[str, int]:
        if loop_id is None:
            result = self._connection.execute(_ALL_PHASE_COUNTS)
        else:
            result = self._connection.execute(_PHASE_COUNTS, {"id": loop_id})
        return {
            values.text(row, "loop_id"): values.integer(row, "total") for row in result.mappings()
        }

    def ticket_totals(self, loop_id: str | None) -> dict[str, PlanTotals]:
        if loop_id is None:
            result = self._connection.execute(_ALL_TICKET_TOTALS)
        else:
            result = self._connection.execute(_TICKET_TOTALS, {"id": loop_id})
        return {
            values.text(row, "loop_id"): PlanTotals(
                total=values.integer(row, "total"), completed=values.integer(row, "completed")
            )
            for row in result.mappings()
        }
