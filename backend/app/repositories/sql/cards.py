"""``CardRepository`` over SQLAlchemy."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import CARDS_COLUMNS, CardsRow, LabelsRow, LoopPlanItemsRow
from ..cards import (
    CARD_EDITABLE,
    CARD_SORTS,
    BoardTicket,
    CardChanges,
    CardCounts,
    CardQuery,
    CardSort,
    TicketProgress,
)

# The join a label filter needs, shared by the card list and the card search.
LABEL_JOIN = " JOIN card_labels cl ON cl.card_id = c.id JOIN labels l ON l.id = cl.label_id"
# What the card queries format into SQL text (see core/sql.py).
_CARD_FILTERS: sql.Filters = (
    ("loop", "c.loop_id = :loop_id"),
    ("unarchived", "c.archived_at IS NULL"),
    ("list", "c.list_id = :list_id"),
    ("q", "(c.title LIKE :q OR c.description LIKE :q)"),
    ("label", "(l.id = :label OR l.name = :label)"),
    ("priority", "c.priority = :priority"),
    ("due_before", "c.due_at IS NOT NULL AND c.due_at <= :due_before"),
    ("overdue", "c.due_at IS NOT NULL AND c.due_at < :now AND c.completed_at IS NULL"),
    ("completed", "c.completed_at IS NOT NULL"),
    ("open", "c.completed_at IS NULL"),
    ("unassigned", "c.assignee_actor_id IS NULL"),
    ("assignee", "c.assignee_actor_id = :assignee"),
)
_BOARD_TICKET_FILTERS: sql.Filters = (
    ("open", "c.archived_at IS NULL AND l.completed_at IS NULL AND l.archived_at IS NULL"),
    ("q", "(c.title LIKE :q OR c.ticket_key LIKE :q)"),
)

_CARD_COLUMNS = sql.column_list(CARDS_COLUMNS, "c")
_GET = text(
    f"SELECT {sql.column_list(CARDS_COLUMNS)} FROM cards"  # noqa: S608 - from CARDS_COLUMNS
    " WHERE id = :id"
)
_POSITIONS = text(
    "SELECT id, position FROM cards WHERE list_id = :list_id AND archived_at IS NULL"
    " ORDER BY position, id"
)
_POSITIONS_EXCEPT = text(
    "SELECT id, position FROM cards WHERE list_id = :list_id AND archived_at IS NULL"
    " AND id != :id ORDER BY position, id"
)
_HIGHEST_POSITION = text(
    "SELECT COALESCE(MAX(position), 0) AS position FROM cards WHERE list_id = :list_id"
)
_RENUMBER = text("UPDATE cards SET position = :position WHERE id = :id")
_ADD = text(
    "INSERT INTO cards (id, list_id, title, description, position, priority, due_at,"
    " completed_at, created_at, updated_at, archived_at, version, assignee_actor_id,"
    " assignee_type, assignee_name, assigned_at, assigned_by_actor_id, loop_id, phase_id,"
    " plan_item_id, ticket_key, kind, required_actor, execution_mode, human_action_reason,"
    " human_instructions, human_confirmed_at, human_confirmed_by_actor_id, plan_revision_id,"
    " summary, summary_source, summary_basis_sha256)"
    " VALUES (:id, :list_id, :title, :description, :position, :priority, :due_at,"
    " :completed_at, :created_at, :updated_at, :archived_at, :version, :assignee_actor_id,"
    " :assignee_type, :assignee_name, :assigned_at, :assigned_by_actor_id, :loop_id, :phase_id,"
    " :plan_item_id, :ticket_key, :kind, :required_actor, :execution_mode, :human_action_reason,"
    " :human_instructions, :human_confirmed_at, :human_confirmed_by_actor_id, :plan_revision_id,"
    " :summary, :summary_source, :summary_basis_sha256)"
)
_SYNC_PLAN_ITEM = text(
    "UPDATE cards SET title = :title, description = :instructions,"
    " required_actor = :required_actor, execution_mode = :execution_mode,"
    " human_action_reason = :human_action_reason, human_instructions = :human_instructions,"
    " phase_id = :phase_id, updated_at = :now,"
    " summary = CASE WHEN :summary = '' THEN summary ELSE :summary END,"
    " summary_source = CASE WHEN :summary = '' THEN summary_source ELSE 'plan' END,"
    " summary_basis_sha256 = CASE WHEN :summary = '' THEN summary_basis_sha256 ELSE :basis END"
    " WHERE id = :id AND plan_item_id = :id"
)
_MOVE = text(
    "UPDATE cards SET list_id = :list_id, position = :position, version = version + 1,"
    " updated_at = :now WHERE id = :id"
)
_ARCHIVE = text(
    "UPDATE cards SET archived_at = :now, updated_at = :now, version = version + 1 WHERE id = :id"
)
_RESTORE = text(
    "UPDATE cards SET archived_at = NULL, position = :position, updated_at = :now,"
    " version = version + 1 WHERE id = :id"
)
_CONFIRM_HUMAN = text(
    "UPDATE cards SET completed_at = :now, human_confirmed_at = :now,"
    " human_confirmed_by_actor_id = :actor, updated_at = :now, version = version + 1"
    " WHERE id = :id"
)
_MANUAL = text(
    f"SELECT {sql.column_list(CARDS_COLUMNS)} FROM cards"  # noqa: S608 - from CARDS_COLUMNS
    " WHERE loop_id = :id AND kind = 'manual' ORDER BY created_at, id"
)
_COMPLETED_TICKETS = text(
    "SELECT COUNT(*) AS total FROM cards WHERE loop_id = :id AND kind IN ('ticket','qa')"
    " AND completed_at IS NOT NULL"
)
_PROGRESS = text(
    "SELECT loop_id, COUNT(*) AS total,"
    " COALESCE(SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS completed,"
    " COALESCE(SUM(CASE WHEN archived_at IS NOT NULL AND completed_at IS NULL THEN 1 ELSE 0"
    " END), 0) AS archived FROM cards WHERE kind IN ('ticket','qa') AND loop_id = :id"
    " GROUP BY loop_id"
)
_ALL_PROGRESS = text(
    "SELECT loop_id, COUNT(*) AS total,"
    " COALESCE(SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS completed,"
    " COALESCE(SUM(CASE WHEN archived_at IS NOT NULL AND completed_at IS NULL THEN 1 ELSE 0"
    " END), 0) AS archived FROM cards WHERE kind IN ('ticket','qa')"
    " AND loop_id IN (SELECT id FROM loops) GROUP BY loop_id"
)
_LABELS = text(
    "SELECT cl.card_id, l.id, l.name, l.color FROM card_labels cl"
    " JOIN labels l ON l.id = cl.label_id WHERE cl.card_id IN :card_ids"
    " ORDER BY l.name"
).bindparams(bindparam("card_ids", expanding=True))
_CLEAR_LABELS = text("DELETE FROM card_labels WHERE card_id = :id")
_ADD_LABEL = text(
    "INSERT OR IGNORE INTO card_labels (card_id, label_id) VALUES (:card_id, :label_id)"
)
_CHECKLIST_COUNTS = text(
    "SELECT ch.card_id, COUNT(i.id) AS total, COALESCE(SUM(i.completed), 0) AS completed"
    " FROM checklists ch LEFT JOIN checklist_items i ON i.checklist_id = ch.id"
    " WHERE ch.card_id IN :card_ids GROUP BY ch.card_id"
).bindparams(bindparam("card_ids", expanding=True))
_COMMENT_COUNTS = text(
    "SELECT card_id, COUNT(*) AS total FROM comments WHERE card_id IN :card_ids"
    " GROUP BY card_id"
).bindparams(bindparam("card_ids", expanding=True))


def _query_filters(query: CardQuery) -> tuple[list[str], dict[str, str]]:
    """The filter names ``query`` selects and the values they bind."""
    filters = ["loop"]
    parameters = {"loop_id": query.loop_id}
    if not query.include_archived:
        filters.append("unarchived")
    if query.list_id:
        filters.append("list")
        parameters["list_id"] = query.list_id
    if query.contains:
        filters.append("q")
        parameters["q"] = f"%{query.contains}%"
    if query.label:
        filters.append("label")
        parameters["label"] = query.label
    if query.priority:
        filters.append("priority")
        parameters["priority"] = query.priority
    if query.due_before:
        filters.append("due_before")
        parameters["due_before"] = query.due_before
    if query.overdue_at:
        filters.append("overdue")
        parameters["now"] = query.overdue_at
    if query.completed is not None:
        filters.append("completed" if query.completed else "open")
    if query.unassigned:
        filters.append("unassigned")
    elif query.assignee:
        filters.append("assignee")
        parameters["assignee"] = query.assignee
    return filters, parameters


def _progress(row: values.ColumnValues) -> TicketProgress:
    return TicketProgress(
        total=values.integer(row, "total"),
        completed=values.integer(row, "completed"),
        archived_incomplete=values.integer(row, "archived"),
    )


class SqlCardRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, card_id: str) -> CardsRow | None:
        row = self._connection.execute(_GET, {"id": card_id}).mappings().first()
        return None if row is None else CardsRow.from_mapping(row)

    def count(self, query: CardQuery) -> int:
        filters, parameters = _query_filters(query)
        joins = LABEL_JOIN if query.label else ""
        where = sql.where(_CARD_FILTERS, filters)
        statement = text(
            "SELECT COUNT(DISTINCT c.id) AS total"  # noqa: S608 - from LABEL_JOIN and _CARD_FILTERS
            f" FROM cards c{joins}{where}"
        )
        row = self._connection.execute(statement, parameters).mappings().one()
        return values.integer(row, "total")

    def page(
        self, query: CardQuery, *, sort: CardSort, descending: bool, limit: int, offset: int
    ) -> list[CardsRow]:
        filters, parameters = _query_filters(query)
        joins = LABEL_JOIN if query.label else ""
        where = sql.where(_CARD_FILTERS, filters)
        sort_column = (
            f"c.{sql.identifier(sort, CARD_SORTS)}" if sort in CARD_SORTS else "c.position"
        )
        direction = "DESC" if descending else "ASC"
        statement = text(
            f"SELECT DISTINCT {_CARD_COLUMNS}"  # noqa: S608 - from CARDS_COLUMNS, LABEL_JOIN, _CARD_FILTERS, CARD_SORTS
            f" FROM cards c{joins}{where} ORDER BY {sort_column} {direction}, c.id"
            " LIMIT :limit OFFSET :offset"
        )
        result = self._connection.execute(
            statement, {**parameters, "limit": limit, "offset": offset}
        )
        return [CardsRow.from_mapping(row) for row in result.mappings()]

    def board_tickets(self, *, contains: str | None, limit: int) -> list[BoardTicket]:
        filters = ["open"]
        parameters: dict[str, str | int] = {"limit": limit}
        if contains:
            filters.append("q")
            parameters["q"] = f"%{contains}%"
        where = sql.where(_BOARD_TICKET_FILTERS, filters)
        statement = text(
            f"SELECT {_CARD_COLUMNS},"  # noqa: S608 - from CARDS_COLUMNS, _BOARD_TICKET_FILTERS
            " l.key AS loop_key, l.name AS loop_name, l.stage AS loop_stage"
            f" FROM cards c JOIN loops l ON l.id = c.loop_id{where}"
            " ORDER BY l.sequence, c.position, c.id LIMIT :limit"
        )
        return [
            BoardTicket(
                card=CardsRow.from_mapping(row),
                loop_key=values.text(row, "loop_key"),
                loop_name=values.text(row, "loop_name"),
                loop_stage=values.text(row, "loop_stage"),
            )
            for row in self._connection.execute(statement, parameters).mappings()
        ]

    def positions(self, list_id: str, *, exclude: str | None = None) -> list[tuple[str, int]]:
        if exclude is None:
            result = self._connection.execute(_POSITIONS, {"list_id": list_id})
        else:
            parameters = {"list_id": list_id, "id": exclude}
            result = self._connection.execute(_POSITIONS_EXCEPT, parameters)
        return [
            (values.text(row, "id"), values.integer(row, "position")) for row in result.mappings()
        ]

    def highest_position(self, list_id: str) -> int:
        row = self._connection.execute(_HIGHEST_POSITION, {"list_id": list_id}).mappings().one()
        return values.integer(row, "position")

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for card_id, position in positions:
            self._connection.execute(_RENUMBER, {"position": position, "id": card_id})

    def add(self, row: CardsRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "list_id": row.list_id,
                "title": row.title,
                "description": row.description,
                "position": row.position,
                "priority": row.priority,
                "due_at": row.due_at,
                "completed_at": row.completed_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "archived_at": row.archived_at,
                "version": row.version,
                "assignee_actor_id": row.assignee_actor_id,
                "assignee_type": row.assignee_type,
                "assignee_name": row.assignee_name,
                "assigned_at": row.assigned_at,
                "assigned_by_actor_id": row.assigned_by_actor_id,
                "loop_id": row.loop_id,
                "phase_id": row.phase_id,
                "plan_item_id": row.plan_item_id,
                "ticket_key": row.ticket_key,
                "kind": row.kind,
                "required_actor": row.required_actor,
                "execution_mode": row.execution_mode,
                "human_action_reason": row.human_action_reason,
                "human_instructions": row.human_instructions,
                "human_confirmed_at": row.human_confirmed_at,
                "human_confirmed_by_actor_id": row.human_confirmed_by_actor_id,
                "plan_revision_id": row.plan_revision_id,
                "summary": row.summary,
                "summary_source": row.summary_source,
                "summary_basis_sha256": row.summary_basis_sha256,
            },
        )

    def update(self, card_id: str, changes: CardChanges) -> None:
        columns = sql.assignments(changes, CARD_EDITABLE)
        statement = text(f"UPDATE cards SET {columns} WHERE id = :id")  # noqa: S608 - from CARD_EDITABLE
        self._connection.execute(statement, {**changes, "id": card_id})

    def sync_plan_item(self, item: LoopPlanItemsRow, *, now: str, summary_basis: str) -> None:
        self._connection.execute(
            _SYNC_PLAN_ITEM,
            {
                "title": item.title,
                "instructions": item.instructions,
                "required_actor": item.required_actor,
                "execution_mode": item.execution_mode,
                "human_action_reason": item.human_action_reason,
                "human_instructions": item.human_instructions,
                "phase_id": item.phase_id,
                "summary": item.summary,
                "basis": summary_basis,
                "now": now,
                "id": item.id,
            },
        )

    def move(self, card_id: str, list_id: str, position: int, *, now: str) -> None:
        self._connection.execute(
            _MOVE, {"list_id": list_id, "position": position, "now": now, "id": card_id}
        )

    def archive(self, card_id: str, *, now: str) -> None:
        self._connection.execute(_ARCHIVE, {"now": now, "id": card_id})

    def restore(self, card_id: str, position: int, *, now: str) -> None:
        self._connection.execute(_RESTORE, {"position": position, "now": now, "id": card_id})

    def confirm_human(self, card_id: str, actor_id: str, *, now: str) -> None:
        self._connection.execute(_CONFIRM_HUMAN, {"now": now, "actor": actor_id, "id": card_id})

    def manual(self, loop_id: str) -> list[CardsRow]:
        result = self._connection.execute(_MANUAL, {"id": loop_id})
        return [CardsRow.from_mapping(row) for row in result.mappings()]

    def completed_tickets(self, loop_id: str) -> int:
        row = self._connection.execute(_COMPLETED_TICKETS, {"id": loop_id}).mappings().one()
        return values.integer(row, "total")

    def progress(self, loop_id: str | None) -> dict[str, TicketProgress]:
        if loop_id is None:
            result = self._connection.execute(_ALL_PROGRESS)
        else:
            result = self._connection.execute(_PROGRESS, {"id": loop_id})
        return {values.text(row, "loop_id"): _progress(row) for row in result.mappings()}

    def labels(self, card_ids: Sequence[str]) -> dict[str, list[LabelsRow]]:
        found: dict[str, list[LabelsRow]] = {card_id: [] for card_id in card_ids}
        if not card_ids:
            return found
        result = self._connection.execute(_LABELS, {"card_ids": list(card_ids)})
        for row in result.mappings():
            found[values.text(row, "card_id")].append(LabelsRow.from_mapping(row))
        return found

    def set_labels(self, card_id: str, label_ids: Sequence[str]) -> None:
        self._connection.execute(_CLEAR_LABELS, {"id": card_id})
        for label_id in label_ids:
            self._connection.execute(_ADD_LABEL, {"card_id": card_id, "label_id": label_id})

    def counts(self, card_ids: Sequence[str]) -> dict[str, CardCounts]:
        totals: dict[str, tuple[int, int]] = dict.fromkeys(card_ids, (0, 0))
        comments = dict.fromkeys(card_ids, 0)
        if card_ids:
            parameters = {"card_ids": list(card_ids)}
            for row in self._connection.execute(_CHECKLIST_COUNTS, parameters).mappings():
                card_id = values.text(row, "card_id")
                totals[card_id] = (values.integer(row, "total"), values.integer(row, "completed"))
            for row in self._connection.execute(_COMMENT_COUNTS, parameters).mappings():
                comments[values.text(row, "card_id")] = values.integer(row, "total")
        return {
            card_id: CardCounts(
                checklist_total=totals[card_id][0],
                checklist_completed=totals[card_id][1],
                comment_count=comments[card_id],
            )
            for card_id in card_ids
        }
