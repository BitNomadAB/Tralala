"""SQLite's check rows turned into a verdict that names what is wrong (``app/core/integrity.py``).

``foreign_key_problem`` is what the migration runner refuses a schema change with before its COMMIT
(``storage/schema/runner.py``; a real file in ``tests/infrastructure/test_table_rebuild.py``).
``snapshot_problem`` and ``unreadable_problem`` decide whether a backup may be restored
(``storage/sqlite.check_snapshot``; real files in
``tests/infrastructure/test_snapshot_restore.py``). Here the rows are fixed, so no database is
opened.
"""

from __future__ import annotations

from typing import get_args

from app.core.integrity import (
    REPORTED_VIOLATIONS,
    SNAPSHOT_REFUSALS,
    SnapshotProblem,
    SnapshotRefusal,
    foreign_key_problem,
    integrity_problem,
    snapshot_problem,
    unreadable_problem,
)

# Rows as SQLite answers them (probed on 3.45.3 and 3.50.4).
OK = [("ok",)]
MISSING_FROM_INDEX = [("row 42 missing from index probe_damage_v",)]
ORPHAN = [("probe_child", 7, "probe_parent", 0)]
# https://www.sqlite.org/rescode.html
SQLITE_CORRUPT = 11
SQLITE_CORRUPT_INDEX = 779
SQLITE_CANTOPEN = 14
SQLITE_NOTADB = 26


def test_no_violation_is_no_problem() -> None:
    assert foreign_key_problem([]) is None


def test_a_violation_names_the_table_the_row_the_parent_and_the_key() -> None:
    problem = foreign_key_problem([("cards", 12, "loop_phases", 1)])

    assert problem == (
        "foreign_key_check: 1 row(s) name a row that does not exist: cards rowid 12 -> loop_phases"
        " (key 1)"
    )


def test_every_violation_is_named_in_the_order_sqlite_reports_them() -> None:
    problem = foreign_key_problem(
        [("loops", 3, "loop_plans", 6), ("loop_history", None, "loops", 0)]
    )

    assert problem == (
        "foreign_key_check: 2 row(s) name a row that does not exist: loops rowid 3 -> loop_plans"
        " (key 6); loop_history rowid None -> loops (key 0)"
    )


def test_a_long_report_names_the_first_rows_and_counts_the_rest() -> None:
    rows = [("cards", rowid, "loop_phases", 0) for rowid in range(1, 26)]

    problem = foreign_key_problem(rows, limit=3)

    assert problem == (
        "foreign_key_check: 25 row(s) name a row that does not exist: cards rowid 1 -> loop_phases"
        " (key 0); cards rowid 2 -> loop_phases (key 0); cards rowid 3 -> loop_phases (key 0);"
        " and 22 more"
    )


def test_the_default_limit_names_twenty_rows() -> None:
    rows = [("cards", rowid, "loop_phases", 0) for rowid in range(REPORTED_VIOLATIONS + 1)]

    problem = foreign_key_problem(rows)

    assert problem is not None
    assert REPORTED_VIOLATIONS == 20
    assert problem.count(" -> loop_phases") == REPORTED_VIOLATIONS
    assert problem.endswith("; and 1 more")


def test_exactly_the_limit_has_no_tail() -> None:
    rows = [("cards", rowid, "loop_phases", 0) for rowid in range(2)]

    problem = foreign_key_problem(rows, limit=2)

    assert problem is not None
    assert "more" not in problem


def test_an_ok_integrity_check_is_no_problem() -> None:
    assert integrity_problem(OK) is None


def test_integrity_findings_are_named_in_the_order_sqlite_reports_them() -> None:
    problem = integrity_problem(
        [("row 42 missing from index probe_damage_v",), ("wrong # of entries in index probe_v",)]
    )

    assert problem == (
        "integrity_check: 2 problem(s): row 42 missing from index probe_damage_v;"
        " wrong # of entries in index probe_v"
    )


def test_a_long_integrity_report_names_the_first_findings_and_counts_the_rest() -> None:
    findings = [(f"row {rowid} missing from index probe_v",) for rowid in range(1, 6)]

    problem = integrity_problem(findings, limit=2)

    assert problem == (
        "integrity_check: 5 problem(s): row 1 missing from index probe_v;"
        " row 2 missing from index probe_v; and 3 more"
    )


def test_an_integrity_check_without_an_answer_is_not_a_pass() -> None:
    assert integrity_problem([]) == "integrity_check: no answer"


def test_ok_beside_a_finding_is_not_a_pass() -> None:
    assert integrity_problem([("ok",), ("page 7: btreeInitPage() returns error code 11",)]) == (
        "integrity_check: 2 problem(s): ok; page 7: btreeInitPage() returns error code 11"
    )


def test_a_snapshot_that_passes_both_checks_is_restored() -> None:
    assert snapshot_problem(OK, []) is None


def test_a_snapshot_with_a_broken_key_is_refused_naming_the_row() -> None:
    assert snapshot_problem(OK, ORPHAN) == SnapshotProblem(
        reason="foreign_key_check_failed",
        detail=(
            "foreign_key_check: 1 row(s) name a row that does not exist:"
            " probe_child rowid 7 -> probe_parent (key 0)"
        ),
    )


def test_a_damaged_snapshot_is_refused_for_its_damage_before_its_keys() -> None:
    assert snapshot_problem(MISSING_FROM_INDEX, ORPHAN) == SnapshotProblem(
        reason="integrity_check_failed",
        detail="integrity_check: 1 problem(s): row 42 missing from index probe_damage_v",
    )


def test_a_damaged_page_sqlite_raises_on_failed_the_integrity_check() -> None:
    expected = SnapshotProblem(
        reason="integrity_check_failed",
        detail="integrity_check: database disk image is malformed",
    )

    assert unreadable_problem(SQLITE_CORRUPT, "database disk image is malformed") == expected
    # An extended code carries the primary one in its low byte.
    assert unreadable_problem(SQLITE_CORRUPT_INDEX, "database disk image is malformed") == expected


def test_a_file_sqlite_will_not_read_is_not_a_database() -> None:
    assert unreadable_problem(SQLITE_NOTADB, "file is not a database") == SnapshotProblem(
        reason="not_a_database", detail="file is not a database"
    )
    assert unreadable_problem(SQLITE_CANTOPEN, "unable to open database file") == SnapshotProblem(
        reason="not_a_database", detail="unable to open database file"
    )
    # 0: an error the driver raised itself, without an SQLite code.
    assert unreadable_problem(0, "Cannot operate on a closed database.").reason == "not_a_database"


def test_every_refusal_reason_has_its_own_message() -> None:
    reasons = set(get_args(SnapshotRefusal.__value__))

    assert set(SNAPSHOT_REFUSALS) == reasons
    assert len(set(SNAPSHOT_REFUSALS.values())) == len(reasons)
    assert all("not restored" in message for message in SNAPSHOT_REFUSALS.values())
