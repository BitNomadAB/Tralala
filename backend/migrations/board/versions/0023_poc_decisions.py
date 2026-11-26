"""POC decisions, a Loop's stop list and the stop a wait names.

An obstacle in a Loop is one of three kinds. A POC decision is a choice that can be changed
afterwards: the one who works takes it, records it and goes on, and a person answers it later with
OK or with feedback, which becomes a new Ticket. Something missing from a person (an API key, an
account) is recorded the same way, as kind ``missing``, and the work goes around it. Neither ever
blocks anything. ``poc_decisions`` holds both: one row a record, numbered per Loop (``sequence``,
unique with the Loop) and keyed ``<LoopKey>-POC-<nnn>``.

A real stop is only what the Loop's stop list names: ``loops.stops_json`` holds it as a JSON array
of strings, NULL for the default list. ``cards.waiting_stop`` is the line a wait names, NULL for a
wait that names none (every wait set before this revision, and every wait a caller sets without a
stop).

``created_by_actor_id`` and ``answered_by_actor_id`` name actors in the registry, which no
constraint can reach (``tools/dbgen/rules.py`` lists them, as it lists
``discussion_threads.created_by_actor_id``); the names beside them are the names at the time, so a
later rename does not rewrite who recorded or answered a decision.

Revision ID: 0023_poc_decisions
Revises: 0022_board_discussions
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_poc_decisions"
down_revision: str | None = "0022_board_discussions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("loops", sa.Column("stops_json", sa.Text(), nullable=True))
    op.add_column("cards", sa.Column("waiting_stop", sa.Text(), nullable=True))

    op.create_table(
        "poc_decisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("loop_id", sa.Text(), nullable=False),
        sa.Column("card_id", sa.Text(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("chosen", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("alternative", sa.Text(), nullable=False, server_default=""),
        sa.Column("change_path", sa.Text(), nullable=False),
        sa.Column("missing", sa.Text(), nullable=False, server_default=""),
        sa.Column("builds_on", sa.Text(), nullable=False, server_default=""),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("feedback_card_id", sa.Text(), nullable=True),
        sa.Column("created_by_actor_id", sa.Text(), nullable=False),
        sa.Column("created_by_type", sa.Text(), nullable=False),
        sa.Column("created_by_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("answered_by_actor_id", sa.Text(), nullable=True),
        sa.Column("answered_by_name", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.Text(), nullable=True),
        # CASCADE: a decision is part of its Loop, as the Loop's notes, lists and cards are, and
        # goes with it; RESTRICT would make deleting the Loop fail on its first decision.
        sa.ForeignKeyConstraint(
            ["loop_id"], ["loops.id"], name="fk_poc_decisions_loop", ondelete="CASCADE"
        ),
        # SET NULL: the decision outlives the Ticket it was taken on. A card is deleted only with
        # the archived list that holds it, and what was chosen and why stays on the Loop; only
        # the pointer goes.
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name="fk_poc_decisions_card", ondelete="SET NULL"
        ),
        # SET NULL: the feedback stays on the decision when the Ticket it became is deleted.
        sa.ForeignKeyConstraint(
            ["feedback_card_id"],
            ["cards.id"],
            name="fk_poc_decisions_feedback_card",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("kind IN ('decision', 'missing')", name="ck_poc_decisions_kind"),
        sa.CheckConstraint(
            "status IN ('open', 'ok', 'feedback')", name="ck_poc_decisions_status"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_poc_decisions_sequence"),
        sa.CheckConstraint("length(details) <= 20000", name="ck_poc_decisions_details_length"),
        sa.CheckConstraint("length(feedback) <= 2000", name="ck_poc_decisions_feedback_length"),
        # An answered decision says who answered and when; an open one has no answer.
        sa.CheckConstraint(
            "(status = 'open') = (answered_at IS NULL)", name="ck_poc_decisions_answered"
        ),
        sqlite_strict=True,
    )
    op.create_index(
        "ux_poc_decisions_loop_sequence", "poc_decisions", ["loop_id", "sequence"], unique=True
    )
    op.create_index("ux_poc_decisions_key", "poc_decisions", ["key"], unique=True)
    op.create_index("ix_poc_decisions_card", "poc_decisions", ["card_id"])
    op.create_index("ix_poc_decisions_feedback_card", "poc_decisions", ["feedback_card_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
