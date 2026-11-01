"""Discussion forum tables (board scope).

Role prompts are snapshotted per participant so later role-template edits never rewrite history.

Revision ID: 0004_discussions
Revises: 0003_card_assignment_attachments
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_discussions"
down_revision: str | None = "0003_card_assignment_attachments"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

STATUSES = (
    "open",
    "discussing",
    "consensus_proposed",
    "human_review",
    "approved",
    "vetoed",
    "rework_requested",
    "unresolved",
    "cancelled",
)


def upgrade() -> None:
    op.create_table(
        "discussion_threads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("card_id", sa.String(), sa.ForeignKey("cards.id", ondelete="CASCADE")),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("goal", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_by_actor_id", sa.String(), nullable=False),
        sa.Column("created_by_type", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("origin_comment_id", sa.String(), nullable=True),
        sa.Column("escalation_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("last_activity_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "status IN ({})".format(",".join(f"'{value}'" for value in STATUSES)),
            name="ck_discussion_status",
        ),
        sa.CheckConstraint(
            "mode IN ('manual','roundtable','autonomous')", name="ck_discussion_mode"
        ),
    )
    op.create_index("ix_discussion_threads_card", "discussion_threads", ["card_id"])
    op.create_index("ix_discussion_threads_status", "discussion_threads", ["status"])

    op.create_table(
        "discussion_participants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "discussion_id",
            sa.String(),
            sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("participant_id", sa.String(), nullable=False),
        sa.Column("participant_type", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("role_template_id", sa.String(), nullable=True),
        sa.Column("role_template_name", sa.String(), nullable=True),
        sa.Column("role_template_updated_at", sa.String(), nullable=True),
        sa.Column("role_source", sa.String(), nullable=False, server_default="template"),
        sa.Column("system_prompt", sa.String(), nullable=False),
        sa.Column("system_prompt_sha256", sa.String(), nullable=False),
        sa.Column("snapshot_at", sa.String(), nullable=False),
        sa.Column("joined_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_discussion_participants_thread", "discussion_participants", ["discussion_id"]
    )

    op.create_table(
        "discussion_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "discussion_id",
            sa.String(),
            sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_message_id", sa.String(), nullable=True),
        sa.Column("author_actor_id", sa.String(), nullable=False),
        sa.Column("author_type", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=False),
        sa.Column("author_role", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="posted"),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_discussion_messages_thread", "discussion_messages", ["discussion_id", "created_at"]
    )

    op.create_table(
        "discussion_votes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "discussion_id",
            sa.String(),
            sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("participant_id", sa.String(), nullable=False),
        sa.Column("position", sa.String(), nullable=False),
        sa.Column("justification", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_discussion_votes_thread", "discussion_votes", ["discussion_id"])

    op.create_table(
        "discussion_outcomes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "discussion_id",
            sa.String(),
            sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.String(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_discussion_outcomes_thread", "discussion_outcomes", ["discussion_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
