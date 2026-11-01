"""Loop-based planning: Loop ownership, documents, approvals, plans, QA and history.

This revision is a structural redesign, not a rolling upgrade. A board database that already
contains lists or cards predates Loop ownership and cannot be converted in place; it must be
reset with the documented development reset command. Fresh databases reach this revision with
empty ``lists``/``cards`` tables, which is the supported path.

Revision ID: 0008_loops
Revises: 0007_comment_mentions
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_loops"
down_revision: str | None = "0007_comment_mentions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RESET_HINT = (
    "This development database predates Loop ownership and cannot be migrated in place. "
    "Run 'python -m app.dev_reset --confirm <data directory>' (backend directory) to reset it."
)


def _guard_populated_database() -> None:
    connection = op.get_bind()
    for table in ("lists", "cards"):
        count = connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one()
        if int(count) > 0:
            raise RuntimeError(f"{RESET_HINT} Found {count} row(s) in '{table}'.")


def upgrade() -> None:
    _guard_populated_database()

    op.create_table(
        "board_loop_defaults",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("column_names_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_board_loop_defaults_singleton"),
    )

    op.create_table(
        "loops",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("goal", sa.String(), nullable=False, server_default=""),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("key_prefix", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column(
            "stage",
            sa.String(),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_plan_id", sa.String(), nullable=True),
        sa.Column("analysis_approval_id", sa.String(), nullable=True),
        sa.Column("roadmap_approval_id", sa.String(), nullable=True),
        sa.Column("implementation_approval_id", sa.String(), nullable=True),
        sa.Column("qa_approval_id", sa.String(), nullable=True),
        sa.Column("active_qa_cycle_id", sa.String(), nullable=True),
        sa.Column("history_id", sa.String(), nullable=True),
        sa.Column("created_by_actor_id", sa.String(), nullable=False),
        sa.Column("created_by_actor_type", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String(), nullable=True),
        sa.Column("cancelled_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "stage IN ('draft','analysis_review','planning','roadmap_review','ready',"
            "'in_progress','replanning','awaiting_qa','completed','cancelled')",
            name="ck_loops_stage",
        ),
    )
    op.create_index("ux_loops_sequence", "loops", ["sequence"], unique=True)
    op.create_index("ux_loops_key", "loops", ["key"], unique=True)
    op.create_index("idx_loops_stage", "loops", ["stage", "updated_at"])

    op.create_table(
        "loop_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("source_info_revision_id", sa.String(), nullable=True),
        sa.Column("source_analysis_ai_revision_id", sa.String(), nullable=True),
        sa.Column("source_analysis_revision_id", sa.String(), nullable=True),
        sa.Column("source_roadmap_ai_revision_id", sa.String(), nullable=True),
        sa.Column("generation_run_id", sa.String(), nullable=True),
        sa.Column("author_actor_id", sa.String(), nullable=False),
        sa.Column("author_actor_type", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=False),
        sa.Column("provenance_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("is_current", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_approved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('info','analysis_ai','analysis','roadmap_ai','roadmap')",
            name="ck_loop_documents_kind",
        ),
        sa.CheckConstraint(
            "status IN ('draft','ready_for_review','approved','changes_requested','stale')",
            name="ck_loop_documents_status",
        ),
    )
    op.create_index(
        "ux_loop_documents_revision",
        "loop_documents",
        ["loop_id", "kind", "revision_number"],
        unique=True,
    )
    op.create_index(
        "ux_loop_documents_current",
        "loop_documents",
        ["loop_id", "kind"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_index(
        "ux_loop_documents_approved",
        "loop_documents",
        ["loop_id", "kind"],
        unique=True,
        sqlite_where=sa.text("is_approved = 1"),
    )

    op.create_table(
        "loop_approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reviewer_actor_id", sa.String(), nullable=False),
        sa.Column("reviewer_name", sa.String(), nullable=False),
        sa.Column("feedback", sa.String(), nullable=False, server_default=""),
        sa.Column("revisions_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("source_hashes_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("loop_version", sa.Integer(), nullable=False),
        sa.Column("superseded_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "scope IN ('analysis','roadmap','implementation','qa')",
            name="ck_loop_approvals_scope",
        ),
        sa.CheckConstraint(
            "decision IN ('approved','changes_requested')", name="ck_loop_approvals_decision"
        ),
    )
    op.create_index(
        "idx_loop_approvals_loop", "loop_approvals", ["loop_id", "scope", "created_at"]
    )

    op.create_table(
        "loop_generation_runs",
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
        sa.CheckConstraint("purpose IN ('analysis','roadmap','qa')", name="ck_runs_purpose"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_runs_status",
        ),
    )
    op.create_index("idx_loop_runs_loop", "loop_generation_runs", ["loop_id", "created_at"])
    op.create_index(
        "ux_loop_runs_active",
        "loop_generation_runs",
        ["loop_id", "purpose"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued','running')"),
    )

    op.create_table(
        "loop_plans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("roadmap_ai_revision_id", sa.String(), nullable=False),
        sa.Column("roadmap_revision_id", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=True),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("activated_at", sa.String(), nullable=True),
        sa.Column("superseded_at", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('draft','active','superseded')", name="ck_plans_status"),
    )
    op.create_index("ux_loop_plans_revision", "loop_plans", ["loop_id", "revision_number"],
    unique=True)
    op.create_index(
        "ux_loop_plans_active",
        "loop_plans",
        ["loop_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "loop_phases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False, server_default=""),
        sa.Column("entry_conditions_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("exit_conditions_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("is_qa_phase", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ux_loop_phases_number", "loop_phases", ["plan_id", "number"], unique=True)
    op.create_index("idx_loop_phases_loop", "loop_phases", ["loop_id", "number"])

    op.create_table(
        "loop_plan_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("phase_id", sa.String(), nullable=False),
        sa.Column("phase_number", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("ticket_sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False, server_default=""),
        sa.Column("instructions", sa.String(), nullable=False, server_default=""),
        sa.Column("required_actor", sa.String(), nullable=False, server_default="any"),
        sa.Column("execution_mode", sa.String(), nullable=False, server_default="normal"),
        sa.Column("priority", sa.String(), nullable=False, server_default="none"),
        sa.Column("acceptance_criteria_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("expected_evidence_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("human_action_reason", sa.String(), nullable=False, server_default=""),
        sa.Column("human_instructions", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "required_actor IN ('any','human')", name="ck_plan_items_required_actor"
        ),
        sa.CheckConstraint(
            "execution_mode IN ('normal','pre_phase_gate')", name="ck_plan_items_execution_mode"
        ),
    )
    op.create_index("ux_loop_plan_items_key", "loop_plan_items", ["key"], unique=True)
    op.create_index(
        "ux_loop_plan_items_sequence",
        "loop_plan_items",
        ["phase_id", "ticket_sequence"],
        unique=True,
    )
    op.create_index("idx_loop_plan_items_loop", "loop_plan_items", ["loop_id", "phase_number"])

    op.create_table(
        "loop_dependencies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('phase','ticket')", name="ck_dependencies_source_type"
        ),
        sa.CheckConstraint(
            "target_type IN ('phase','ticket')", name="ck_dependencies_target_type"
        ),
    )
    op.create_index(
        "ux_loop_dependencies_edge",
        "loop_dependencies",
        ["plan_id", "source_type", "source_id", "target_type", "target_id"],
        unique=True,
    )

    op.create_table(
        "loop_qa_cycles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "loop_id",
            sa.String(),
            sa.ForeignKey("loops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("card_id", sa.String(), nullable=True),
        sa.Column("ai_instructions_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("human_instructions_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("instruction_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivery_baseline", sa.String(), nullable=False, server_default=""),
        sa.Column("generation_run_id", sa.String(), nullable=True),
        sa.Column("attestation_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("decided_at", sa.String(), nullable=True),
        sa.Column("decided_by_actor_id", sa.String(), nullable=True),
        sa.Column("decision_note", sa.String(), nullable=False, server_default=""),
        sa.CheckConstraint(
            "status IN ('pending','instructions_ready','in_progress','accepted',"
            "'rejected','superseded')",
            name="ck_qa_cycles_status",
        ),
    )
    op.create_index(
        "ux_loop_qa_cycle_number", "loop_qa_cycles", ["loop_id", "cycle_number"], unique=True
    )
    op.create_index(
        "ux_loop_qa_active",
        "loop_qa_cycles",
        ["loop_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending','instructions_ready','in_progress')"),
    )

    op.create_table(
        "loop_qa_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "cycle_id",
            sa.String(),
            sa.ForeignKey("loop_qa_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False, server_default=""),
        sa.Column("evidence", sa.String(), nullable=False, server_default=""),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor_name", sa.String(), nullable=False),
        sa.Column("tested_baseline", sa.String(), nullable=False, server_default=""),
        sa.Column("instruction_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disposition_approved_by_actor_id", sa.String(), nullable=True),
        sa.Column("disposition_note", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "status IN ('passed','failed','blocked','not_run','not_applicable')",
            name="ck_qa_results_status",
        ),
    )
    op.create_index("idx_loop_qa_results_cycle", "loop_qa_results", ["cycle_id", "scenario_id"])

    op.create_table(
        "loop_history",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("history_schema_version", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("conformance", sa.String(), nullable=False, server_default="native"),
        sa.Column("board_id", sa.String(), nullable=False),
        sa.Column("loop_id", sa.String(), nullable=True),
        sa.Column("loop_key", sa.String(), nullable=True),
        sa.Column("loop_name", sa.String(), nullable=False),
        sa.Column("qa_status", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("envelope_json", sa.String(), nullable=False),
        sa.Column("search_text", sa.String(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("imported_at", sa.String(), nullable=True),
        sa.Column("imported_by_actor_id", sa.String(), nullable=True),
        sa.Column("source_project", sa.String(), nullable=True),
        sa.Column("source_reference", sa.String(), nullable=True),
        sa.Column("source_format", sa.String(), nullable=True),
        sa.Column("source_version", sa.String(), nullable=True),
        sa.Column("validation_warnings_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('native','imported_legacy')", name="ck_history_source_kind"
        ),
    )
    op.create_index(
        "ux_loop_history_native",
        "loop_history",
        ["board_id", "loop_id"],
        unique=True,
        sqlite_where=sa.text("source_kind = 'native'"),
    )
    op.create_index("idx_loop_history_completed", "loop_history", ["completed_at", "id"])
    op.create_index("idx_loop_history_kind", "loop_history", ["source_kind", "created_at"])

    op.create_table(
        "loop_history_artifacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "history_id",
            sa.String(),
            sa.ForeignKey("loop_history.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("inclusion", sa.String(), nullable=False, server_default="included"),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.CheckConstraint(
            "inclusion IN ('included','excluded')", name="ck_history_artifacts_inclusion"
        ),
    )
    op.create_index("idx_loop_history_artifacts", "loop_history_artifacts", ["history_id"])

    with op.batch_alter_table("lists", recreate="always") as batch:
        batch.add_column(sa.Column("loop_id", sa.String(), nullable=False))
        batch.create_foreign_key(
            "fk_lists_loop", "loops", ["loop_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_unique_constraint("ux_lists_id_loop", ["id", "loop_id"])
    op.create_index("idx_lists_loop_position", "lists", ["loop_id", "position", "id"])

    with op.batch_alter_table("cards", recreate="always") as batch:
        batch.add_column(sa.Column("loop_id", sa.String(), nullable=False))
        batch.add_column(sa.Column("phase_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("plan_item_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("ticket_key", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("kind", sa.String(), nullable=False, server_default="manual")
        )
        batch.add_column(
            sa.Column("required_actor", sa.String(), nullable=False, server_default="any")
        )
        batch.add_column(
            sa.Column("execution_mode", sa.String(), nullable=False, server_default="normal")
        )
        batch.add_column(
            sa.Column("human_action_reason", sa.String(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("human_instructions", sa.String(), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("human_confirmed_at", sa.String(), nullable=True))
        batch.add_column(sa.Column("human_confirmed_by_actor_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("plan_revision_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_cards_loop", "loops", ["loop_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_cards_list_loop",
            "lists",
            ["list_id", "loop_id"],
            ["id", "loop_id"],
            ondelete="CASCADE",
        )
    op.create_index("idx_cards_loop", "cards", ["loop_id", "list_id", "position"])
    op.create_index(
        "ux_cards_ticket_key", "cards", ["ticket_key"], unique=True, sqlite_where=sa.text(
            "ticket_key IS NOT NULL"
        )
    )
    op.create_index("idx_cards_plan_item", "cards", ["plan_item_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
