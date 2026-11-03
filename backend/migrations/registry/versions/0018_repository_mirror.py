"""A repository can be read through a Tralala-managed Git mirror as well as the GitHub API.

The provider ``git_https`` reads any HTTPS Git host the operator allows: one shallow bare mirror per
repository under ``<data>/repos/<repository_id>/``, fetched before every run. The row keeps what an
operator needs to see of it:

- ``default_branch``: the branch the remote's HEAD names (``git ls-remote --symref``), stored by the
  access check and by a fetch without an explicit branch;
- ``last_sha`` and ``fetched_at``: the commit the last good fetch brought and when;
- ``mirror_bytes``: the mirror's size after its hygiene;
- ``mirror_error``: why the last fetch failed (a code, never the host's own words), or NULL.

All five are NULL for a GitHub repository and for a mirror that has never been fetched.

SQLite cannot alter a CHECK constraint in place, so the table is rebuilt through
``batch_alter_table`` to let ``ck_repositories_provider`` accept ``git_https``. The runner applies
revisions with foreign keys off, so the rebuild leaves the board links in ``board_repositories``
alone; existing rows keep their values and their provider.

Revision ID: 0018_repository_mirror
Revises: 0017_agent_json_schema
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_repository_mirror"
down_revision: str | None = "0017_agent_json_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# The table as revisions 0008 and 0009 left it, so batch mode does not depend on SQLite constraint
# reflection (as in 0002). It is not STRICT, and the rebuild keeps it that way.
repositories_before = sa.Table(
    "repositories",
    sa.MetaData(),
    sa.Column("id", sa.String(), primary_key=True),
    sa.Column("name", sa.String(), nullable=False),
    sa.Column("provider", sa.String(), nullable=False),
    sa.Column("url", sa.String(), nullable=False),
    sa.Column("branch", sa.String(), nullable=True),
    sa.Column("token_ciphertext", sa.String(), nullable=True),
    sa.Column("token_hint", sa.String(), nullable=True),
    sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("last_checked_at", sa.String(), nullable=True),
    sa.Column("last_check_status", sa.String(), nullable=True),
    sa.Column("last_check_detail", sa.String(), nullable=True),
    sa.Column("created_at", sa.String(), nullable=False),
    sa.Column("updated_at", sa.String(), nullable=False),
    sa.CheckConstraint("provider IN ('github')", name="ck_repositories_provider"),
)


def upgrade() -> None:
    with op.batch_alter_table("repositories", copy_from=repositories_before) as batch:
        batch.drop_constraint("ck_repositories_provider", type_="check")
        batch.create_check_constraint(
            "ck_repositories_provider", "provider IN ('github', 'git_https')"
        )
        batch.add_column(sa.Column("default_branch", sa.Text(), nullable=True))
        batch.add_column(sa.Column("last_sha", sa.Text(), nullable=True))
        batch.add_column(sa.Column("fetched_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("mirror_bytes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("mirror_error", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
