"""``LoopQaRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import LOOP_QA_CYCLES_COLUMNS, LoopQaCyclesRow

_CYCLES_COLUMNS = sql.column_list(LOOP_QA_CYCLES_COLUMNS)
_CYCLES = text(
    f"SELECT {_CYCLES_COLUMNS} FROM loop_qa_cycles"  # noqa: S608 - from LOOP_QA_CYCLES_COLUMNS
    " WHERE loop_id = :id ORDER BY cycle_number"
)
_ALL_CYCLES = text(
    f"SELECT {_CYCLES_COLUMNS} FROM loop_qa_cycles"  # noqa: S608 - from LOOP_QA_CYCLES_COLUMNS
    " WHERE loop_id IN (SELECT id FROM loops) ORDER BY cycle_number"
)
_SUPERSEDE_OPEN = text(
    "UPDATE loop_qa_cycles SET status = 'superseded', updated_at = :now"
    " WHERE loop_id = :id AND status IN ('pending','instructions_ready','in_progress')"
)


class SqlLoopQaRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def cycles(self, loop_id: str | None) -> list[LoopQaCyclesRow]:
        if loop_id is None:
            result = self._connection.execute(_ALL_CYCLES)
        else:
            result = self._connection.execute(_CYCLES, {"id": loop_id})
        return [LoopQaCyclesRow.from_mapping(row) for row in result.mappings()]

    def supersede_open(self, loop_id: str, *, now: str) -> None:
        self._connection.execute(_SUPERSEDE_OPEN, {"now": now, "id": loop_id})
