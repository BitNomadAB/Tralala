"""Per-Loop agent preference per generation purpose.

A board lists the agents that may work on it (registry ``board_agents``); this table records which
of them a Loop should use by default for each purpose, so a person does not have to pick the same
agent on every run. ``agent_id`` is a registry id and carries no foreign key: a board database must
not depend on registry rows, and deleting an agent simply leaves a preference that no longer
resolves (the run then falls back to the board default).

Revision ID: 0009_loop_agent_preferences
Revises: 0008_loops
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_loop_agent_preferences"
down_revision: str | None = "0008_loops"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "loop_agent_preferences",
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("purpose", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_loop_agent_preferences_agent", "loop_agent_preferences", ["agent_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
