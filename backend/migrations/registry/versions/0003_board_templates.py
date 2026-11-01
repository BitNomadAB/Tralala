"""Reusable board templates stored in the registry.

A template captures the board description, the initial list names and optional labels. Boards keep
their own SQLite database; only the template definition is global.

Revision ID: 0003_board_templates
Revises: 0002_board_migration_state
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_board_templates"
down_revision: str | None = "0002_board_migration_state"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "board_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(collation="NOCASE"), nullable=False, unique=True),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("lists_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("labels_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
