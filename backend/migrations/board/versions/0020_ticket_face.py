"""Every Ticket may carry a face for people.

The face is what a person reads of a Ticket by default: why it is needed, what happens if it is
skipped, up to three points for and against, and one to five concrete steps (the summary already
has its own column, revision 0016). The RoadMap writes the face of a planned Ticket
(``loop_plan_items.face``, copied onto the published card with the summary); a person edits it
later. It is stored as a JSON object; the empty string is no face, which is what every Ticket
written before this revision has.

Revision ID: 0020_ticket_face
Revises: 0019_generation_roadmap_brief
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_ticket_face"
down_revision: str | None = "0019_generation_roadmap_brief"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("face", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "loop_plan_items", sa.Column("face", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
