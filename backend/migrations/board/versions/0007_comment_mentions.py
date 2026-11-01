"""Agent mentions in ticket comments: one durable job per mention and a card event log.

Revision ID: 0007_comment_mentions
Revises: 0006_discussion_events
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_comment_mentions"
down_revision: str | None = "0006_discussion_events"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comment_mention_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "card_id",
            sa.String(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "comment_id",
            sa.String(),
            sa.ForeignKey("comments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "response_comment_id",
            sa.String(),
            sa.ForeignKey("comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role_snapshot_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_by_actor_id", sa.String(), nullable=False),
        sa.Column("requested_by_type", sa.String(), nullable=False),
        sa.Column("requested_by_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_comment_mentions_card", "comment_mention_jobs", ["card_id", "created_at"]
    )
    op.create_index(
        "uq_comment_mentions_once",
        "comment_mention_jobs",
        ["comment_id", "agent_id"],
        unique=True,
    )
    op.create_table(
        "card_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(), nullable=False, unique=True),
        sa.Column(
            "card_id",
            sa.String(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("actor_type", sa.String(), nullable=True),
        sa.Column("actor_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_card_events_card", "card_events", ["card_id", "seq"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
