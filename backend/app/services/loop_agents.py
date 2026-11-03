"""Which agent a Loop uses for each generation purpose.

A board lists the agents that may work on it (registry ``board_agents``). This service stores, per
Loop, the agent to prefer for ``analysis``, ``roadmap`` and ``qa`` — a preference, never a grant:
generation still refuses an agent the board does not list, and an explicit ``agent_id`` on a run
always wins so one run can deviate without changing the stored default.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import NotFound, ValidationFailure
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from .activity import activity_entry

PURPOSES: tuple[str, ...] = ("analysis", "roadmap", "qa")


class BoardAgentRoster(Protocol):
    """The registry side: which agents exist as board profiles, and which work on a board."""

    def validate_ids(self, agent_ids: list[str]) -> None: ...

    def agent_ids(self, board_id: str) -> list[str]: ...


def _new_id() -> str:
    return str(uuid4())


class LoopAgentService:
    def __init__(
        self,
        store: BoardUnitOfWork,
        agents: BoardAgentRoster,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.store = store
        self.agents = agents
        self._clock = clock
        self._new_id = new_id

    def get(self, board_id: str, loop_id: str) -> dict[str, str | None]:
        with self.store.reader(board_id) as repos:
            _require_loop(repos, loop_id)
            return _read(repos, loop_id)

    def set(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        assignments: Mapping[str, str | None],
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
        now = self._clock()
        with self.store.writer(board_id) as repos:
            _require_loop(repos, loop_id)
            for purpose, agent_id in assignments.items():
                repos.loop_agents.replace(loop_id, purpose, agent_id, now=now)
            repos.activity.add(
                activity_entry(
                    actor,
                    action="loop.agents_updated",
                    entity_type="loop",
                    entity_id=loop_id,
                    changes={"agents": dict(assignments)},
                    entry_id=self._new_id(),
                    timestamp=now,
                )
            )
            return _read(repos, loop_id)

    def resolve(self, board_id: str, loop_id: str, purpose: str) -> str | None:
        """The stored agent for one purpose, or ``None`` when the Loop has no preference."""
        with self.store.reader(board_id) as repos:
            return repos.loop_agents.agent_for(loop_id, purpose)


def _require_loop(repos: BoardRepositories, loop_id: str) -> None:
    if repos.loops.get(loop_id) is None:
        raise NotFound("Loop not found")


def _read(repos: BoardRepositories, loop_id: str) -> dict[str, str | None]:
    stored = repos.loop_agents.for_loop(loop_id)
    return {purpose: stored.get(purpose) for purpose in PURPOSES}
