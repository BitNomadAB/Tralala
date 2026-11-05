"""Every Ticket carries a short summary of what it is about.

A worker that lists a board's Tickets reads one short summary per Ticket instead of every field, and
then reads the Ticket it chose. The RoadMap writes the summary of a planned Ticket
(``loop_plan_items.summary``, copied onto the published card); anyone who may edit a Ticket writes
or replaces it later.

``summary_source`` says who wrote it (``plan``, ``person`` or ``agent``; empty while there is
none). ``summary_basis_sha256`` is the hash of the title and description the summary was written
from, so a later edit of either marks the summary stale instead of silently keeping it.

Revision ID: 0016_ticket_summaries
Revises: 0015_loop_notes
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_ticket_summaries"
down_revision: str | None = "0015_loop_notes"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("summary", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "cards", sa.Column("summary_source", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "cards", sa.Column("summary_basis_sha256", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "loop_plan_items", sa.Column("summary", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
