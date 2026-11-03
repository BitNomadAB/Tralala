"""SQL text whose variable parts come from literals only.

Values always travel as bind parameters, and a list of values as an expanding bind parameter
(``IN :ids``). The only parts of a statement that may be formatted into its text are identifiers
and fragments taken from a module-level tuple of string literals. These helpers do the taking: they
return text from the tuple they are given and refuse any name that is not in it, so request input
can never become SQL. A statement formatted from their result carries ``# noqa: S608`` with a reason
that names the tuple.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

type Filters = tuple[tuple[str, str], ...]
"""Named WHERE fragments as ``(name, fragment)`` pairs, in the order the statement lists them."""


def identifier(name: str, allowed: tuple[str, ...]) -> str:
    """``name`` when it is one of ``allowed``; anything else is a programming error."""
    if name not in allowed:
        raise ValueError(f"{name!r} is not an allowed SQL identifier")
    return name


def _chosen(names: Iterable[str], allowed: tuple[str, ...]) -> list[str]:
    wanted = set(names)
    unknown = wanted.difference(allowed)
    if unknown:
        raise ValueError(f"not allowed SQL identifiers: {sorted(unknown)}")
    return [column for column in allowed if column in wanted]


def assignments(names: Iterable[str], allowed: tuple[str, ...]) -> str:
    """``a = :a, b = :b`` for the named columns, in the order of ``allowed``."""
    return ", ".join(f"{column} = :{column}" for column in _chosen(names, allowed))


def insert_columns(names: Iterable[str], allowed: tuple[str, ...]) -> tuple[str, str]:
    """An INSERT's column list and its ``:column`` placeholders, in the order of ``allowed``."""
    columns = _chosen(names, allowed)
    return ", ".join(columns), ", ".join(f":{column}" for column in columns)


def where(filters: Filters, selected: Collection[str]) -> str:
    """`` WHERE a AND b`` for the selected filter names, in the order of ``filters``.

    Empty when nothing is selected. A selected name that is not a filter is refused rather than
    skipped, because a filter dropped by a typo would widen the result without a sound.
    """
    known = {name for name, _ in filters}
    unknown = set(selected).difference(known)
    if unknown:
        raise ValueError(f"unknown SQL filters: {sorted(unknown)}")
    chosen = [fragment for name, fragment in filters if name in selected]
    return f" WHERE {' AND '.join(chosen)}" if chosen else ""
