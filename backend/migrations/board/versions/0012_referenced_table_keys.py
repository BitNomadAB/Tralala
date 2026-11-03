"""Foreign keys for the board references that wait for a runner with foreign keys off.

Revision ``0011`` could only rebuild tables that nothing references: the runner enforced foreign
keys inside its transaction, and dropping the old copy of a table fires the ON DELETE action of
every row that references it (and of every link a table holds to itself). The runner now applies a
revision the way SQLite's table-rebuild procedure says: foreign keys off for the transaction and
``PRAGMA foreign_key_check`` before the COMMIT (``app/storage/schema/runner.py``). This revision
gives the remaining references their keys: those in tables other tables reference (``cards``,
``discussion_threads``, ``loops``, ``loop_history``, ``loop_plans``, ``loop_qa_cycles``), the links
``discussion_messages`` and ``loop_documents`` hold to themselves, and the roadmap revisions of a
plan. Two references stay without a key; ``tools/dbgen/rules.py`` says why.

The Loop's rows all go with their Loop (``loop_id`` ON DELETE CASCADE), and between two rows the
Loop deletes together RESTRICT would make deleting the Loop depend on the order SQLite visits the
tables. So an optional link between them is SET NULL, and a row that is part of what it names
CASCADEs. RESTRICT is kept where the two rows are never deleted together: a Loop and its history.

A plan revision is stored before its two roadmap revisions are written and linked to them in the
same transaction (``register_draft``, then ``attach_revisions``), and the columns are NOT NULL, so
they hold ``''`` in between. Their keys are ``DEFERRABLE INITIALLY DEFERRED``: SQLite checks them at
the COMMIT, when the links are in place (https://www.sqlite.org/foreignkeys.html, section 4.2).

A reference whose row is gone is settled first, by what the column means: an optional one becomes
NULL; a plan's roadmap revision is NOT NULL and the application never deletes a document, so one
that is missing stops the upgrade with the plans to repair (the Migration Manager keeps its
pre-migration backup and marks the board ``migration_failed``). Nothing is deleted.

Rebuilding ``cards`` and ``loop_history`` drops their FTS triggers, which live outside the chain
(``app/storage/schema/fts.py``), and renumbers the rows the index points at; ``ensure_fts`` puts the
triggers back and rebuilds the index once the upgrade is committed.

Revision ID: 0012_referenced_table_keys
Revises: 0011_board_foreign_keys
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_referenced_table_keys"
down_revision: str | None = "0011_board_foreign_keys"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Optional references: a row that is gone becomes NULL.
_CLEAR = (
    "UPDATE cards SET phase_id = NULL WHERE phase_id IS NOT NULL"
    " AND phase_id NOT IN (SELECT id FROM loop_phases)",
    "UPDATE cards SET plan_item_id = NULL WHERE plan_item_id IS NOT NULL"
    " AND plan_item_id NOT IN (SELECT id FROM loop_plan_items)",
    "UPDATE cards SET plan_revision_id = NULL WHERE plan_revision_id IS NOT NULL"
    " AND plan_revision_id NOT IN (SELECT id FROM loop_plans)",
    "UPDATE discussion_messages SET parent_message_id = NULL WHERE parent_message_id IS NOT NULL"
    " AND parent_message_id NOT IN (SELECT id FROM discussion_messages)",
    "UPDATE discussion_threads SET origin_comment_id = NULL WHERE origin_comment_id IS NOT NULL"
    " AND origin_comment_id NOT IN (SELECT id FROM comments)",
    "UPDATE loop_documents SET source_analysis_ai_revision_id = NULL"
    " WHERE source_analysis_ai_revision_id IS NOT NULL"
    " AND source_analysis_ai_revision_id NOT IN (SELECT id FROM loop_documents)",
    "UPDATE loop_documents SET source_analysis_revision_id = NULL"
    " WHERE source_analysis_revision_id IS NOT NULL"
    " AND source_analysis_revision_id NOT IN (SELECT id FROM loop_documents)",
    "UPDATE loop_documents SET source_roadmap_ai_revision_id = NULL"
    " WHERE source_roadmap_ai_revision_id IS NOT NULL"
    " AND source_roadmap_ai_revision_id NOT IN (SELECT id FROM loop_documents)",
    "UPDATE loop_history SET loop_id = NULL WHERE loop_id IS NOT NULL"
    " AND loop_id NOT IN (SELECT id FROM loops)",
    "UPDATE loop_qa_cycles SET card_id = NULL WHERE card_id IS NOT NULL"
    " AND card_id NOT IN (SELECT id FROM cards)",
    "UPDATE loops SET current_plan_id = NULL WHERE current_plan_id IS NOT NULL"
    " AND current_plan_id NOT IN (SELECT id FROM loop_plans)",
    "UPDATE loops SET analysis_approval_id = NULL WHERE analysis_approval_id IS NOT NULL"
    " AND analysis_approval_id NOT IN (SELECT id FROM loop_approvals)",
    "UPDATE loops SET roadmap_approval_id = NULL WHERE roadmap_approval_id IS NOT NULL"
    " AND roadmap_approval_id NOT IN (SELECT id FROM loop_approvals)",
    "UPDATE loops SET implementation_approval_id = NULL"
    " WHERE implementation_approval_id IS NOT NULL"
    " AND implementation_approval_id NOT IN (SELECT id FROM loop_approvals)",
    "UPDATE loops SET qa_approval_id = NULL WHERE qa_approval_id IS NOT NULL"
    " AND qa_approval_id NOT IN (SELECT id FROM loop_approvals)",
    "UPDATE loops SET active_qa_cycle_id = NULL WHERE active_qa_cycle_id IS NOT NULL"
    " AND active_qa_cycle_id NOT IN (SELECT id FROM loop_qa_cycles)",
    "UPDATE loops SET history_id = NULL WHERE history_id IS NOT NULL"
    " AND history_id NOT IN (SELECT id FROM loop_history)",
)

# References that cannot be cleared: (what is missing, the rows that name it).
_REQUIRED = (
    (
        "loop_plans.roadmap_ai_revision_id",
        "SELECT id FROM loop_plans"
        " WHERE roadmap_ai_revision_id NOT IN (SELECT id FROM loop_documents) ORDER BY id",
    ),
    (
        "loop_plans.roadmap_revision_id",
        "SELECT id FROM loop_plans"
        " WHERE roadmap_revision_id NOT IN (SELECT id FROM loop_documents) ORDER BY id",
    ),
)


def upgrade() -> None:
    for statement in _CLEAR:
        op.execute(statement)
    connection = op.get_bind()
    for column, query in _REQUIRED:
        missing = [str(row) for (row,) in connection.exec_driver_sql(query)]
        if missing:
            raise RuntimeError(
                f"{column} names a row that does not exist in {len(missing)} row(s): "
                + ", ".join(missing[:20])
                + "; point them at an existing row and start again"
            )

    # SET NULL: a Ticket stays when the phase, plan item or plan revision it came from goes; all
    # of them go with the Loop. idx_cards_plan_item already starts with plan_item_id.
    with op.batch_alter_table("cards", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_cards_phase", "loop_phases", ["phase_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_cards_plan_item", "loop_plan_items", ["plan_item_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_cards_plan_revision",
            "loop_plans",
            ["plan_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_cards_phase", "cards", ["phase_id"])
    op.create_index("ix_cards_plan_revision", "cards", ["plan_revision_id"])

    # SET NULL: a reply stays in its discussion when the message it answers goes.
    with op.batch_alter_table("discussion_messages", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_discussion_messages_parent",
            "discussion_messages",
            ["parent_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_discussion_messages_parent", "discussion_messages", ["parent_message_id"])

    # SET NULL: a discussion stays when the comment it started from is deleted.
    with op.batch_alter_table("discussion_threads", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_discussion_threads_origin_comment",
            "comments",
            ["origin_comment_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_discussion_threads_origin_comment", "discussion_threads", ["origin_comment_id"]
    )

    # SET NULL: a revision's sources are provenance; the revision stays when a source goes, and
    # every revision of a Loop goes with the Loop.
    with op.batch_alter_table("loop_documents", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_documents_source_analysis_ai",
            "loop_documents",
            ["source_analysis_ai_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_loop_documents_source_analysis",
            "loop_documents",
            ["source_analysis_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_loop_documents_source_roadmap_ai",
            "loop_documents",
            ["source_roadmap_ai_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_loop_documents_source_analysis_ai",
        "loop_documents",
        ["source_analysis_ai_revision_id"],
    )
    op.create_index(
        "ix_loop_documents_source_analysis", "loop_documents", ["source_analysis_revision_id"]
    )
    op.create_index(
        "ix_loop_documents_source_roadmap_ai",
        "loop_documents",
        ["source_roadmap_ai_revision_id"],
    )

    # CASCADE, checked at the COMMIT: a plan revision is the structured form of its two roadmap
    # revisions and goes with them (only ever with the Loop). Deferred, because the plan is stored
    # with '' before the revisions exist and linked to them before the transaction ends.
    with op.batch_alter_table("loop_plans", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_plans_roadmap_ai",
            "loop_documents",
            ["roadmap_ai_revision_id"],
            ["id"],
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        )
        batch.create_foreign_key(
            "fk_loop_plans_roadmap",
            "loop_documents",
            ["roadmap_revision_id"],
            ["id"],
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        )
    op.create_index("ix_loop_plans_roadmap_ai", "loop_plans", ["roadmap_ai_revision_id"])
    op.create_index("ix_loop_plans_roadmap", "loop_plans", ["roadmap_revision_id"])

    # SET NULL: a QA cycle keeps its record when its QA Ticket is deleted with the Ticket's column.
    with op.batch_alter_table("loop_qa_cycles", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_qa_cycles_card", "cards", ["card_id"], ["id"], ondelete="SET NULL"
        )
    op.create_index("ix_loop_qa_cycles_card", "loop_qa_cycles", ["card_id"])

    # RESTRICT: a completed Loop and its history record are kept together. The history is never
    # deleted with the Loop (it is the immutable record of it), so the order problem above does
    # not arise; imported history names no Loop.
    with op.batch_alter_table("loop_history", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_history_loop", "loops", ["loop_id"], ["id"], ondelete="RESTRICT"
        )
    op.create_index("ix_loop_history_loop", "loop_history", ["loop_id"])

    # SET NULL for the Loop's pointers to its current plan, approvals and QA cycle: all of them go
    # with the Loop. RESTRICT for its history, as above.
    with op.batch_alter_table("loops", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loops_current_plan", "loop_plans", ["current_plan_id"], ["id"], ondelete="SET NULL"
        )
        for column in ("analysis", "roadmap", "implementation", "qa"):
            batch.create_foreign_key(
                f"fk_loops_{column}_approval",
                "loop_approvals",
                [f"{column}_approval_id"],
                ["id"],
                ondelete="SET NULL",
            )
        batch.create_foreign_key(
            "fk_loops_active_qa_cycle",
            "loop_qa_cycles",
            ["active_qa_cycle_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_loops_history", "loop_history", ["history_id"], ["id"], ondelete="RESTRICT"
        )
    op.create_index("ix_loops_current_plan", "loops", ["current_plan_id"])
    for column in ("analysis", "roadmap", "implementation", "qa"):
        op.create_index(f"ix_loops_{column}_approval", "loops", [f"{column}_approval_id"])
    op.create_index("ix_loops_active_qa_cycle", "loops", ["active_qa_cycle_id"])
    op.create_index("ix_loops_history", "loops", ["history_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
