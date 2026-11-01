"""Card assignment and ticket attachments.

Assignment is stored on the card (single primary assignee) with a denormalised display name so the
UI does not need a cross-database join. Attachments keep metadata in the board database and bytes on
disk under ``data/boards/{uuid}/attachments/{uuid}``; ``deleted_at`` marks a soft delete.

Revision ID: 0003_card_assignment_attachments
Revises: 0002_cards_completed_index
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_card_assignment_attachments"
down_revision: str | None = "0002_cards_completed_index"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMN: SQLite supports it natively, so the table (and its FTS5 triggers) is not
    # rebuilt.
    op.add_column("cards", sa.Column("assignee_actor_id", sa.String(), nullable=True))
    op.add_column("cards", sa.Column("assignee_type", sa.String(), nullable=True))
    op.add_column("cards", sa.Column("assignee_name", sa.String(), nullable=True))
    op.add_column("cards", sa.Column("assigned_at", sa.String(), nullable=True))
    op.add_column("cards", sa.Column("assigned_by_actor_id", sa.String(), nullable=True))

    op.create_index("ix_cards_assignee", "cards", ["assignee_actor_id"])

    op.create_table(
        "attachments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "card_id",
            sa.String(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("discussion_id", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("stored_filename", sa.String(), nullable=False, unique=True),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("uploaded_by_actor_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "card_id IS NOT NULL OR discussion_id IS NOT NULL",
            name="ck_attachments_context",
        ),
    )
    op.create_index("ix_attachments_card", "attachments", ["card_id"])
    op.create_index("ix_attachments_discussion", "attachments", ["discussion_id"])
    op.create_index("ix_attachments_message", "attachments", ["message_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
