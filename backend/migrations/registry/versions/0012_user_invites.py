"""One-time enrolment links, so an administrator never has to know a user password.

An administrator creates the account, the server issues a token that is stored hashed, and the
administrator hands the link over through whatever channel the two already use. The link is single
use and expires; using it sets the password and signs the person in. No mail server is involved,
which is the point: the installation stays small and e-mail infrastructure never becomes a
dependency.

Revision ID: 0012_user_invites
Revises: 0011_role_scope
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_user_invites"
down_revision: str | None = "0011_role_scope"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_invites",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.String(),
            sa.ForeignKey("actors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_by_actor_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("used_at", sa.String(), nullable=True),
    )
    op.create_index("ux_user_invites_token", "user_invites", ["token_hash"], unique=True)
    op.create_index("ix_user_invites_actor", "user_invites", ["actor_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
