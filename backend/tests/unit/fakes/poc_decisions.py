"""``PocDecisionRepository`` over a ``BoardState``: a list kept in insertion order, with the keys
and checks of ``poc_decisions`` (revision 0023) enforced as the database would."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.generated.board import PocDecisionsRow
from app.repositories.poc_decisions import PocDecisionAnswer, PocDecisionMark
from tests.unit.fakes.registry import ConstraintError

if TYPE_CHECKING:
    from tests.unit.fakes.board import BoardState

_KINDS = ("decision", "missing")
_STATUSES = ("open", "ok", "feedback")


def _check(row: PocDecisionsRow, state: BoardState) -> None:
    """The CHECK constraints and foreign keys of the table."""
    if row.kind not in _KINDS:
        raise ConstraintError(f"poc_decisions.kind {row.kind!r}")
    if row.status not in _STATUSES:
        raise ConstraintError(f"poc_decisions.status {row.status!r}")
    if row.sequence < 1:
        raise ConstraintError("poc_decisions.sequence is at least 1")
    if len(row.details) > 20_000 or len(row.feedback) > 2000:
        raise ConstraintError("poc_decisions.details or feedback is too long")
    if (row.status == "open") != (row.answered_at is None):
        raise ConstraintError("poc_decisions: an answered decision has its answer, an open none")
    if row.loop_id not in state.loops:
        raise ConstraintError(f"poc_decisions.loop_id {row.loop_id} does not exist")
    for card_id in (row.card_id, row.feedback_card_id):
        if card_id is not None and card_id not in state.cards:
            raise ConstraintError(f"poc_decisions names card {card_id}, which does not exist")


class FakePocDecisionRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def _index(self, decision_id: str) -> int | None:
        rows = self._state.poc_decisions
        return next((i for i, row in enumerate(rows) if row.id == decision_id), None)

    def get(self, decision_id: str) -> PocDecisionsRow | None:
        index = self._index(decision_id)
        return None if index is None else self._state.poc_decisions[index]

    def for_loop(self, loop_id: str) -> list[PocDecisionsRow]:
        rows = (row for row in self._state.poc_decisions if row.loop_id == loop_id)
        return sorted(rows, key=lambda row: row.sequence)

    def marks(self) -> list[PocDecisionMark]:
        rows = sorted(self._state.poc_decisions, key=lambda row: (row.loop_id, row.sequence))
        return [
            PocDecisionMark(
                loop_id=row.loop_id,
                card_id=row.card_id,
                kind=row.kind,
                status=row.status,
                built_on=row.builds_on != "",
            )
            for row in rows
        ]

    def add(self, row: PocDecisionsRow) -> None:
        for other in self._state.poc_decisions:
            if other.id == row.id or other.key == row.key:
                raise ConstraintError(f"poc_decisions {row.id} breaks the primary or key index")
            if other.loop_id == row.loop_id and other.sequence == row.sequence:
                raise ConstraintError("poc_decisions (loop_id, sequence) is unique")
        _check(row, self._state)
        self._state.poc_decisions.append(row)

    def answer(self, decision_id: str, answer: PocDecisionAnswer) -> None:
        index = self._index(decision_id)
        if index is None:
            return
        answered = self._state.poc_decisions[index].__replace__(
            status=answer.status,
            feedback=answer.feedback,
            feedback_card_id=answer.feedback_card_id,
            answered_by_actor_id=answer.answered_by_actor_id,
            answered_by_name=answer.answered_by_name,
            answered_at=answer.answered_at,
        )
        _check(answered, self._state)
        self._state.poc_decisions[index] = answered
