"""``LoopPlanRepository``, ``LoopPhaseRepository``, ``LoopPlanItemRepository`` and
``LoopDependencyRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import (
    LOOP_DEPENDENCIES_COLUMNS,
    LOOP_PHASES_COLUMNS,
    LOOP_PLAN_ITEMS_COLUMNS,
    LOOP_PLANS_COLUMNS,
    LoopDependenciesRow,
    LoopPhasesRow,
    LoopPlanItemsRow,
    LoopPlansRow,
)
from ..loop_plans import PlannedItem, PlanTotals

# --- plans ---------------------------------------------------------------------------------------

_PLANS = sql.column_list(LOOP_PLANS_COLUMNS)
_GET = text(f"SELECT {_PLANS} FROM loop_plans WHERE id = :id")  # noqa: S608 - from LOOP_PLANS_COLUMNS
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
_NEXT_REVISION = text(
    "SELECT COALESCE(MAX(revision_number), 0) + 1 AS next FROM loop_plans WHERE loop_id = :id"
)
_ADD = text(
    "INSERT INTO loop_plans (id, loop_id, revision_number, roadmap_ai_revision_id,"
    " roadmap_revision_id, approval_id, payload_json, content_hash, status, created_at,"
    " activated_at, superseded_at) VALUES (:id, :loop_id, :revision_number,"
    " :roadmap_ai_revision_id, :roadmap_revision_id, :approval_id, :payload_json, :content_hash,"
    " :status, :created_at, :activated_at, :superseded_at)"
)
_ATTACH_REVISIONS = text(
    "UPDATE loop_plans SET roadmap_ai_revision_id = :ai, roadmap_revision_id = :human"
    " WHERE id = :id"
)
_SUPERSEDE_ACTIVE = text(
    "UPDATE loop_plans SET status = 'superseded', superseded_at = :now"
    " WHERE loop_id = :loop_id AND status = 'active' AND id != :plan_id"
)
_ACTIVATE = text(
    "UPDATE loop_plans SET status = 'active', approval_id = :approval_id,"
    " activated_at = COALESCE(activated_at, :now) WHERE id = :id"
)

# --- Phases --------------------------------------------------------------------------------------

_PHASE = f"SELECT {sql.column_list(LOOP_PHASES_COLUMNS)} FROM loop_phases"  # noqa: S608 - from LOOP_PHASES_COLUMNS
_GET_PHASE = text(f"{_PHASE} WHERE loop_id = :loop_id AND id = :id")
_PHASES_FOR_LOOP = text(f"{_PHASE} WHERE loop_id = :id ORDER BY number")
_ADD_PHASE = text(
    "INSERT INTO loop_phases (id, loop_id, plan_id, number, name, objective,"
    " entry_conditions_json, exit_conditions_json, is_qa_phase, created_at)"
    " VALUES (:id, :loop_id, :plan_id, :number, :name, :objective, :entry_conditions_json,"
    " :exit_conditions_json, :is_qa_phase, :created_at)"
)
_UPDATE_PHASE = text(
    "UPDATE loop_phases SET plan_id = :plan_id, number = :number, name = :name,"
    " objective = :objective, entry_conditions_json = :entry_conditions_json,"
    " exit_conditions_json = :exit_conditions_json WHERE id = :id"
)

# --- plan items ----------------------------------------------------------------------------------

_ITEM = f"SELECT {sql.column_list(LOOP_PLAN_ITEMS_COLUMNS)} FROM loop_plan_items"  # noqa: S608 - from LOOP_PLAN_ITEMS_COLUMNS
_GET_ITEM = text(f"{_ITEM} WHERE loop_id = :loop_id AND id = :id")
_NEXT_ITEM_SEQUENCE = text(
    "SELECT COALESCE(MAX(ticket_sequence), 0) + 1 AS next FROM loop_plan_items"
    " WHERE loop_id = :loop_id AND phase_number = :number"
)
_ADD_ITEM = text(
    "INSERT INTO loop_plan_items (id, loop_id, plan_id, phase_id, phase_number, key,"
    " ticket_sequence, title, objective, instructions, required_actor, execution_mode, priority,"
    " acceptance_criteria_json, expected_evidence_json, human_action_reason, human_instructions,"
    " created_at) VALUES (:id, :loop_id, :plan_id, :phase_id, :phase_number, :key,"
    " :ticket_sequence, :title, :objective, :instructions, :required_actor, :execution_mode,"
    " :priority, :acceptance_criteria_json, :expected_evidence_json, :human_action_reason,"
    " :human_instructions, :created_at)"
)
_UPDATE_ITEM = text(
    "UPDATE loop_plan_items SET plan_id = :plan_id, phase_id = :phase_id,"
    " phase_number = :phase_number, title = :title, objective = :objective,"
    " instructions = :instructions, required_actor = :required_actor,"
    " execution_mode = :execution_mode, priority = :priority,"
    " acceptance_criteria_json = :acceptance_criteria_json,"
    " expected_evidence_json = :expected_evidence_json,"
    " human_action_reason = :human_action_reason, human_instructions = :human_instructions"
    " WHERE id = :id"
)
_ITEMS_WITH_CARDS = text(
    f"SELECT {sql.column_list(LOOP_PLAN_ITEMS_COLUMNS, 'i')},"  # noqa: S608 - from LOOP_PLAN_ITEMS_COLUMNS
    " c.id AS card_id, c.completed_at AS card_completed_at FROM loop_plan_items i"
    " LEFT JOIN cards c ON c.plan_item_id = i.id"
    " WHERE i.loop_id = :id ORDER BY i.phase_number, i.ticket_sequence, i.key"
)

# --- dependencies --------------------------------------------------------------------------------

_DEPENDENCIES = text(
    f"SELECT {sql.column_list(LOOP_DEPENDENCIES_COLUMNS)} FROM loop_dependencies"  # noqa: S608 - from LOOP_DEPENDENCIES_COLUMNS
    " WHERE loop_id = :id ORDER BY rowid"
)
_CLEAR_DEPENDENCIES = text("DELETE FROM loop_dependencies WHERE loop_id = :id")
_ADD_DEPENDENCY = text(
    "INSERT OR IGNORE INTO loop_dependencies (id, loop_id, plan_id, source_type, source_id,"
    " target_type, target_id, created_at) VALUES (:id, :loop_id, :plan_id, :source_type,"
    " :source_id, :target_type, :target_id, :created_at)"
)


class SqlLoopPlanRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, plan_id: str) -> LoopPlansRow | None:
        row = self._connection.execute(_GET, {"id": plan_id}).mappings().first()
        return None if row is None else LoopPlansRow.from_mapping(row)

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

    def next_revision(self, loop_id: str) -> int:
        row = self._connection.execute(_NEXT_REVISION, {"id": loop_id}).mappings().one()
        return values.integer(row, "next")

    def add(self, row: LoopPlansRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "loop_id": row.loop_id,
                "revision_number": row.revision_number,
                "roadmap_ai_revision_id": row.roadmap_ai_revision_id,
                "roadmap_revision_id": row.roadmap_revision_id,
                "approval_id": row.approval_id,
                "payload_json": row.payload_json,
                "content_hash": row.content_hash,
                "status": row.status,
                "created_at": row.created_at,
                "activated_at": row.activated_at,
                "superseded_at": row.superseded_at,
            },
        )

    def attach_revisions(
        self, plan_id: str, *, roadmap_ai_revision_id: str, roadmap_revision_id: str
    ) -> None:
        self._connection.execute(
            _ATTACH_REVISIONS,
            {"ai": roadmap_ai_revision_id, "human": roadmap_revision_id, "id": plan_id},
        )

    def activate(self, loop_id: str, plan_id: str, *, approval_id: str | None, now: str) -> None:
        self._connection.execute(
            _SUPERSEDE_ACTIVE, {"now": now, "loop_id": loop_id, "plan_id": plan_id}
        )
        self._connection.execute(
            _ACTIVATE, {"approval_id": approval_id, "now": now, "id": plan_id}
        )


def _phase_values(row: LoopPhasesRow) -> dict[str, str | int]:
    return {
        "id": row.id,
        "loop_id": row.loop_id,
        "plan_id": row.plan_id,
        "number": row.number,
        "name": row.name,
        "objective": row.objective,
        "entry_conditions_json": row.entry_conditions_json,
        "exit_conditions_json": row.exit_conditions_json,
        "is_qa_phase": row.is_qa_phase,
        "created_at": row.created_at,
    }


class SqlLoopPhaseRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, loop_id: str, phase_id: str) -> LoopPhasesRow | None:
        parameters = {"loop_id": loop_id, "id": phase_id}
        row = self._connection.execute(_GET_PHASE, parameters).mappings().first()
        return None if row is None else LoopPhasesRow.from_mapping(row)

    def for_loop(self, loop_id: str) -> list[LoopPhasesRow]:
        result = self._connection.execute(_PHASES_FOR_LOOP, {"id": loop_id})
        return [LoopPhasesRow.from_mapping(row) for row in result.mappings()]

    def add(self, row: LoopPhasesRow) -> None:
        self._connection.execute(_ADD_PHASE, _phase_values(row))

    def update(self, row: LoopPhasesRow) -> None:
        self._connection.execute(_UPDATE_PHASE, _phase_values(row))


def _item_values(row: LoopPlanItemsRow) -> dict[str, str | int]:
    return {
        "id": row.id,
        "loop_id": row.loop_id,
        "plan_id": row.plan_id,
        "phase_id": row.phase_id,
        "phase_number": row.phase_number,
        "key": row.key,
        "ticket_sequence": row.ticket_sequence,
        "title": row.title,
        "objective": row.objective,
        "instructions": row.instructions,
        "required_actor": row.required_actor,
        "execution_mode": row.execution_mode,
        "priority": row.priority,
        "acceptance_criteria_json": row.acceptance_criteria_json,
        "expected_evidence_json": row.expected_evidence_json,
        "human_action_reason": row.human_action_reason,
        "human_instructions": row.human_instructions,
        "created_at": row.created_at,
    }


class SqlLoopPlanItemRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, loop_id: str, item_id: str) -> LoopPlanItemsRow | None:
        parameters = {"loop_id": loop_id, "id": item_id}
        row = self._connection.execute(_GET_ITEM, parameters).mappings().first()
        return None if row is None else LoopPlanItemsRow.from_mapping(row)

    def next_sequence(self, loop_id: str, phase_number: int) -> int:
        parameters = {"loop_id": loop_id, "number": phase_number}
        row = self._connection.execute(_NEXT_ITEM_SEQUENCE, parameters).mappings().one()
        return values.integer(row, "next")

    def add(self, row: LoopPlanItemsRow) -> None:
        self._connection.execute(_ADD_ITEM, _item_values(row))

    def update(self, row: LoopPlanItemsRow) -> None:
        self._connection.execute(_UPDATE_ITEM, _item_values(row))

    def with_cards(self, loop_id: str) -> list[PlannedItem]:
        result = self._connection.execute(_ITEMS_WITH_CARDS, {"id": loop_id})
        return [
            PlannedItem(
                item=LoopPlanItemsRow.from_mapping(row),
                card_id=values.text_or_none(row, "card_id"),
                completed_at=values.text_or_none(row, "card_completed_at"),
            )
            for row in result.mappings()
        ]


class SqlLoopDependencyRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_loop(self, loop_id: str) -> list[LoopDependenciesRow]:
        result = self._connection.execute(_DEPENDENCIES, {"id": loop_id})
        return [LoopDependenciesRow.from_mapping(row) for row in result.mappings()]

    def clear(self, loop_id: str) -> None:
        self._connection.execute(_CLEAR_DEPENDENCIES, {"id": loop_id})

    def add(self, row: LoopDependenciesRow) -> None:
        self._connection.execute(
            _ADD_DEPENDENCY,
            {
                "id": row.id,
                "loop_id": row.loop_id,
                "plan_id": row.plan_id,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "created_at": row.created_at,
            },
        )
