"""Board-level repository reference and its sealed read-only credential.

The credential belongs to the registry rather than to the board database, because a board export
streams the board file and must never carry a secret out of the installation.

Revision ID: 0007_board_repositories
Revises: 0006_user_preferences
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_board_repositories"
down_revision: str | None = "0006_user_preferences"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("board_id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=True),
        sa.Column("token_ciphertext", sa.String(), nullable=True),
        sa.Column("token_hint", sa.String(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_checked_at", sa.String(), nullable=True),
        sa.Column("last_check_status", sa.String(), nullable=True),
        sa.Column("last_check_detail", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name="fk_repositories_board", ondelete="CASCADE"
        ),
        sa.CheckConstraint("provider IN ('github')", name="ck_repositories_provider"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
