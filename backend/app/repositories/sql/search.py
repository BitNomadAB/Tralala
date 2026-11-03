"""``CardSearchRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import CARDS_COLUMNS, CardsRow
from ..search import CardSearch
from .cards import LABEL_JOIN

# What the search formats into its SQL text (see core/sql.py).
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
_CARD_COLUMNS = sql.column_list(CARDS_COLUMNS, "c")


def _filters(search: CardSearch) -> tuple[list[str], dict[str, str]]:
    """The filter names ``search`` selects and the values they bind; ``match`` and ``label`` also
    need their joins (``_CARD_FTS_JOIN``, ``LABEL_JOIN``)."""
    filters = ["loop"]
    parameters = {"loop_id": search.loop_id}
    if search.match is not None:
        filters.append("match")
        parameters["match"] = search.match
    elif search.contains is not None:
        filters.append("q")
        parameters["q"] = f"%{search.contains}%"
    if not search.include_archived:
        filters.append("unarchived")
    if search.priority is not None:
        filters.append("priority")
        parameters["priority"] = search.priority
    if search.label is not None:
        filters.append("label")
        parameters["label"] = search.label
    if search.completed is not None:
        filters.append("completed" if search.completed else "open")
    if search.overdue_at is not None:
        filters.append("overdue")
        parameters["now"] = search.overdue_at
    if search.list_id is not None:
        filters.append("list")
        parameters["list_id"] = search.list_id
    return filters, parameters


class SqlCardSearchRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def count(self, search: CardSearch) -> int:
        filters, parameters = _filters(search)
        joins = ""
        if search.match is not None:
            joins += _CARD_FTS_JOIN
        if search.label is not None:
            joins += LABEL_JOIN
        where = sql.where(_CARD_SEARCH_FILTERS, filters)
        statement = text(
            "SELECT COUNT(DISTINCT c.id) AS total"  # noqa: S608 - from _CARD_FTS_JOIN, LABEL_JOIN, _CARD_SEARCH_FILTERS
            f" FROM cards c{joins}{where}"
        )
        row = self._connection.execute(statement, parameters).mappings().one()
        return values.integer(row, "total")

    def page(self, search: CardSearch, *, limit: int, offset: int) -> list[CardsRow]:
        filters, parameters = _filters(search)
        joins = ""
        if search.match is not None:
            joins += _CARD_FTS_JOIN
        if search.label is not None:
            joins += LABEL_JOIN
        where = sql.where(_CARD_SEARCH_FILTERS, filters)
        statement = text(
            f"SELECT DISTINCT {_CARD_COLUMNS}"  # noqa: S608 - from CARDS_COLUMNS, _CARD_FTS_JOIN, LABEL_JOIN, _CARD_SEARCH_FILTERS
            f" FROM cards c{joins}{where} ORDER BY c.updated_at DESC, c.id"
            " LIMIT :limit OFFSET :offset"
        )
        result = self._connection.execute(
            statement, {**parameters, "limit": limit, "offset": offset}
        )
        return [CardsRow.from_mapping(row) for row in result.mappings()]
