"""Optional FTS5 index bootstrap.

FTS5 is a search accelerator, not part of the schema contract: runtimes without FTS5 fall back
to LIKE. It is therefore created outside the Alembic chain and never blocks a migration.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection, Engine

from ..sqlite import write_transaction

FTS_STATEMENTS = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts
    USING fts5(title, description, content='cards', content_rowid='rowid')
    """,
    """
    CREATE TRIGGER IF NOT EXISTS cards_fts_ai AFTER INSERT ON cards BEGIN
        INSERT INTO cards_fts(rowid, title, description)
        VALUES (new.rowid, new.title, new.description);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS cards_fts_ad AFTER DELETE ON cards BEGIN
        INSERT INTO cards_fts(cards_fts, rowid, title, description)
        VALUES ('delete', old.rowid, old.title, old.description);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS cards_fts_au AFTER UPDATE ON cards BEGIN
        INSERT INTO cards_fts(cards_fts, rowid, title, description)
        VALUES ('delete', old.rowid, old.title, old.description);
        INSERT INTO cards_fts(rowid, title, description)
        VALUES (new.rowid, new.title, new.description);
    END
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS loop_history_fts
    USING fts5(loop_name, search_text, content='loop_history', content_rowid='rowid')
    """,
    """
    CREATE TRIGGER IF NOT EXISTS loop_history_fts_ai AFTER INSERT ON loop_history BEGIN
        INSERT INTO loop_history_fts(rowid, loop_name, search_text)
        VALUES (new.rowid, new.loop_name, new.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS loop_history_fts_ad AFTER DELETE ON loop_history BEGIN
        INSERT INTO loop_history_fts(loop_history_fts, rowid, loop_name, search_text)
        VALUES ('delete', old.rowid, old.loop_name, old.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS loop_history_fts_au AFTER UPDATE ON loop_history BEGIN
        INSERT INTO loop_history_fts(loop_history_fts, rowid, loop_name, search_text)
        VALUES ('delete', old.rowid, old.loop_name, old.search_text);
        INSERT INTO loop_history_fts(rowid, loop_name, search_text)
        VALUES (new.rowid, new.loop_name, new.search_text);
    END
    """,
]


def _history_index_matches(conn: Connection) -> bool:
    """External-content FTS5 reads its rows from the table, so compare the index side instead."""
    return (
        conn.exec_driver_sql("SELECT COUNT(*) FROM loop_history").scalar_one()
        == conn.exec_driver_sql("SELECT COUNT(*) FROM loop_history_fts_docsize").scalar_one()
    )


# Each index with the triggers that keep it in step with its table.
_INDEXES = {
    "cards_fts": ("cards_fts_ai", "cards_fts_ad", "cards_fts_au"),
    "loop_history_fts": ("loop_history_fts_ai", "loop_history_fts_ad", "loop_history_fts_au"),
}


def ensure_fts(engine: Engine) -> bool:
    """Create the FTS tables/triggers when supported; rebuild an index that was not kept in step.

    An index is rebuilt when it is new, or when one of its triggers was missing: a revision that
    rebuilds ``cards`` or ``loop_history`` (``batch_alter_table``) drops the old table with its
    triggers and copies the rows under new rowids, so the index no longer matches its table.
    """
    try:
        with write_transaction(engine) as conn:
            present = {
                str(name)
                for (name,) in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
                )
            }
            for statement in FTS_STATEMENTS:
                conn.exec_driver_sql(statement)
            kept = {
                index: index in present and set(triggers) <= present
                for index, triggers in _INDEXES.items()
            }
            if not kept["cards_fts"]:
                conn.exec_driver_sql("INSERT INTO cards_fts(cards_fts) VALUES('rebuild')")
            if not kept["loop_history_fts"] or not _history_index_matches(conn):
                # A restore or a copy can also leave the history index behind the table;
                # rebuilding is cheap and turns a silently empty history search into a correct one.
                conn.exec_driver_sql(
                    "INSERT INTO loop_history_fts(loop_history_fts) VALUES('rebuild')"
                )
    except Exception:  # noqa: BLE001 - optional capability, must never break startup
        return False
    return True
