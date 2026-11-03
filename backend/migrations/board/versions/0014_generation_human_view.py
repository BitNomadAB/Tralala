"""A generation run may write the analysis a person reads (``analysis_human``).

The human view of an analysis was a template filled from the structure. A board agent now writes it
for a project manager from the exact technical analysis revision, and that is a run of its own: it
has an agent, a model, a process tree and a result that is checked before it is stored. The run's
purpose names it, so ``ck_runs_purpose`` admits ``analysis_human`` beside the three it had.

SQLite cannot alter a CHECK constraint in place, so the table is rebuilt through
``batch_alter_table``. Its shape is given explicitly (``copy_from``), as revision 0002 of the
registry does, so the rebuild does not depend on SQLite reflecting CHECK constraints. The two
indexes are dropped before and created after the rebuild for the same reason:
``ux_loop_runs_active`` is partial (one queued or running run per Loop and purpose), and a reflected
copy that lost its ``WHERE`` would refuse every second run of a purpose. Rows keep every value;
the columns keep their order, so the generated row is unchanged.

Revision ID: 0014_generation_human_view
Revises: 0013_generation_run_trace
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_generation_human_view"
down_revision: str | None = "0013_generation_run_trace"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# The table as revisions 0008, 0010 and 0013 left it.
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
    sa.CheckConstraint("purpose IN ('analysis','roadmap','qa')", name="ck_runs_purpose"),
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
            "ck_runs_purpose", "purpose IN ('analysis','analysis_human','roadmap','qa')"
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
