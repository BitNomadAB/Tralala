"""A board's link to a repository can steer which files a run's snapshot reads.

The snapshot of a repository keeps the files an analysis asks for first (the README, the rules, the
documentation, the configuration) and stops at its caps, so a Loop about one part of a large
repository may never see that part. Two globs lists on the link let the board say where to look:

- ``focus_paths``: when not empty, only a file one of these globs matches is read;
- ``exclude_paths``: a file one of these globs matches is never read.

Both are JSON text holding an array of strings, ``'[]'`` when the board has said nothing, so every
existing link keeps reading the whole repository. The globs are validated where a request enters
(``schemas/boards.py``) and matched in ``services/repo_snapshot.py``.

``ADD COLUMN``, not a rebuild: SQLite appends a NOT NULL column with its default and gives every row
already there that default.

Revision ID: 0019_board_repository_paths
Revises: 0018_repository_mirror
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_board_repository_paths"
down_revision: str | None = "0018_repository_mirror"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "board_repositories",
        sa.Column("focus_paths", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "board_repositories",
        sa.Column("exclude_paths", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
