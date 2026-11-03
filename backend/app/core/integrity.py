"""What SQLite's ``integrity_check`` and ``foreign_key_check`` report, as a verdict to act on.

A schema change runs with foreign keys off (SQLite's table-rebuild procedure,
https://www.sqlite.org/lang_altertable.html#otheralter), so nothing stops it from leaving a row that
names a missing one. ``storage/schema/runner.py`` therefore runs ``PRAGMA foreign_key_check`` before
the COMMIT and refuses the change when it reports a row; ``foreign_key_problem`` says which rows.

A backup is restored only when both checks pass on the snapshot (``storage/sqlite.check_snapshot``);
``snapshot_problem`` and ``unreadable_problem`` decide, and the refusal is
``422 board_backup_invalid``. The module is pure, so the unit suite holds it to fixed rows without
opening a database.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

REPORTED_VIOLATIONS: Final = 20
"""How many offending rows a refusal names; the count covers all of them."""

SQLITE_CORRUPT: Final = 11
"""SQLite's primary result code for a damaged database file (https://www.sqlite.org/rescode.html)."""

type SnapshotRefusal = Literal[
    "not_a_database", "integrity_check_failed", "foreign_key_check_failed"
]
"""Why a backup was not restored: ``details.reason`` of ``422 board_backup_invalid``."""

SNAPSHOT_REFUSALS: Final[Mapping[SnapshotRefusal, str]] = {
    "not_a_database": "Backup is not a database this installation can read and was not restored",
    "integrity_check_failed": "Backup failed its integrity check and was not restored",
    "foreign_key_check_failed": "Backup failed its foreign key check and was not restored",
}
"""The error message for each reason."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotProblem:
    """Why a snapshot may not replace a board's database."""

    reason: SnapshotRefusal
    detail: str
    """What SQLite answered, without paths: ``details.detail`` of the refusal."""


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


def integrity_problem(
    findings: Sequence[Sequence[object]], *, limit: int = REPORTED_VIOLATIONS
) -> str | None:
    """None when ``integrity_check`` answered its single ``ok`` row, else what it found.

    The pragma answers one row with one text column: ``ok``, or one problem per row. An empty
    answer is not a pass.
    """
    messages = [str(row[0]) for row in findings]
    if messages == ["ok"]:
        return None
    if not messages:
        return "integrity_check: no answer"
    shown = messages[:limit]
    more = len(messages) - len(shown)
    tail = f"; and {more} more" if more > 0 else ""
    return f"integrity_check: {len(messages)} problem(s): " + "; ".join(shown) + tail


def snapshot_problem(
    findings: Sequence[Sequence[object]], violations: Sequence[Sequence[object]]
) -> SnapshotProblem | None:
    """None to restore a snapshot, else why not, from the rows its two checks answered.

    ``integrity_check`` decides first: a file that fails it is refused for that whatever its keys
    say (the storage layer does not ask ``foreign_key_check`` of it). Then any ``foreign_key_check``
    row refuses it, because a restored board would hold a row that names a missing one.
    """
    integrity = integrity_problem(findings)
    if integrity is not None:
        return SnapshotProblem(reason="integrity_check_failed", detail=integrity)
    keys = foreign_key_problem(violations)
    if keys is not None:
        return SnapshotProblem(reason="foreign_key_check_failed", detail=keys)
    return None


def unreadable_problem(error_code: int, message: str) -> SnapshotProblem:
    """The refusal of a snapshot SQLite would not open or check, from the error it raised.

    ``error_code`` is SQLite's extended result code (0 when the driver raised the error itself); its
    low byte is the primary code. A damaged file (``SQLITE_CORRUPT``, also raised while
    ``integrity_check`` walks a broken page) failed the integrity check; anything else, such as
    ``file is not a database``, is not a database this installation can read.
    """
    if error_code & 0xFF == SQLITE_CORRUPT:
        return SnapshotProblem(
            reason="integrity_check_failed", detail=f"integrity_check: {message}"
        )
    return SnapshotProblem(reason="not_a_database", detail=message)
