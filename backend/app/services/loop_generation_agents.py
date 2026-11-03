"""Which agent runs a generation, and the role it runs with.

An explicit choice, then the Loop's stored preference, then a board agent; an organisation
profile is never a Loop's worker. The registry is reached only through its unit of work, which
each function takes as ``store``.
"""

from __future__ import annotations

from typing import Protocol, TypedDict

from ..core.errors import ServiceUnavailable, ValidationFailure
from ..db.generated.registry import AgentsRow
from ..repositories.registry import RegistryUnitOfWork
from .agents import EffectiveRole
from .runtime import EXECUTABLE_CONNECTION_TYPES


class RoleSource(Protocol):
    """``AgentService.effective_role``: the role an agent runs with now."""

    def effective_role(self, agent_id: str) -> EffectiveRole: ...


class PreferredAgents(Protocol):
    """``LoopAgentService.resolve``: the Loop's stored agent for one purpose."""

    def resolve(self, board_id: str, loop_id: str, purpose: str) -> str | None: ...


class RolePrompt(TypedDict):
    system_prompt: str
    role_source: str
    role_template_id: str | None
    role_template_name: str | None


def preferred_agent(
    board_id: str, loop_id: str, purpose: str, *, loop_agents: PreferredAgents | None
) -> str | None:
    """The Loop's stored choice for this purpose, or None when it has no preference."""
    return (
        loop_agents.resolve(board_id, loop_id, purpose)
        if loop_agents is not None
        else None
    )


def resolve_agent(
    agent_id: str | None,
    board_id: str,
    loop_id: str,
    purpose: str,
    *,
    store: RegistryUnitOfWork,
    loop_agents: PreferredAgents | None,
) -> AgentsRow:
    """Explicit choice, then the Loop's stored preference, then a board agent.

    An explicit choice must be usable or the run fails loudly. A stored preference may have gone
    stale (the agent was deleted, disabled, dropped from the board, or is an organisation
    profile), and then the run falls back to the board default instead of blocking.
    """
    requested = agent_id
    if not agent_id:
        agent_id = preferred_agent(board_id, loop_id, purpose, loop_agents=loop_agents)
    row = agent_row(agent_id, board_id, strict=bool(requested), store=store) if agent_id else None
    if row is None:
        row = default_agent_row(board_id, store=store)
    if row is None:
        raise ServiceUnavailable(
            "No enabled generation agent is configured",
            code="generation_unavailable",
            details={"hint": "Configure an OpenAI-compatible agent in Settings"},
        )
    connection_type = str(row.connection_type or "openai_compatible")
    if connection_type not in EXECUTABLE_CONNECTION_TYPES:
        raise ServiceUnavailable(
            "This connection type cannot execute generation requests",
            code="generation_unavailable",
            details={
                "connection_type": row.connection_type,
                "supported": list(EXECUTABLE_CONNECTION_TYPES),
            },
        )
    return row


def agent_row(
    agent_id: str, board_id: str, *, strict: bool, store: RegistryUnitOfWork
) -> AgentsRow | None:
    """An agent a run may use, or None when it is unusable and the caller is not strict."""
    with store.reader() as registry:
        row = registry.agents.get(agent_id)
        scope = registry.agents.role_scope(agent_id)
        board_agents = registry.agent_links.agent_ids(board_id)
    if row is None:
        if strict:
            raise ValidationFailure("Agent not found", details={"agent_id": agent_id})
        return None
    if scope == "organisation":
        if strict:
            raise ValidationFailure(
                "An organisation profile cannot run a Loop",
                code="agent_scope_organisation",
                details={"agent_id": agent_id, "board_id": board_id},
            )
        return None
    if not row.enabled:
        if strict:
            raise ValidationFailure("Agent is disabled", details={"agent_id": agent_id})
        return None
    if board_agents and agent_id not in board_agents:
        if strict:
            raise ValidationFailure(
                "That agent does not work on this board",
                code="agent_not_on_board",
                details={"agent_id": agent_id, "board_id": board_id},
            )
        return None
    return row


def default_agent_row(board_id: str, *, store: RegistryUnitOfWork) -> AgentsRow | None:
    """First board agent by name, else the first enabled generator of the installation.

    Organisation profiles are excluded either way: they are not a Loop's worker.
    """
    types = list(EXECUTABLE_CONNECTION_TYPES)
    with store.reader() as registry:
        board_agents = registry.agent_links.agent_ids(board_id)
        row = (
            registry.agents.first_generator(types, agent_ids=board_agents)
            if board_agents
            else None
        )
        if row is None:
            row = registry.agents.first_generator(types)
    return row


def role_prompt(agent: AgentsRow, *, agents: RoleSource) -> RolePrompt:
    """Resolve the agent's role the same way a discussion does, without joining it later."""
    role = agents.effective_role(agent.id)
    return {
        "system_prompt": str(role.get("system_prompt") or "").strip(),
        "role_source": role["role_source"],
        "role_template_id": role["role_template_id"],
        "role_template_name": role["role_template_name"],
    }
