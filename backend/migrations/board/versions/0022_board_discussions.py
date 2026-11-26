"""Discussions on the board itself: closing a thread, a read marker per reader, a Ticket reference.

A thread with no Ticket (``card_id`` NULL, which the column has always allowed) is a discussion on
the board. The one who opened a thread may close it: ``ck_discussion_status`` admits ``closed``,
and ``closed_at`` and ``closed_by_actor_id`` say when and by whom. A closed thread still takes
comments; each is marked ``after_closed``, so nothing is ever deleted and a reader sees which words
came after the close. A message may point at a Ticket on the same board (``ref_card_id``).
``discussion_reads`` keeps, per actor and thread, when that actor last read it, so a person or an
API key can tell what is new for them.

``discussion_threads`` is rebuilt the way 0019 rebuilt ``loop_generation_runs``, for the same
reasons: SQLite cannot alter a CHECK constraint in place, and the shape is given explicitly
(``copy_from``) so the rebuild does not depend on SQLite reflecting CHECK constraints. The table
holds no collated column, so nothing needs ``reflect_args``; its keys keep their names and actions
(the card's CASCADE from 0004, the origin comment's SET NULL from 0012), its three indexes are
dropped before and created after the rebuild, and its rows keep every value. The new columns come
last, so the existing ones keep their order. ``discussion_messages`` is rebuilt by reflection as
0012 rebuilt it, because a revision adds a foreign key by rebuilding the table.

``closed_by_actor_id`` and ``discussion_reads.actor_id`` name actors in the registry, which no
constraint can reach (``tools/dbgen/rules.py`` lists them, as it lists ``created_by_actor_id``).

Revision ID: 0022_board_discussions
Revises: 0021_card_notes
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_board_discussions"
down_revision: str | None = "0021_card_notes"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

STATUSES_BEFORE = (
    "open",
    "discussing",
    "consensus_proposed",
    "human_review",
    "approved",
    "vetoed",
    "rework_requested",
    "unresolved",
    "cancelled",
)
STATUSES = (*STATUSES_BEFORE, "closed")


def _status_check(statuses: Sequence[str]) -> str:
    return "status IN ({})".format(",".join(f"'{value}'" for value in statuses))


# The table as revisions 0004, 0005 and 0012 left it.
threads_before = sa.Table(
    "discussion_threads",
    sa.MetaData(),
    sa.Column("id", sa.String(), primary_key=True),
    sa.Column("card_id", sa.String(), sa.ForeignKey("cards.id", ondelete="CASCADE")),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("goal", sa.String(), nullable=False),
    sa.Column("mode", sa.String(), nullable=False, server_default="manual"),
    sa.Column("status", sa.String(), nullable=False, server_default="open"),
    sa.Column("created_by_actor_id", sa.String(), nullable=False),
    sa.Column("created_by_type", sa.String(), nullable=False),
    sa.Column("created_by_name", sa.String(), nullable=False),
    sa.Column("max_rounds", sa.Integer(), nullable=False, server_default="3"),
    sa.Column("origin_comment_id", sa.String(), nullable=True),
    sa.Column("escalation_depth", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("created_at", sa.String(), nullable=False),
    sa.Column("updated_at", sa.String(), nullable=False),
    sa.Column("last_activity_at", sa.String(), nullable=False),
    sa.Column("round_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("run_state", sa.String(), nullable=False, server_default="idle"),
    sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
    sa.CheckConstraint("mode IN ('manual','roundtable','autonomous')", name="ck_discussion_mode"),
    sa.CheckConstraint(_status_check(STATUSES_BEFORE), name="ck_discussion_status"),
    sa.ForeignKeyConstraint(
        ["origin_comment_id"],
        ["comments.id"],
        name="fk_discussion_threads_origin_comment",
        ondelete="SET NULL",
    ),
)

_THREAD_INDEXES = (
    ("ix_discussion_threads_card", ["card_id"]),
    ("ix_discussion_threads_status", ["status"]),
    ("ix_discussion_threads_origin_comment", ["origin_comment_id"]),
)


def upgrade() -> None:
    for name, _columns in _THREAD_INDEXES:
        op.drop_index(name, table_name="discussion_threads")
    with op.batch_alter_table(
        "discussion_threads", copy_from=threads_before, recreate="always"
    ) as batch:
        batch.drop_constraint("ck_discussion_status", type_="check")
        batch.create_check_constraint("ck_discussion_status", _status_check(STATUSES))
        batch.add_column(sa.Column("closed_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("closed_by_actor_id", sa.Text(), nullable=True))
    for name, columns in _THREAD_INDEXES:
        op.create_index(name, "discussion_threads", columns)

    # SET NULL: a message outlives the Ticket it pointed at. The words stay in the discussion
    # when that Ticket is deleted with its archived list; only the pointer goes.
    with op.batch_alter_table("discussion_messages", recreate="always") as batch:
        batch.add_column(
            sa.Column("after_closed", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("ref_card_id", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_discussion_messages_after_closed", "after_closed IN (0, 1)"
        )
        batch.create_foreign_key(
            "fk_discussion_messages_ref_card",
            "cards",
            ["ref_card_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_discussion_messages_ref_card", "discussion_messages", ["ref_card_id"])

    op.create_table(
        "discussion_reads",
        sa.Column("discussion_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("last_read_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("discussion_id", "actor_id", name="pk_discussion_reads"),
        # CASCADE: a read marker is part of its thread and means nothing without it; the thread
        # goes only with its Ticket (card_id CASCADE), and RESTRICT here would make that delete
        # fail on the first marker.
        sa.ForeignKeyConstraint(
            ["discussion_id"],
            ["discussion_threads.id"],
            name="fk_discussion_reads_discussion",
            ondelete="CASCADE",
        ),
        sqlite_strict=True,
    )
    op.create_index("ix_discussion_reads_actor", "discussion_reads", ["actor_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
