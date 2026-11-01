"""Accounts and server-side sessions.

Revision ID: 0005_accounts_and_sessions
Revises: 0004_agent_foundation
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_accounts_and_sessions"
down_revision: str | None = "0004_agent_foundation"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_credentials",
        sa.Column("role", sa.String(), nullable=False, server_default="admin"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column(
            "actor_id",
            sa.String(),
            sa.ForeignKey("actors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.String(), nullable=True),
    )
    op.create_index("ix_sessions_actor", "sessions", ["actor_id"])
    op.create_index("ix_sessions_expiry", "sessions", ["expires_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
