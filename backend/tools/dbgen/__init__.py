"""``python -m tools.dbgen``: the schema-driven first step of the backend build.

In pipeline order, each step stopping the build on a failure:

1. **Migrations.** Each Alembic chain has exactly one head and a linear ``down_revision`` chain, and
   both chains apply from empty to head in an in-memory SQLite database through
   ``app/storage/schema/runner.py`` (the board chain also gets the FTS5 bootstrap the application
   runs). These two in-memory databases are the only ones the tool opens.
2. **Schema rules** (``rules.SCHEMA_RULES``): structural rules that belong to the build, not to a
   test.
3. **Rows.** ``app/db/generated/{registry,board}.py``: one frozen, slotted, keyword-only dataclass
   per table with a checked ``from_mapping`` and a column tuple, so a repository selects exactly a
   row's columns. Pyright then holds every consumer to them.
4. **SQL.** Every SQL statement in ``app/`` is compiled by SQLite (``EXPLAIN``, parameters bound to
   NULL) against the freshly migrated schema; see ``sqlcheck``.

A manifest in ``app/db/generated`` caches the work: an unchanged schema is not migrated or
generated again, and only new or changed statements are compiled. ``--check`` compares and never
writes. A run with nothing to do does not even import SQLAlchemy or Alembic.
"""


class BuildError(Exception):
    """A problem that stops the build; the message says what to change."""
