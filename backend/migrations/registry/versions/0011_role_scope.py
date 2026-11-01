"""Role templates gain a scope: a board profile or an organisation-wide one.

Board profiles answer inside one board and may be selected for it. Organisation profiles
(Coordinator, Architect) work across the whole installation, so they are deliberately not offered
as board agents. Existing templates are board profiles, which is what they were.

Revision ID: 0011_role_scope
Revises: 0010_board_agents
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_role_scope"
down_revision: str | None = "0010_board_agents"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("role_templates") as batch:
        batch.add_column(
            sa.Column("scope", sa.String(), nullable=False, server_default="board")
        )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
