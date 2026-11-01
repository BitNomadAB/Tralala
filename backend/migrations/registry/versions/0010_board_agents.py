"""A board selects the agents that work on it.

Agents are registry-level resources (identity, connection and credentials) just like repositories,
so board membership is a link table rather than a column: one agent can serve several boards and a
board can list several. A board without a selection keeps working — generation then falls back to
every enabled OpenAI-compatible agent.

Revision ID: 0010_board_agents
Revises: 0009_board_repository_links
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_board_agents"
down_revision: str | None = "0009_board_repository_links"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "board_agents",
        sa.Column("board_id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name="fk_board_agents_board", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_board_agents_agent", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_board_agents_agent", "board_agents", ["agent_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
