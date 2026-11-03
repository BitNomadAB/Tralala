"""A Loop keeps a log of notes: what belongs to the Loop and to no single Ticket.

A person or a worker writes a note on a Loop (a baseline, the gates that passed, a merge or a
deploy, what is still open); the Loop page lists them and finalizing a Loop carries them into its
history snapshot. Notes are appended, never edited.

``author_actor_id`` names an actor in the registry, which no constraint can reach (the rule the
comments table's ``actor_id`` follows). ``content_sha256`` lets a retried write find the note it
already made.

Revision ID: 0015_loop_notes
Revises: 0014_generation_human_view
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_loop_notes"
down_revision: str | None = "0014_generation_human_view"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "loop_notes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("loop_id", sa.Text(), nullable=False),
        sa.Column("author_actor_id", sa.Text(), nullable=False),
        sa.Column("author_actor_type", sa.Text(), nullable=False),
        sa.Column("author_name", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        # CASCADE: a Loop's notes are part of it and go with it.
        sa.ForeignKeyConstraint(
            ["loop_id"], ["loops.id"], name="fk_loop_notes_loop", ondelete="CASCADE"
        ),
        sa.CheckConstraint("length(content) <= 20000", name="ck_loop_notes_content_length"),
        sqlite_strict=True,
    )
    op.create_index("idx_loop_notes_loop", "loop_notes", ["loop_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
