"""Cached per-board counters for the dashboard.

The dashboard shows how many Loops, lists and Tickets each board holds, but those numbers live
inside that board's own database. Measuring them for the whole list therefore means opening every
board file, which does not scale to an installation with many boards on a slow disk.

The numbers are still measured from the board itself — the registry never becomes the source of
truth for board content — but the result is kept here and dropped whenever the board is written to,
with a short time limit as a backstop. A row is optional: a board without one is simply measured on
the next list.

Revision ID: 0014_board_stats
Revises: 0013_credential_owner
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_board_stats"
down_revision: str | None = "0013_credential_owner"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "board_stats",
        sa.Column("board_id", sa.String(), primary_key=True),
        sa.Column("loop_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("list_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("card_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("measured_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name="fk_board_stats_board", ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
