"""Durable discussion event log for catch-up after a dropped stream.

Revision ID: 0006_discussion_events
Revises: 0005_discussion_run_control
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_discussion_events"
down_revision: str | None = "0005_discussion_run_control"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discussion_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(), nullable=False, unique=True),
        sa.Column(
            "discussion_id",
            sa.String(),
            sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("actor_type", sa.String(), nullable=True),
        sa.Column("actor_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_discussion_events_thread", "discussion_events", ["discussion_id", "seq"]
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
