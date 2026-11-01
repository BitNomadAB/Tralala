"""A board chooses which repositories it is about; a repository may serve several boards.

Revision 0008 put one board on each repository. A board can concern several repositories (an app
and its infrastructure), and the choice belongs where the board is created or edited, so the link
becomes its own table and the column on ``repositories`` goes away. Existing assignments are copied
first.

Revision ID: 0009_board_repository_links
Revises: 0008_repositories_and_board_assignment
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_board_repository_links"
down_revision: str | None = "0008_repositories_and_board_assignment"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    # Read the assignments before the rebuild: batch_alter_table recreates the table and the
    # drop of the old one would cascade into any link rows that already existed.
    pairs = connection.execute(
        sa.text("SELECT board_id, id, updated_at FROM repositories WHERE board_id IS NOT NULL")
    ).mappings().all()

    with op.batch_alter_table("repositories") as batch:
        batch.drop_index("ux_repositories_board_url")
        batch.drop_column("board_id")

    op.create_table(
        "board_repositories",
        sa.Column("board_id", sa.String(), primary_key=True),
        sa.Column("repository_id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name="fk_board_repositories_board", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name="fk_board_repositories_repository",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_board_repositories_repository", "board_repositories", ["repository_id"])

    for pair in pairs:
        connection.execute(
            sa.text(
                "INSERT INTO board_repositories (board_id, repository_id, created_at)"
                " VALUES (:board_id, :repository_id, :now)"
            ),
            {
                "board_id": pair["board_id"],
                "repository_id": pair["id"],
                "now": pair["updated_at"],
            },
        )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
