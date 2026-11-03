"""The PRAGMA lists, held to the SQLite documentation each one follows (``app/core/pragmas.py``).

``app/storage/sqlite.py`` sends them; ``tests/infrastructure/test_sqlite_setup.py`` reads the
connect-time settings back from a real connection. Here they are constants, so no database is
opened.
"""

from __future__ import annotations

from app.core import pragmas
from app.core.pragmas import (
    AFTER_RESTORE_PRAGMAS,
    BUSY_TIMEOUT_MS,
    CHECKPOINT,
    CLOSE_PRAGMAS,
    CONNECT_PRAGMAS,
    FOREIGN_KEY_CHECK,
    INTEGRITY_CHECK,
    JOURNAL_SIZE_LIMIT_BYTES,
    OPTIMIZE,
)

# https://www.sqlite.org/pragma.html#pragma_optimize
OPTIMIZE_DEBUG = 0x00001
OPTIMIZE_ANALYZE = 0x00002
OPTIMIZE_ANALYSIS_LIMIT = 0x00010
OPTIMIZE_ALL_TABLES = 0x10000
OPTIMIZE_DEFAULT_MASK = 0xFFFE
# https://www.sqlite.org/wal.html: a WAL is checkpointed and reused at about 1000 pages.
AUTOCHECKPOINT_PAGES = 1000
DEFAULT_PAGE_SIZE = 4096


def test_every_connection_gets_these_settings_in_this_order() -> None:
    assert CONNECT_PRAGMAS == (
        "PRAGMA foreign_keys=ON",
        "PRAGMA journal_mode=WAL",
        "PRAGMA busy_timeout=5000",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA journal_size_limit=67108864",
    )
    assert BUSY_TIMEOUT_MS == 5000


def test_the_journal_limit_is_64_mib_and_above_what_a_wal_reaches_between_checkpoints() -> None:
    assert JOURNAL_SIZE_LIMIT_BYTES == 64 * 1024 * 1024
    # So an ordinary commit never pays for a truncation; only an outsized transaction is cut back.
    assert JOURNAL_SIZE_LIMIT_BYTES > AUTOCHECKPOINT_PAGES * DEFAULT_PAGE_SIZE


def test_a_board_going_out_of_use_is_optimized_and_then_checkpointed() -> None:
    # optimize first: its ANALYZE writes into the WAL, which the checkpoint then empties.
    assert CLOSE_PRAGMAS == ("PRAGMA optimize=0x1fffe", "PRAGMA wal_checkpoint(TRUNCATE)")
    assert CLOSE_PRAGMAS == (OPTIMIZE, CHECKPOINT)


def test_optimize_keeps_the_default_mask_and_looks_at_every_table() -> None:
    mask = int(OPTIMIZE.removeprefix("PRAGMA optimize="), 16)

    assert mask == OPTIMIZE_DEFAULT_MASK | OPTIMIZE_ALL_TABLES
    assert mask & OPTIMIZE_ANALYZE
    assert mask & OPTIMIZE_ANALYSIS_LIMIT
    assert mask & OPTIMIZE_ALL_TABLES
    assert not mask & OPTIMIZE_DEBUG


def test_a_restore_ends_with_a_truncating_checkpoint() -> None:
    assert AFTER_RESTORE_PRAGMAS == ("PRAGMA wal_checkpoint(TRUNCATE)",)
    assert CHECKPOINT == "PRAGMA wal_checkpoint(TRUNCATE)"


def test_a_snapshot_is_checked_by_both_of_sqlites_checks() -> None:
    assert (INTEGRITY_CHECK, FOREIGN_KEY_CHECK) == (
        "PRAGMA integrity_check",
        "PRAGMA foreign_key_check",
    )


def test_nothing_is_sent_before_a_backup() -> None:
    """The backup API copies the committed pages, those in the -wal file included, by itself."""
    lists = {name for name in vars(pragmas) if name.endswith("_PRAGMAS")}

    assert lists == {"CONNECT_PRAGMAS", "CLOSE_PRAGMAS", "AFTER_RESTORE_PRAGMAS"}
