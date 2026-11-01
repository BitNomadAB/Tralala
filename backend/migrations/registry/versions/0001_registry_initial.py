"""Registry baseline: boards, actors, credentials and idempotency records.

Revision ID: 0001_registry_initial
Revises:
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_registry_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "boards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','archived','maintenance','error')",
            name="ck_boards_status",
        ),
    )
    op.create_index("idx_boards_status", "boards", ["status"])

    op.create_table(
        "actors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("disabled_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "type IN ('user','agent','service')",
            name="ck_actors_type",
        ),
    )

    op.create_table(
        "user_credentials",
        sa.Column(
            "actor_id",
            sa.String(),
            sa.ForeignKey("actors.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )

    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.String(),
            sa.ForeignKey("actors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("scopes", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=True),
        sa.Column("last_used_at", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.String(), nullable=True),
    )
    op.create_index("idx_api_credentials_actor", "api_credentials", ["actor_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("actor_id", "idempotency_key"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
