"""``foreign_key_problem`` turns ``PRAGMA foreign_key_check`` rows into a refusal that names them.

The migration runner calls it before every COMMIT (``storage/schema/runner.py``); a real file shows
the refusal rolling a schema change back in ``tests/infrastructure/test_table_rebuild.py``. Here the
rows are fixed, so no database is opened.
"""

from __future__ import annotations

from app.core.integrity import REPORTED_VIOLATIONS, foreign_key_problem


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
