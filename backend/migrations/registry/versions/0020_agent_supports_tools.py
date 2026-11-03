"""Whether an agent's provider answers tool calls.

An OpenAI-compatible provider that takes ``tools`` lets the model ask for something and get it back
in the same conversation: a generation run can then give the model read-only tools over the run's
repository commit instead of one fixed snapshot. Not every provider or model takes tools, and some
refuse the request outright, so the connection test finds out (``AgentService.test``: one tiny call
with one dummy tool) and records it here; a run offers tools only when the flag is set.

A flag as the convention stores one: an INTEGER 0/1 with a named CHECK. Existing agents start at 0
and keep working as before until their connection is tested again.

Revision ID: 0020_agent_supports_tools
Revises: 0019_board_repository_paths
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020_agent_supports_tools"
down_revision: str | None = "0019_board_repository_paths"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ADD COLUMN, not a rebuild: SQLite appends the column with its CHECK and holds the rows already
    # there, which all take the default, to the CHECK. Written out because Alembic's add_column
    # renders no column CHECK on SQLite (it would need a batch rebuild of ``agents`` for that).
    op.execute(
        "ALTER TABLE agents ADD COLUMN supports_tools INTEGER NOT NULL DEFAULT 0"
        " CONSTRAINT ck_agents_supports_tools CHECK (supports_tools IN (0, 1))"
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
