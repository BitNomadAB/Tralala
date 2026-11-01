"""Add the migration_failed board status and the recorded Alembic revision.

SQLite cannot alter a CHECK constraint in place, so the table is rebuilt through
``batch_alter_table``. Existing rows keep their values; ``schema_revision`` is filled by the
Migration Manager on the next board pass.

Revision ID: 0002_board_migration_state
Revises: 0001_registry_initial
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_board_migration_state"
down_revision: str | None = "0001_registry_initial"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Explicit old-shape table so batch mode does not depend on SQLite constraint reflection.
boards_before = sa.Table(
    "boards",
    sa.MetaData(),
    sa.Column("id", sa.String(), primary_key=True),
    sa.Column("name", sa.String(), nullable=False),
    sa.Column("description", sa.String(), nullable=False, server_default=""),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("created_at", sa.String(), nullable=False),
    sa.Column("updated_at", sa.String(), nullable=False),
    sa.Column("archived_at", sa.String(), nullable=True),
    sa.Column("schema_version", sa.Integer(), nullable=False),
    sa.CheckConstraint(
        "status IN ('active','archived','maintenance','error')",
        name="ck_boards_status",
    ),
)


def upgrade() -> None:
    with op.batch_alter_table("boards", copy_from=boards_before) as batch:
        batch.drop_constraint("ck_boards_status", type_="check")
        batch.create_check_constraint(
            "ck_boards_status",
            "status IN ('active','archived','maintenance','error','migration_failed')",
        )
        batch.add_column(sa.Column("schema_revision", sa.String(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
