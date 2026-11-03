"""A generation run says which step it is on.

An analysis run is not one opaque wait: it reads the Loop's Info, fetches the board's repositories
and then calls the provider. The person watching the document dialog needs to see which of those is
happening, and — when one fails — which one failed. The column holds that step; it is nullable
because runs recorded before this revision simply have no phase.

Revision ID: 0010_generation_run_phase
Revises: 0009_loop_agent_preferences
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_generation_run_phase"
down_revision: str | None = "0009_loop_agent_preferences"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("loop_generation_runs") as batch:
        batch.add_column(sa.Column("phase", sa.String(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
