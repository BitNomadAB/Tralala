"""POC decisions and what is missing from a person, as ``PocDecisionService`` and the Loop
summaries use them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..db.generated.board import POC_DECISIONS_COLUMNS, PocDecisionsRow


@dataclass(frozen=True, slots=True, kw_only=True)
class PocDecisionMark:
    """What a Loop summary counts of one record: its Loop and Ticket, its kind and status, and
    whether other work builds on it (``builds_on`` is not empty)."""

    loop_id: str
    card_id: str | None
    kind: str
    status: str
    built_on: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class PocDecisionAnswer:
    """A person's answer as it is stored: the new status, the feedback (empty for OK), the Ticket
    the feedback became (``None`` for OK) and who answered when."""

    status: str
    feedback: str
    feedback_card_id: str | None
    answered_by_actor_id: str
    answered_by_name: str
    answered_at: str


class PocDecisionRepository(Protocol):
    def get(self, decision_id: str) -> PocDecisionsRow | None: ...

    def for_loop(self, loop_id: str) -> list[PocDecisionsRow]:
        """The Loop's records by sequence, answered ones included."""
        ...

    def marks(self) -> list[PocDecisionMark]:
        """Every record on the board, by Loop and sequence, as a Loop summary counts them: one
        read for every Loop."""
        ...

    def add(self, row: PocDecisionsRow) -> None: ...

    def answer(self, decision_id: str, answer: PocDecisionAnswer) -> None: ...


__all__ = [
    "POC_DECISIONS_COLUMNS",
    "PocDecisionAnswer",
    "PocDecisionMark",
    "PocDecisionRepository",
]
