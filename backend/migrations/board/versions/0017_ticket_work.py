"""A Ticket says where its work is done and what it waits for.

``cards.workplace`` describes the work and assigns nothing: ``codebase`` (it is done in a
repository, so it can be taken in a coding session), ``outside`` (another system or the world
outside) or ``unknown``. Every Ticket already there reads ``unknown``, so nothing old claims what
nobody said.

``cards.waiting_for`` is what the Ticket waits for: ``nothing``, ``decision``, ``information``,
``access`` (a system, key, account, setting or machine) or ``third_party`` (a supplier, a customer,
a lawyer, ...), with a short ``waiting_reason`` and who set it (``waiting_set_by``, a registry
actor) and when. Every Ticket already there waits for ``nothing``. The state a list shows (ready,
needs input, blocked) is computed from it and the plan's blockers on every read, never stored.

``loop_plan_items`` carries the RoadMap's starting values (``workplace``, ``waiting_for``,
``waiting_reason``) onto the card it publishes.

``ADD COLUMN`` with a column CHECK, not a rebuild: SQLite appends a NOT NULL column with its
default, gives every row already there that default and tests the CHECK against them. The DDL is
written out because Alembic's ``add_column`` drops a column's CHECK on SQLite.

Revision ID: 0017_ticket_work
Revises: 0016_ticket_summaries
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_ticket_work"
down_revision: str | None = "0016_ticket_summaries"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_WORKPLACE = "NOT NULL DEFAULT 'unknown' CHECK (workplace IN ('codebase','outside','unknown'))"
_WAITING_FOR = (
    "NOT NULL DEFAULT 'nothing'"
    " CHECK (waiting_for IN ('nothing','decision','information','access','third_party'))"
)
_WAITING_REASON = "NOT NULL DEFAULT '' CHECK (length(waiting_reason) <= 500)"

_STATEMENTS = (
    f"ALTER TABLE cards ADD COLUMN workplace TEXT {_WORKPLACE}",
    f"ALTER TABLE cards ADD COLUMN waiting_for TEXT {_WAITING_FOR}",
    f"ALTER TABLE cards ADD COLUMN waiting_reason TEXT {_WAITING_REASON}",
    "ALTER TABLE cards ADD COLUMN waiting_set_at TEXT",
    "ALTER TABLE cards ADD COLUMN waiting_set_by TEXT",
    f"ALTER TABLE loop_plan_items ADD COLUMN workplace TEXT {_WORKPLACE}",
    f"ALTER TABLE loop_plan_items ADD COLUMN waiting_for TEXT {_WAITING_FOR}",
    f"ALTER TABLE loop_plan_items ADD COLUMN waiting_reason TEXT {_WAITING_REASON}",
)


def upgrade() -> None:
    for statement in _STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
