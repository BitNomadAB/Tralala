"""Repositories become a registry-level list, each assigned to one board.

Revision 0007 modelled one repository per board. A board may own several repositories (an app and
its infrastructure, for example), and a repository is created first and then assigned, so the table
is rebuilt with its own id, a name and a nullable board assignment. Existing rows are preserved and
keep their credential.

Revision ID: 0008_repositories_and_board_assignment
Revises: 0007_board_repositories
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0008_repositories_and_board_assignment"
down_revision: str | None = "0007_board_repositories"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repositories_new",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=True),
        sa.Column("board_id", sa.String(), nullable=True),
        sa.Column("token_ciphertext", sa.String(), nullable=True),
        sa.Column("token_hint", sa.String(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_checked_at", sa.String(), nullable=True),
        sa.Column("last_check_status", sa.String(), nullable=True),
        sa.Column("last_check_detail", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name="fk_repositories_board", ondelete="SET NULL"
        ),
        sa.CheckConstraint("provider IN ('github')", name="ck_repositories_provider"),
    )

    connection = op.get_bind()
    existing = connection.execute(sa.text("SELECT * FROM repositories")).mappings().all()
    for row in existing:
        connection.execute(
            sa.text(
                "INSERT INTO repositories_new (id, name, provider, url, branch, board_id,"
                " token_ciphertext, token_hint, enabled, last_checked_at, last_check_status,"
                " last_check_detail, created_at, updated_at)"
                " VALUES (:id, :name, :provider, :url, :branch, :board, :token, :hint, :enabled,"
                " :checked_at, :check_status, :check_detail, :created_at, :updated_at)"
            ),
            {
                "id": str(uuid4()),
                "name": row["url"].rstrip("/").rsplit("/", 1)[-1] or row["url"],
                "provider": row["provider"],
                "url": row["url"],
                "branch": row["branch"],
                "board": row["board_id"],
                "token": row["token_ciphertext"],
                "hint": row["token_hint"],
                "enabled": row["enabled"],
                "checked_at": row["last_checked_at"],
                "check_status": row["last_check_status"],
                "check_detail": row["last_check_detail"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    op.drop_table("repositories")
    op.rename_table("repositories_new", "repositories")
    op.create_index(
        "ux_repositories_board_url", "repositories", ["board_id", "url"], unique=True
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
