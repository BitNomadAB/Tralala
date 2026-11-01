"""Discussion run control: runs, rounds, budgets and duplicate guards.

Existing discussion tables gain plain columns so the released ``0004`` schema keeps working for
boards that are adopted later. Nothing on ``cards`` is touched, so the FTS5 triggers survive.

Revision ID: 0005_discussion_run_control
Revises: 0004_discussions
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_discussion_run_control"
down_revision: str | None = "0004_discussions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RUN_STATUSES = (
    "running",
    "paused",
    "stopped",
    "completed",
    "failed",
    "budget_exhausted",
    "no_progress",
)
ROUND_STATUSES = ("completed", "paused", "stopped", "failed", "budget_exhausted", "no_progress")


def _in_clause(values: Sequence[str]) -> str:
    return "({})".format(",".join(f"'{value}'" for value in values))


def upgrade() -> None:
    op.add_column(
        "discussion_threads",
        sa.Column("round_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "discussion_threads",
        sa.Column("run_state", sa.String(), nullable=False, server_default="idle"),
    )
    op.add_column(
        "discussion_threads",
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "discussion_threads",
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "discussion_messages",
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("discussion_messages", sa.Column("content_sha256", sa.String(), nullable=True))
    op.add_column(
        "discussion_votes",
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "discussion_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "discussion_id",
            sa.String(),
            sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("autonomy", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rounds_requested", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rounds_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_budget", sa.Integer(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_budget_seconds", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stop_reason", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_by_actor_id", sa.String(), nullable=False),
        sa.Column("started_by_type", sa.String(), nullable=False),
        sa.Column("started_by_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            f"status IN {_in_clause(RUN_STATUSES)}", name="ck_discussion_run_status"
        ),
    )
    op.create_index(
        "ix_discussion_runs_thread", "discussion_runs", ["discussion_id", "created_at"]
    )
    op.create_index("ix_discussion_runs_status", "discussion_runs", ["status"])

    op.create_table(
        "discussion_rounds",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "discussion_id",
            sa.String(),
            sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("discussion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            f"status IN {_in_clause(ROUND_STATUSES)}", name="ck_discussion_round_status"
        ),
    )
    op.create_index(
        "ix_discussion_rounds_run",
        "discussion_rounds",
        ["run_id", "round_number"],
        unique=True,
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
