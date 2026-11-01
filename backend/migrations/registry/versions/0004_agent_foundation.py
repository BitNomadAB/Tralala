"""Role templates and AI agent configurations.

Role templates are the central, reusable role definition. Agents reference a template (optionally
overriding the prompt); the prompt is snapshotted when a discussion starts, so editing a template
later never rewrites historical context.

Revision ID: 0004_agent_foundation
Revises: 0003_board_templates
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agent_foundation"
down_revision: str | None = "0003_board_templates"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "role_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(collation="NOCASE"), nullable=False, unique=True),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("system_prompt", sa.String(), nullable=False),
        sa.Column("default_system_prompt", sa.String(), nullable=False),
        sa.Column("built_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("builtin_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ux_role_templates_builtin_key",
        "role_templates",
        ["builtin_key"],
        unique=True,
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(collation="NOCASE"), nullable=False, unique=True),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("role_template_id", sa.String(), nullable=True),
        sa.Column("role_prompt_override", sa.String(), nullable=True),
        sa.Column("connection_type", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("api_key_ciphertext", sa.String(), nullable=True),
        sa.Column("api_key_hint", sa.String(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_test_status", sa.String(), nullable=True),
        sa.Column("last_test_message", sa.String(), nullable=True),
        sa.Column("last_tested_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "connection_type IN ('openai_compatible','a2a')",
            name="ck_agents_connection_type",
        ),
    )
    op.create_index("ix_agents_role_template_id", "agents", ["role_template_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
