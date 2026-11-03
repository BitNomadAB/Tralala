"""``LoopRepository`` over SQLAlchemy."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import LOOPS_COLUMNS, LoopsRow
from ..loops import LOOP_APPROVAL_COLUMNS, LOOP_EDITABLE, ApprovalColumn, LoopChanges

# What the Loop list formats into its SQL text (see core/sql.py).
_LOOP_FILTERS: sql.Filters = (
    ("unarchived", "archived_at IS NULL"),
    ("open", "completed_at IS NULL"),
    ("stage", "stage = :stage"),
)

_COLUMNS = sql.column_list(LOOPS_COLUMNS)
_GET = text(f"SELECT {_COLUMNS} FROM loops WHERE id = :id")  # noqa: S608 - from LOOPS_COLUMNS
_NEXT_SEQUENCE = text("SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM loops")
_ADD = text(
    "INSERT INTO loops (id, name, goal, sequence, key_prefix, key, stage, version,"
    " current_plan_id, analysis_approval_id, roadmap_approval_id, implementation_approval_id,"
    " qa_approval_id, active_qa_cycle_id, history_id, created_by_actor_id, created_by_actor_type,"
    " created_by_name, created_at, updated_at, archived_at, cancelled_at, completed_at)"
    " VALUES (:id, :name, :goal, :sequence, :key_prefix, :key, :stage, :version,"
    " :current_plan_id, :analysis_approval_id, :roadmap_approval_id, :implementation_approval_id,"
    " :qa_approval_id, :active_qa_cycle_id, :history_id, :created_by_actor_id,"
    " :created_by_actor_type, :created_by_name, :created_at, :updated_at, :archived_at,"
    " :cancelled_at, :completed_at)"
)
_CANCEL = text(
    "UPDATE loops SET stage = 'cancelled', cancelled_at = :now, version = version + 1,"
    " updated_at = :now WHERE id = :id"
)
_ARCHIVE = text(
    "UPDATE loops SET archived_at = :now, version = version + 1, updated_at = :now WHERE id = :id"
)
_SET_STAGE = text("UPDATE loops SET stage = :stage, updated_at = :now WHERE id = :id")
_BUMP_VERSION = text("UPDATE loops SET version = version + 1, updated_at = :now WHERE id = :id")
_SET_CURRENT_PLAN = text(
    "UPDATE loops SET current_plan_id = :plan_id, updated_at = :now WHERE id = :id"
)
_CLEAR_DELIVERY_APPROVALS = text(
    "UPDATE loops SET implementation_approval_id = NULL, qa_approval_id = NULL,"
    " updated_at = :now WHERE id = :id"
)


class SqlLoopRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, loop_id: str) -> LoopsRow | None:
        row = self._connection.execute(_GET, {"id": loop_id}).mappings().first()
        return None if row is None else LoopsRow.from_mapping(row)

    def listing(
        self, *, include_archived: bool, include_completed: bool, stage: str | None
    ) -> list[LoopsRow]:
        filters: list[str] = []
        parameters: dict[str, str] = {}
        if not include_archived:
            filters.append("unarchived")
        if not include_completed:
            filters.append("open")
        if stage:
            filters.append("stage")
            parameters["stage"] = stage
        where = sql.where(_LOOP_FILTERS, filters)
        statement = text(
            f"SELECT {_COLUMNS} FROM loops{where}"  # noqa: S608 - from LOOPS_COLUMNS, _LOOP_FILTERS
            " ORDER BY CASE WHEN completed_at IS NULL THEN 0 ELSE 1 END, sequence, id"
        )
        result = self._connection.execute(statement, parameters).mappings()
        return [LoopsRow.from_mapping(row) for row in result]

    def next_sequence(self) -> int:
        row = self._connection.execute(_NEXT_SEQUENCE).mappings().one()
        return values.integer(row, "next")

    def add(self, row: LoopsRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "name": row.name,
                "goal": row.goal,
                "sequence": row.sequence,
                "key_prefix": row.key_prefix,
                "key": row.key,
                "stage": row.stage,
                "version": row.version,
                "current_plan_id": row.current_plan_id,
                "analysis_approval_id": row.analysis_approval_id,
                "roadmap_approval_id": row.roadmap_approval_id,
                "implementation_approval_id": row.implementation_approval_id,
                "qa_approval_id": row.qa_approval_id,
                "active_qa_cycle_id": row.active_qa_cycle_id,
                "history_id": row.history_id,
                "created_by_actor_id": row.created_by_actor_id,
                "created_by_actor_type": row.created_by_actor_type,
                "created_by_name": row.created_by_name,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "archived_at": row.archived_at,
                "cancelled_at": row.cancelled_at,
                "completed_at": row.completed_at,
            },
        )

    def update(self, loop_id: str, changes: LoopChanges) -> None:
        columns = sql.assignments(changes, LOOP_EDITABLE)
        statement = text(f"UPDATE loops SET {columns} WHERE id = :id")  # noqa: S608 - from LOOP_EDITABLE
        self._connection.execute(statement, {**changes, "id": loop_id})

    def cancel(self, loop_id: str, *, now: str) -> None:
        self._connection.execute(_CANCEL, {"now": now, "id": loop_id})

    def archive(self, loop_id: str, *, now: str) -> None:
        self._connection.execute(_ARCHIVE, {"now": now, "id": loop_id})

    def set_stage(self, loop_id: str, stage: str, *, now: str) -> None:
        self._connection.execute(_SET_STAGE, {"stage": stage, "now": now, "id": loop_id})

    def set_current_plan(self, loop_id: str, plan_id: str, *, now: str) -> None:
        self._connection.execute(_SET_CURRENT_PLAN, {"plan_id": plan_id, "now": now, "id": loop_id})

    def clear_delivery_approvals(self, loop_id: str, *, now: str) -> None:
        self._connection.execute(_CLEAR_DELIVERY_APPROVALS, {"now": now, "id": loop_id})

    def clear_approvals(
        self, loop_id: str, columns: Sequence[ApprovalColumn], *, now: str
    ) -> None:
        cleared = sql.assignments(columns, LOOP_APPROVAL_COLUMNS)
        statement = text(
            f"UPDATE loops SET {cleared}, updated_at = :now WHERE id = :id"  # noqa: S608 - from LOOP_APPROVAL_COLUMNS
        )
        self._connection.execute(statement, {**dict.fromkeys(columns), "now": now, "id": loop_id})

    def set_approval(
        self, loop_id: str, column: ApprovalColumn, approval_id: str, *, now: str
    ) -> None:
        name = sql.identifier(column, LOOP_APPROVAL_COLUMNS)
        statement = text(
            f"UPDATE loops SET {name} = :approval_id, version = version + 1,"  # noqa: S608 - from LOOP_APPROVAL_COLUMNS
            " updated_at = :now WHERE id = :id"
        )
        self._connection.execute(
            statement, {"approval_id": approval_id, "now": now, "id": loop_id}
        )

    def bump_version(self, loop_id: str, *, now: str) -> None:
        self._connection.execute(_BUMP_VERSION, {"now": now, "id": loop_id})
