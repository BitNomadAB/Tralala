"""What SQLite's ``PRAGMA foreign_key_check`` reports, turned into a verdict a person can act on.

A schema change runs with foreign keys off (SQLite's table-rebuild procedure,
https://www.sqlite.org/lang_altertable.html#otheralter), so nothing stops it from leaving a row that
names a missing one. ``storage/schema/runner.py`` therefore runs ``PRAGMA foreign_key_check`` before
the COMMIT and refuses the change when it reports a row; this module says which rows. It is pure, so
the unit suite holds it to fixed rows without opening a database.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

REPORTED_VIOLATIONS: Final = 20
"""How many offending rows a refusal names; the count covers all of them."""


def foreign_key_problem(
    violations: Sequence[Sequence[object]], *, limit: int = REPORTED_VIOLATIONS
) -> str | None:
    """None when ``foreign_key_check`` found nothing, else which rows name a missing row.

    Each row is what the pragma returns: the table, the offending row's rowid (None for a table
    without one), the parent table and the index of the foreign key in the table's key list.
    """
    if not violations:
        return None
    shown = [
        f"{table} rowid {rowid} -> {parent} (key {key})"
        for table, rowid, parent, key in (tuple(row) for row in violations[:limit])
    ]
    more = len(violations) - len(shown)
    tail = f"; and {more} more" if more > 0 else ""
    return (
        f"foreign_key_check: {len(violations)} row(s) name a row that does not exist: "
        + "; ".join(shown)
        + tail
    )
