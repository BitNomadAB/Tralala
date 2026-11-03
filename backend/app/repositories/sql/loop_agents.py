"""``LoopAgentRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...db import values

_FOR_LOOP = text("SELECT purpose, agent_id FROM loop_agent_preferences WHERE loop_id = :id")
_AGENT_FOR = text(
    "SELECT agent_id FROM loop_agent_preferences WHERE loop_id = :id AND purpose = :p"
)
_CLEAR = text("DELETE FROM loop_agent_preferences WHERE loop_id = :id AND purpose = :p")
_STORE = text(
    "INSERT INTO loop_agent_preferences (loop_id, purpose, agent_id, updated_at)"
    " VALUES (:id, :p, :agent_id, :now)"
)


class SqlLoopAgentRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_loop(self, loop_id: str) -> dict[str, str]:
        result = self._connection.execute(_FOR_LOOP, {"id": loop_id}).mappings()
        return {values.text(row, "purpose"): values.text(row, "agent_id") for row in result}

    def agent_for(self, loop_id: str, purpose: str) -> str | None:
        row = self._connection.execute(_AGENT_FOR, {"id": loop_id, "p": purpose}).mappings().first()
        return None if row is None else values.text(row, "agent_id")

    def replace(self, loop_id: str, purpose: str, agent_id: str | None, *, now: str) -> None:
        self._connection.execute(_CLEAR, {"id": loop_id, "p": purpose})
        if agent_id:
            self._connection.execute(
                _STORE, {"id": loop_id, "p": purpose, "agent_id": agent_id, "now": now}
            )
