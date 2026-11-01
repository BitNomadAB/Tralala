"""Index completed cards for completion filters and reports.

Revision ID: 0002_cards_completed_index
Revises: 0001_board_initial
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_cards_completed_index"
down_revision: str | None = "0001_board_initial"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_cards_completed_at", "cards", ["completed_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
