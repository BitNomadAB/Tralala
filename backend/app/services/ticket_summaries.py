"""A Ticket's short summary: who wrote it and whether it still matches the Ticket.

Pure functions over a card's row, so the service, the views and the worker tools agree on one rule.
A summary remembers the title and description it was written from as a hash; when either changes
the summary is still shown, marked stale, so a reader knows to write a new one.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from ..core.context import ActorContext
from ..db.generated.board import CardsRow

type SummarySource = Literal["", "plan", "person", "agent"]


def summary_basis(title: str, description: str) -> str:
    """The hash of what a summary describes: the title and the description it was written from."""
    return hashlib.sha256(f"{title}\n{description}".encode()).hexdigest()


def summary_source(actor: ActorContext) -> SummarySource:
    """Who wrote a summary through a card write: a signed-in person or an agent's token."""
    return "person" if actor.is_user else "agent"


def summary_stale(row: CardsRow) -> bool:
    """A written summary whose Ticket's title or description changed after it was written."""
    if not row.summary:
        return False
    return row.summary_basis_sha256 != summary_basis(row.title, row.description)


__all__ = [
    "SummarySource",
    "summary_basis",
    "summary_source",
    "summary_stale",
]
