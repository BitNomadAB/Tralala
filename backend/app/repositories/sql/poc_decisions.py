"""``PocDecisionRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import POC_DECISIONS_COLUMNS, PocDecisionsRow
from ..poc_decisions import PocDecisionAnswer, PocDecisionMark

_DECISION = (
    f"SELECT {sql.column_list(POC_DECISIONS_COLUMNS)}"  # noqa: S608 - from POC_DECISIONS_COLUMNS
    " FROM poc_decisions"
)
_GET = text(f"{_DECISION} WHERE id = :id")
_FOR_LOOP = text(f"{_DECISION} WHERE loop_id = :loop_id ORDER BY sequence")
_MARKS = text(
    "SELECT loop_id, card_id, kind, status, builds_on <> '' AS built_on FROM poc_decisions"
    " ORDER BY loop_id, sequence"
)
_ADD = text(
    "INSERT INTO poc_decisions (id, loop_id, card_id, sequence, key, kind, title, chosen, reason,"
    " alternative, change_path, missing, builds_on, details, status, feedback, feedback_card_id,"
    " created_by_actor_id, created_by_type, created_by_name, created_at, answered_by_actor_id,"
    " answered_by_name, answered_at)"
    " VALUES (:id, :loop_id, :card_id, :sequence, :key, :kind, :title, :chosen, :reason,"
    " :alternative, :change_path, :missing, :builds_on, :details, :status, :feedback,"
    " :feedback_card_id, :created_by_actor_id, :created_by_type, :created_by_name, :created_at,"
    " :answered_by_actor_id, :answered_by_name, :answered_at)"
)
_ANSWER = text(
    "UPDATE poc_decisions SET status = :status, feedback = :feedback,"
    " feedback_card_id = :feedback_card_id, answered_by_actor_id = :answered_by_actor_id,"
    " answered_by_name = :answered_by_name, answered_at = :answered_at WHERE id = :id"
)


class SqlPocDecisionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, decision_id: str) -> PocDecisionsRow | None:
        row = self._connection.execute(_GET, {"id": decision_id}).mappings().first()
        return None if row is None else PocDecisionsRow.from_mapping(row)

    def for_loop(self, loop_id: str) -> list[PocDecisionsRow]:
        result = self._connection.execute(_FOR_LOOP, {"loop_id": loop_id}).mappings()
        return [PocDecisionsRow.from_mapping(row) for row in result]

    def marks(self) -> list[PocDecisionMark]:
        result = self._connection.execute(_MARKS).mappings()
        return [
            PocDecisionMark(
                loop_id=values.text(row, "loop_id"),
                card_id=values.text_or_none(row, "card_id"),
                kind=values.text(row, "kind"),
                status=values.text(row, "status"),
                built_on=values.flag(row, "built_on"),
            )
            for row in result
        ]

    def add(self, row: PocDecisionsRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "loop_id": row.loop_id,
                "card_id": row.card_id,
                "sequence": row.sequence,
                "key": row.key,
                "kind": row.kind,
                "title": row.title,
                "chosen": row.chosen,
                "reason": row.reason,
                "alternative": row.alternative,
                "change_path": row.change_path,
                "missing": row.missing,
                "builds_on": row.builds_on,
                "details": row.details,
                "status": row.status,
                "feedback": row.feedback,
                "feedback_card_id": row.feedback_card_id,
                "created_by_actor_id": row.created_by_actor_id,
                "created_by_type": row.created_by_type,
                "created_by_name": row.created_by_name,
                "created_at": row.created_at,
                "answered_by_actor_id": row.answered_by_actor_id,
                "answered_by_name": row.answered_by_name,
                "answered_at": row.answered_at,
            },
        )

    def answer(self, decision_id: str, answer: PocDecisionAnswer) -> None:
        self._connection.execute(
            _ANSWER,
            {
                "id": decision_id,
                "status": answer.status,
                "feedback": answer.feedback,
                "feedback_card_id": answer.feedback_card_id,
                "answered_by_actor_id": answer.answered_by_actor_id,
                "answered_by_name": answer.answered_by_name,
                "answered_at": answer.answered_at,
            },
        )
