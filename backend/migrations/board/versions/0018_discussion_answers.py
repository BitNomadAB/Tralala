"""A discussion answer carries a standard structure, and each round a synthesis beside it.

``discussion_messages.answer_json`` holds a participant's structured answer (position, one-sentence
recommendation, for, against, conditions, open questions, confidence) beside its prose in
``content``; ``{}`` is a person's message, or an answer written before this revision.
``discussion_rounds.synthesis_json`` holds the decision support Tralala computes from the latest
answers after the round; ``{}`` is a round before this revision.

A vote's position moves to the answer's set: ``agree`` reads ``yes``, ``disagree`` reads ``no`` and
``abstain`` reads ``unclear``, so an older thread speaks the same language as a new one.

Revision ID: 0018_discussion_answers
Revises: 0016_ticket_summaries
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_discussion_answers"
down_revision: str | None = "0016_ticket_summaries"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discussion_messages",
        sa.Column("answer_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "discussion_rounds",
        sa.Column("synthesis_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.execute(
        "UPDATE discussion_votes SET position = CASE position"
        " WHEN 'agree' THEN 'yes' WHEN 'disagree' THEN 'no' ELSE 'unclear' END"
        " WHERE position IN ('agree', 'disagree', 'abstain')"
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
