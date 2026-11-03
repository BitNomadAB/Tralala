"""Which agent a Loop prefers for each generation purpose, as ``LoopAgentService`` uses it."""

from __future__ import annotations

from typing import Protocol


class LoopAgentRepository(Protocol):
    def for_loop(self, loop_id: str) -> dict[str, str]:
        """The stored agent id per purpose; a purpose without a preference is absent."""
        ...

    def agent_for(self, loop_id: str, purpose: str) -> str | None: ...

    def replace(self, loop_id: str, purpose: str, agent_id: str | None, *, now: str) -> None:
        """Store ``agent_id`` for the purpose, or clear the purpose when it is ``None``."""
        ...
