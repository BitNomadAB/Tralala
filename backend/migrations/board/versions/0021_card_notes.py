"""A person's notes on a Ticket: their own words beside the plan, never an agent's.

A person adds a note to a Ticket ("Extra notes about the Ticket"); the Ticket view shows it with its
author and time, and ``read_ticket`` hands it to a coding agent as ``person_notes``, a field of its
own, so the person's words reach the session that works the Ticket without being mistaken for the
plan. Only a person writes one, and only its author edits or deletes it; ``version`` is the
optimistic-concurrency token of an edit, as a card's is.

``author_actor_id`` names an actor in the registry, which no constraint can reach (the rule the
comments table's ``actor_id`` and ``loop_notes.author_actor_id`` follow); ``author_name`` is the
name at the time of writing, so a later rename does not rewrite who wrote the note.

Revision ID: 0021_card_notes
Revises: 0020_ticket_face
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_card_notes"
down_revision: str | None = "0020_ticket_face"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_notes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("author_actor_id", sa.Text(), nullable=False),
        sa.Column("author_name", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        # CASCADE: a note is part of its Ticket, as the Ticket's comments, checklists and
        # attachments are, and every one of them goes with the card. A card is archived, not
        # deleted, while its Loop is open; it is deleted only with the archived list that holds it
        # (cards.list_id CASCADE), and RESTRICT here would make that delete fail on the first note.
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name="fk_card_notes_card", ondelete="CASCADE"
        ),
        sa.CheckConstraint("length(text) BETWEEN 1 AND 4000", name="ck_card_notes_text_length"),
        sa.CheckConstraint("version >= 1", name="ck_card_notes_version"),
        sqlite_strict=True,
    )
    op.create_index("idx_card_notes_card", "card_notes", ["card_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
