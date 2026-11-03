"""Column values read from SQLite, checked against the type the schema declares.

The generated ``from_mapping`` of every row calls one of these per column. Each one checks the value
it is given instead of trusting it, so a value of the wrong type stops at the row with the column's
name rather than travelling on as something it is not. ``None`` is accepted only by the ``_or_none``
variants, which the generator picks for nullable columns.
"""

from __future__ import annotations

from typing import Protocol


class ColumnValues(Protocol):
    """A result row by column name: SQLAlchemy's ``RowMapping``, or a plain dict in a test.

    Not ``Mapping[str, object]``: a ``RowMapping`` is keyed by ``str | Column``, and a mapping's key
    type is invariant, so only the one operation the rows need is asked for.
    """

    def __getitem__(self, column: str, /) -> object: ...


class _Prefixed:
    """One table's columns in a joined result, where they were selected as ``<prefix><column>``."""

    __slots__ = ("_prefix", "_row")

    def __init__(self, row: ColumnValues, prefix: str) -> None:
        self._row = row
        self._prefix = prefix

    def __getitem__(self, column: str, /) -> object:
        return self._row[self._prefix + column]


def prefixed(row: ColumnValues, prefix: str) -> ColumnValues:
    """The columns ``sql.column_list(..., prefix=prefix)`` selected, under their own names.

    A generated row's ``from_mapping`` reads a joined table's columns through this, so two tables
    that share a column name (``id``, ``name``) never meet in one result key.
    """
    return _Prefixed(row, prefix)


class ColumnTypeError(TypeError):
    """A column held a value its declared type does not allow."""

    def __init__(self, column: str, expected: str, value: object) -> None:
        super().__init__(f"{column}: expected {expected}, got {type(value).__name__}")
        self.column = column


def text(row: ColumnValues, column: str) -> str:
    value = row[column]
    if isinstance(value, str):
        return value
    raise ColumnTypeError(column, "str", value)


def text_or_none(row: ColumnValues, column: str) -> str | None:
    return None if row[column] is None else text(row, column)


def integer(row: ColumnValues, column: str) -> int:
    value = row[column]
    # bool is an int subclass; SQLite never returns one, so one here is a programming error.
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ColumnTypeError(column, "int", value)


def integer_or_none(row: ColumnValues, column: str) -> int | None:
    return None if row[column] is None else integer(row, column)


def real(row: ColumnValues, column: str) -> float:
    value = row[column]
    # A REAL column may hand back an integral value as int.
    if isinstance(value, float):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    raise ColumnTypeError(column, "float", value)


def real_or_none(row: ColumnValues, column: str) -> float | None:
    return None if row[column] is None else real(row, column)


def flag(row: ColumnValues, column: str) -> bool:
    """A BOOLEAN column: SQLite stores 0 or 1."""
    value = row[column]
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return value == 1
    raise ColumnTypeError(column, "0 or 1", value)


def flag_or_none(row: ColumnValues, column: str) -> bool | None:
    return None if row[column] is None else flag(row, column)


def blob(row: ColumnValues, column: str) -> bytes:
    value = row[column]
    if isinstance(value, bytes):
        return value
    raise ColumnTypeError(column, "bytes", value)


def blob_or_none(row: ColumnValues, column: str) -> bytes | None:
    return None if row[column] is None else blob(row, column)
