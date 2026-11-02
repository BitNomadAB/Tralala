"""Ownership for API tokens, so a person's agent access belongs to that person.

A token is still its own agent actor — that is what makes audit entries readable — but it now
records which account issued it. Ownership is what lets a member hold and manage their own
"interaction agent access", lets an administrator count and revoke it per user, and makes disabling
an account stop the agents acting on its behalf.

The column is nullable: tokens issued before this revision keep working and appear as
installation-wide access for an administrator.

Revision ID: 0013_credential_owner
Revises: 0012_user_invites
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_credential_owner"
down_revision: str | None = "0012_user_invites"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_credentials") as batch:
        batch.add_column(sa.Column("owner_actor_id", sa.String(), nullable=True))
    op.create_index(
        "ix_api_credentials_owner", "api_credentials", ["owner_actor_id", "created_at"]
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
