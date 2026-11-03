"""The foreign key from an agent to its role template.

``agents.role_template_id`` named a role template without a constraint. ``agents`` is referenced by
``board_agents`` (ON DELETE CASCADE), so rebuilding it while foreign keys were enforced would have
deleted every board's agent assignments when the old copy was dropped. The runner now applies a
revision the way SQLite's table-rebuild procedure says: foreign keys off for the transaction and
``PRAGMA foreign_key_check`` before the COMMIT (``app/storage/schema/runner.py``).

A template that is gone is settled first: the reference is optional (an agent may carry its own
prompt), and ``AgentService`` already clears it when a template is deleted, so a missing template
becomes NULL. Nothing is deleted.

Revision ID: 0016_agent_role_template_key
Revises: 0015_registry_foreign_keys
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_agent_role_template_key"
down_revision: str | None = "0015_registry_foreign_keys"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE agents SET role_template_id = NULL WHERE role_template_id IS NOT NULL"
        " AND role_template_id NOT IN (SELECT id FROM role_templates)"
    )
    # SET NULL: deleting a template leaves its agents in place without one, as AgentService does.
    # ix_agents_role_template_id already starts with the column. SQLAlchemy does not reflect a
    # column's collation from SQLite, so the rebuild is handed the name column as 0004 declared it:
    # without it the copy would compare agent names case-sensitively.
    with op.batch_alter_table(
        "agents",
        recreate="always",
        reflect_args=[sa.Column("name", sa.String(collation="NOCASE"), nullable=False)],
    ) as batch:
        batch.create_foreign_key(
            "fk_agents_role_template",
            "role_templates",
            ["role_template_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
