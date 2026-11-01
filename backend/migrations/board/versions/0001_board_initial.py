"""Board baseline: metadata, lists, cards, labels, checklists, comments and activity.

Revision ID: 0001_board_initial
Revises:
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_board_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "board_metadata",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
    )

    op.create_table(
        "lists",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String(), nullable=True),
    )
    op.create_index("idx_lists_position", "lists", ["position", "id"])

    op.create_table(
        "cards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "list_id",
            sa.String(),
            sa.ForeignKey("lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False, server_default="none"),
        sa.Column("due_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "priority IN ('none','low','medium','high','urgent')",
            name="ck_cards_priority",
        ),
    )
    op.create_index("idx_cards_list_position", "cards", ["list_id", "position", "id"])
    op.create_index("idx_cards_updated_at", "cards", ["updated_at"])
    op.create_index("idx_cards_archived_at", "cards", ["archived_at"])
    op.create_index("idx_cards_priority", "cards", ["priority"])
    op.create_index("idx_cards_due_at", "cards", ["due_at"])

    op.create_table(
        "labels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("color", sa.String(), nullable=False),
    )

    op.create_table(
        "card_labels",
        sa.Column(
            "card_id",
            sa.String(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "label_id",
            sa.String(),
            sa.ForeignKey("labels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "checklists",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "card_id",
            sa.String(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index("idx_checklists_card", "checklists", ["card_id", "position"])

    op.create_table(
        "checklist_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "checklist_id",
            sa.String(),
            sa.ForeignKey("checklists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index(
        "idx_checklist_items_checklist", "checklist_items", ["checklist_id", "position"]
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "card_id",
            sa.String(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("idx_comments_card", "comments", ["card_id", "created_at"])

    op.create_table(
        "activity_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.Column("changes_json", sa.String(), nullable=False, server_default="{}"),
    )
    op.create_index("idx_activity_timestamp", "activity_log", ["timestamp"])
    op.create_index("idx_activity_entity", "activity_log", ["entity_type", "entity_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("actor_id", "idempotency_key"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
