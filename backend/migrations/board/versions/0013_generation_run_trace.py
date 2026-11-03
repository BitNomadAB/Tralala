"""A generation run keeps the steps it took, so a person can read how its answer was made.

A run no longer makes one fixed call: the model reads the repository through tools, as often as it
needs, and an answer that breaks a rule is sent back for repair. The run panel shows those steps as
they happen and after the run, one plain-language line each: which file the model read, what it
searched for, which rule an answer broke, which limit the run reached. ``trace_json`` holds them as
a JSON array, written after every step. It never holds a file's content, only what was asked for
and how large the answer was.

``ADD COLUMN``, not a rebuild: SQLite appends a NOT NULL column with its default and gives every row
already there that default, so a run recorded before this revision has an empty trace.

Revision ID: 0013_generation_run_trace
Revises: 0012_referenced_table_keys
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_generation_run_trace"
down_revision: str | None = "0012_referenced_table_keys"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "loop_generation_runs",
        sa.Column("trace_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
