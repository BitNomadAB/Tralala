"""A generation run may write the RoadMap's brief for people (``roadmap_human``).

The human view of a RoadMap becomes a brief a person reads (what happens in which order, their own
part, what could block it), written by a connected worker or by a board agent from the exact
technical RoadMap revision. The board agent's brief is a run of its own, as the analysis's is
(revision 0014), so ``ck_runs_purpose`` admits ``roadmap_human`` beside the four it had.

The table is rebuilt the way 0014 rebuilt it, for the same reasons: SQLite cannot alter a CHECK
constraint in place, the shape is given explicitly (``copy_from``) so the rebuild does not depend
on SQLite reflecting CHECK constraints, and both indexes are dropped before and created after the
rebuild so the partial ``ux_loop_runs_active`` keeps its ``WHERE``. Rows keep every value; the
columns keep their order, so the generated row is unchanged.

Revision ID: 0019_generation_roadmap_brief
Revises: 0016_ticket_summaries
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_generation_roadmap_brief"
down_revision: str | None = "0016_ticket_summaries"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# The table as revisions 0008, 0010, 0013 and 0014 left it.
runs_before = sa.Table(
    "loop_generation_runs",
    sa.MetaData(),
    sa.Column("id", sa.String(), primary_key=True),
    sa.Column(
        "loop_id",
        sa.String(),
        sa.ForeignKey("loops.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("purpose", sa.String(), nullable=False),
    sa.Column("status", sa.String(), nullable=False, server_default="queued"),
    sa.Column("input_json", sa.String(), nullable=False, server_default="{}"),
    sa.Column("input_hash", sa.String(), nullable=False),
    sa.Column("source_revisions_json", sa.String(), nullable=False, server_default="{}"),
    sa.Column("output_json", sa.String(), nullable=False, server_default="{}"),
    sa.Column("error_code", sa.String(), nullable=True),
    sa.Column("error_message", sa.String(), nullable=True),
    sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("agent_id", sa.String(), nullable=True),
    sa.Column("agent_name", sa.String(), nullable=True),
    sa.Column("model", sa.String(), nullable=True),
    sa.Column("role_snapshot_json", sa.String(), nullable=False, server_default="{}"),
    sa.Column("usage_json", sa.String(), nullable=False, server_default="{}"),
    sa.Column("created_by_actor_id", sa.String(), nullable=False),
    sa.Column("created_by_actor_type", sa.String(), nullable=False),
    sa.Column("created_at", sa.String(), nullable=False),
    sa.Column("started_at", sa.String(), nullable=True),
    sa.Column("finished_at", sa.String(), nullable=True),
    sa.Column("phase", sa.String(), nullable=True),
    sa.Column("trace_json", sa.Text(), nullable=False, server_default="[]"),
    sa.CheckConstraint(
        "purpose IN ('analysis','analysis_human','roadmap','qa')", name="ck_runs_purpose"
    ),
    sa.CheckConstraint(
        "status IN ('queued','running','completed','failed','cancelled')",
        name="ck_runs_status",
    ),
)


def upgrade() -> None:
    op.drop_index("ux_loop_runs_active", table_name="loop_generation_runs")
    op.drop_index("idx_loop_runs_loop", table_name="loop_generation_runs")
    with op.batch_alter_table(
        "loop_generation_runs", copy_from=runs_before, recreate="always"
    ) as batch:
        batch.drop_constraint("ck_runs_purpose", type_="check")
        batch.create_check_constraint(
            "ck_runs_purpose",
            "purpose IN ('analysis','analysis_human','roadmap','roadmap_human','qa')",
        )
    op.create_index("idx_loop_runs_loop", "loop_generation_runs", ["loop_id", "created_at"])
    op.create_index(
        "ux_loop_runs_active",
        "loop_generation_runs",
        ["loop_id", "purpose"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued','running')"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
