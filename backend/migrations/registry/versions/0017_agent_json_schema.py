"""Whether an agent's provider takes a JSON schema as the answer's format.

An OpenAI-compatible provider that supports ``response_format: {"type": "json_schema", ...}``
constrains the answer to the schema, so a generation needs no repair round for output that does
not parse. Not every provider takes it, and some refuse the request outright, so the connection
test finds out (``AgentService.test``) and records it here; a generation sends the schema only
when the flag is set, and asks once more without it when the provider refuses it after all.

A flag as the convention stores one: an INTEGER 0/1 with a named CHECK. Existing agents start at 0
and keep working as before until their connection is tested again.

Revision ID: 0017_agent_json_schema
Revises: 0016_agent_role_template_key
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_agent_json_schema"
down_revision: str | None = "0016_agent_role_template_key"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ADD COLUMN, not a rebuild: SQLite appends the column with its CHECK and holds the rows already
    # there, which all take the default, to the CHECK. Written out because Alembic's add_column
    # renders no column CHECK on SQLite (it would need a batch rebuild of ``agents`` for that).
    op.execute(
        "ALTER TABLE agents ADD COLUMN supports_json_schema INTEGER NOT NULL DEFAULT 0"
        " CONSTRAINT ck_agents_supports_json_schema CHECK (supports_json_schema IN (0, 1))"
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
