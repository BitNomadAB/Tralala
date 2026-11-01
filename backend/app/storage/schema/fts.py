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
]


def ensure_fts(engine: Engine) -> bool:
    """Create the FTS table/triggers when supported; rebuild only when first created."""
    try:
        with engine.begin() as conn:
            existed = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cards_fts'"
            ).first()
            for statement in FTS_STATEMENTS:
                conn.exec_driver_sql(statement)
            if not existed:
                conn.exec_driver_sql("INSERT INTO cards_fts(cards_fts) VALUES('rebuild')")
        return True
    except Exception:  # noqa: BLE001 - optional capability, must never break startup
        return False
