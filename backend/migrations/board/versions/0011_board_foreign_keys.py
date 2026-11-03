"""Foreign keys for the board columns that name a row of this database, and the indexes they need.

The build (``python -m tools.dbgen``) now requires a foreign key on every column that names a row,
an index that starts with every foreign key and an explicit ON DELETE rule. This revision adds the
indexes four existing keys lacked and the foreign keys of eight columns.

SQLite adds a foreign key only by rebuilding the table, which ``batch_alter_table`` does. The
runner enforces foreign keys inside its transaction, and dropping the old copy of a table fires the
ON DELETE action of every row that references it, so only tables nothing references are rebuilt,
parents before the tables that come to reference them. The references this revision cannot reach
are listed in ``tools/dbgen/rules.py`` with what blocks each one.

The Loop tables all belong to their Loop (``loop_id`` ON DELETE CASCADE). Between two rows the Loop
deletes together, RESTRICT would make deleting the Loop depend on the order SQLite visits the
tables (it fails when the referenced row goes first), so those keys CASCADE where the row is part of
what it references and SET NULL where the link is optional.

A reference whose row is gone is settled first, by what the column means: an optional one becomes
NULL; a NOT NULL one names a plan or a phase, which the application never deletes, so one that is
missing stops the upgrade with the rows to repair (the Migration Manager keeps its pre-migration
backup and marks the board ``migration_failed``). Nothing is deleted.

Revision ID: 0011_board_foreign_keys
Revises: 0010_generation_run_phase
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_board_foreign_keys"
down_revision: str | None = "0010_generation_run_phase"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Optional references: a row that is gone becomes NULL. An attachment needs a card or a discussion
# (ck_attachments_context), so its discussion is only cleared where it also has a card.
_CLEAR = (
    "UPDATE loop_plans SET approval_id = NULL WHERE approval_id IS NOT NULL"
    " AND approval_id NOT IN (SELECT id FROM loop_approvals)",
    "UPDATE loop_documents SET generation_run_id = NULL WHERE generation_run_id IS NOT NULL"
    " AND generation_run_id NOT IN (SELECT id FROM loop_generation_runs)",
    "UPDATE attachments SET message_id = NULL WHERE message_id IS NOT NULL"
    " AND message_id NOT IN (SELECT id FROM discussion_messages)",
    "UPDATE attachments SET discussion_id = NULL WHERE discussion_id IS NOT NULL"
    " AND card_id IS NOT NULL AND discussion_id NOT IN (SELECT id FROM discussion_threads)",
)

# References that cannot be cleared: (what is missing, the rows that name it).
_REQUIRED = (
    (
        "loop_phases.plan_id",
        "SELECT id FROM loop_phases WHERE plan_id NOT IN (SELECT id FROM loop_plans) ORDER BY id",
    ),
    (
        "loop_plan_items.plan_id",
        "SELECT id FROM loop_plan_items WHERE plan_id NOT IN (SELECT id FROM loop_plans)"
        " ORDER BY id",
    ),
    (
        "loop_plan_items.phase_id",
        "SELECT id FROM loop_plan_items WHERE phase_id NOT IN (SELECT id FROM loop_phases)"
        " ORDER BY id",
    ),
    (
        "loop_dependencies.plan_id",
        "SELECT id FROM loop_dependencies WHERE plan_id NOT IN (SELECT id FROM loop_plans)"
        " ORDER BY id",
    ),
    (
        "attachments.discussion_id",
        "SELECT id FROM attachments WHERE discussion_id IS NOT NULL AND card_id IS NULL"
        " AND discussion_id NOT IN (SELECT id FROM discussion_threads) ORDER BY id",
    ),
)


def upgrade() -> None:
    # Data first. Python's sqlite3 opens the transaction at the first INSERT/UPDATE/DELETE and runs
    # DDL before it in autocommit mode, so starting with DML keeps every rebuild below inside the
    # one transaction the runner rolls back on failure.
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

    # Existing keys without an index that starts with them.
    op.create_index("ix_card_labels_label", "card_labels", ["label_id"])
    op.create_index(
        "ix_comment_mentions_response", "comment_mention_jobs", ["response_comment_id"]
    )
    op.create_index("ix_discussion_rounds_thread", "discussion_rounds", ["discussion_id"])
    op.create_index("ix_loop_dependencies_loop", "loop_dependencies", ["loop_id"])

    # SET NULL: a plan keeps its content when its approval goes (both belong to the Loop).
    with op.batch_alter_table("loop_plans", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_plans_approval", "loop_approvals", ["approval_id"], ["id"], ondelete="SET NULL"
        )
    op.create_index("ix_loop_plans_approval", "loop_plans", ["approval_id"])

    # CASCADE: phases, plan items and dependencies are the projection of a plan revision's
    # payload, rebuilt from it on every registration; they are part of the plan they name.
    with op.batch_alter_table("loop_phases", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_phases_plan", "loop_plans", ["plan_id"], ["id"], ondelete="CASCADE"
        )
    with op.batch_alter_table("loop_plan_items", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_plan_items_plan", "loop_plans", ["plan_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_loop_plan_items_phase", "loop_phases", ["phase_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index("ix_loop_plan_items_plan", "loop_plan_items", ["plan_id"])
    with op.batch_alter_table("loop_dependencies", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_dependencies_plan", "loop_plans", ["plan_id"], ["id"], ondelete="CASCADE"
        )

    # SET NULL: the run is provenance; the document it produced stays.
    with op.batch_alter_table("loop_documents", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_loop_documents_run",
            "loop_generation_runs",
            ["generation_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_loop_documents_run", "loop_documents", ["generation_run_id"])

    # CASCADE: a discussion owns its attachments as a card does (card_id is CASCADE), and SET NULL
    # could leave a row with neither (ck_attachments_context). SET NULL for the message: the
    # attachment stays in its discussion.
    with op.batch_alter_table("attachments", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_attachments_discussion",
            "discussion_threads",
            ["discussion_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_attachments_message",
            "discussion_messages",
            ["message_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
