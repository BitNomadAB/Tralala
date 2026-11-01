"""Which agent a Loop uses for each generation purpose.

A board lists the agents that may work on it (registry ``board_agents``). This service stores, per
Loop, the agent to prefer for ``analysis``, ``roadmap`` and ``qa`` — a preference, never a grant:
generation still refuses an agent the board does not list, and an explicit ``agent_id`` on a run
always wins so one run can deviate without changing the stored default.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import NotFound, ValidationFailure
from ..storage.board_db import BoardDatabaseManager
from ..storage.sqlite import utcnow
from .activity import log_activity
from .agents import AgentService

PURPOSES: tuple[str, ...] = ("analysis", "roadmap", "qa")


class LoopAgentService:
    def __init__(self, boards: BoardDatabaseManager, agents: AgentService) -> None:
        self.boards = boards
        self.agents = agents

    def get(self, board_id: str, loop_id: str) -> dict[str, str | None]:
        with self.boards.reader(board_id) as conn:
            self._require_loop(conn, loop_id)
            return self._read(conn, loop_id)

    @staticmethod
    def _require_loop(conn: Any, loop_id: str) -> None:
        found = conn.execute(
            text("SELECT id FROM loops WHERE id = :id"), {"id": loop_id}
        ).mappings().first()
        if found is None:
            raise NotFound("Loop not found")

    @staticmethod
    def _read(conn: Any, loop_id: str) -> dict[str, str | None]:
        stored = {
            row["purpose"]: row["agent_id"]
            for row in conn.execute(
                text("SELECT purpose, agent_id FROM loop_agent_preferences WHERE loop_id = :id"),
                {"id": loop_id},
            ).mappings()
        }
        return {purpose: stored.get(purpose) for purpose in PURPOSES}

    def set(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        assignments: dict[str, str | None],
    ) -> dict[str, str | None]:
        """Replace the stored preference; ``None`` clears one purpose."""
        actor.require("boards:write")
        chosen = [agent_id for agent_id in assignments.values() if agent_id]
        self.agents.validate_ids(chosen)
        allowed = set(self.agents.agent_ids(board_id))
        if allowed:
            for purpose, agent_id in assignments.items():
                if agent_id and agent_id not in allowed:
                    raise ValidationFailure(
                        "That agent does not work on this board",
                        code="agent_not_on_board",
                        details={"purpose": purpose, "agent_id": agent_id},
                    )
        now = utcnow()
        with self.boards.session(board_id) as conn:
            self._require_loop(conn, loop_id)
            for purpose, agent_id in assignments.items():
                conn.execute(
                    text("DELETE FROM loop_agent_preferences WHERE loop_id = :id AND purpose = :p"),
                    {"id": loop_id, "p": purpose},
                )
                if agent_id:
                    conn.execute(
                        text(
                            "INSERT INTO loop_agent_preferences (loop_id, purpose, agent_id,"
                            " updated_at) VALUES (:id, :p, :agent_id, :now)"
                        ),
                        {"id": loop_id, "p": purpose, "agent_id": agent_id, "now": now},
                    )
            log_activity(
                conn,
                actor,
                action="loop.agents_updated",
                entity_type="loop",
                entity_id=loop_id,
                changes={"agents": assignments},
            )
            return self._read(conn, loop_id)

    # --- resolution ------------------------------------------------------------

    def resolve(self, board_id: str, loop_id: str, purpose: str) -> str | None:
        """The stored agent for one purpose, or ``None`` when the Loop has no preference."""
        return self._read_purpose(board_id, loop_id, purpose)

    def _read_purpose(self, board_id: str, loop_id: str, purpose: str) -> str | None:
        with self.boards.reader(board_id) as conn:
            row = conn.execute(
                text(
                    "SELECT agent_id FROM loop_agent_preferences"
                    " WHERE loop_id = :id AND purpose = :p"
                ),
                {"id": loop_id, "p": purpose},
            ).mappings().first()
        return row["agent_id"] if row else None
