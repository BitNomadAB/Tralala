"""Per-account appearance preferences.

Revision ID: 0006_user_preferences
Revises: 0005_accounts_and_sessions
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_user_preferences"
down_revision: str | None = "0005_accounts_and_sessions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_credentials", sa.Column("theme_mode", sa.String(), nullable=True))
    op.add_column("user_credentials", sa.Column("theme_kit", sa.String(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
