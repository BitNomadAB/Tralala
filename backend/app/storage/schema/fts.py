"""Optional FTS5 index bootstrap.

FTS5 is a search accelerator, not part of the schema contract: runtimes without FTS5 fall back
to LIKE. It is therefore created outside the Alembic chain and never blocks a migration.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

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


def ensure_fts(engine: Engine) -> bool:
    """Create the FTS tables/triggers when supported; rebuild only when first created."""
    try:
        with engine.begin() as conn:
            existed = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cards_fts'"
            ).first()
            history_existed = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'loop_history_fts'"
            ).first()
            for statement in FTS_STATEMENTS:
                conn.exec_driver_sql(statement)
            if not existed:
                conn.exec_driver_sql("INSERT INTO cards_fts(cards_fts) VALUES('rebuild')")
            if not history_existed:
                conn.exec_driver_sql(
                    "INSERT INTO loop_history_fts(loop_history_fts) VALUES('rebuild')"
                )
        return True
    except Exception:  # noqa: BLE001 - optional capability, must never break startup
        return False
