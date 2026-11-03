"""Role templates, agent profiles and the boards that select them, for the agent services.

Every row here lives in the registry. An agent references a role template by id (or carries an
override), and a board's choice of agents is a row per agent in ``board_agents``.
"""

from __future__ import annotations

from typing import Protocol, TypedDict

from ..db.generated.registry import AgentsRow, BoardAgentsRow, RoleTemplatesRow

# The columns of ``RoleTemplateChanges`` and ``AgentChanges``, as an update formats them into its
# SQL text (core/sql.py).
ROLE_TEMPLATE_EDITABLE = (
    "name",
    "description",
    "system_prompt",
    "default_system_prompt",
    "scope",
)
AGENT_EDITABLE = (
    "name",
    "description",
    "role_template_id",
    "role_prompt_override",
    "connection_type",
    "base_url",
    "model",
    "temperature",
    "max_output_tokens",
    "timeout_seconds",
    "enabled",
    "api_key_ciphertext",
    "api_key_hint",
)


class RoleTemplateChanges(TypedDict, total=False):
    """The columns of a role template a change may write; ``updated_at`` is written with them."""

    name: str
    description: str
    system_prompt: str
    default_system_prompt: str
    scope: str


class AgentChanges(TypedDict, total=False):
    """The columns of an agent an edit may write; ``updated_at`` is written with them."""

    name: str
    description: str
    role_template_id: str | None
    role_prompt_override: str | None
    connection_type: str
    base_url: str
    model: str | None
    temperature: float | None
    max_output_tokens: int | None
    timeout_seconds: int
    enabled: int
    api_key_ciphertext: str | None
    api_key_hint: str | None


class RoleTemplateRepository(Protocol):
    def all(self) -> list[RoleTemplatesRow]:
        """Built-in templates first, then by name (case-insensitive, as the column compares)."""
        ...

    def get(self, role_id: str) -> RoleTemplatesRow | None: ...

    def by_builtin_key(self, key: str) -> RoleTemplatesRow | None: ...

    def add(self, row: RoleTemplatesRow) -> None:
        """Raises ``ConstraintViolationError`` when the name (or built-in key) is taken."""
        ...

    def update(self, role_id: str, changes: RoleTemplateChanges, *, now: str) -> None:
        """Write ``changes`` (at least one) with ``updated_at = now``; ``ConstraintViolationError``
        when the new name is taken."""
        ...

    def delete(self, role_id: str) -> None: ...


class AgentRepository(Protocol):
    def get(self, agent_id: str) -> AgentsRow | None: ...

    def listing(self, *, contains: str | None, enabled: bool | None) -> list[AgentsRow]:
        """By name. ``contains`` keeps the agents whose name or description contains it, as SQL
        ``LIKE`` matches (ASCII case-insensitive, ``%`` and ``_`` are wildcards)."""
        ...

    def count_by_role_template(self) -> dict[str, int]:
        """How many agents reference each role template; a template without one is absent."""
        ...

    def add(self, row: AgentsRow) -> None:
        """Raises ``ConstraintViolationError`` when the name is taken."""
        ...

    def update(self, agent_id: str, changes: AgentChanges, *, now: str) -> None:
        """Write ``changes`` (at least one) with ``updated_at = now``; ``ConstraintViolationError``
        when the new name is taken."""
        ...

    def record_test(self, agent_id: str, *, status: str, message: str, now: str) -> None:
        """The outcome of the last connection test; ``updated_at`` stays."""
        ...

    def clear_role_template(self, role_id: str) -> None:
        """Every agent that references the template stops referencing it."""
        ...

    def delete(self, agent_id: str) -> None:
        """Delete the agent; the boards that selected it lose it."""
        ...

    def sealed_keys(self) -> dict[str, str]:
        """The sealed provider key of every agent that has one, by agent id."""
        ...

    def reseal(self, agent_id: str, ciphertext: str) -> None:
        """Replace the sealed key; ``updated_at`` stays."""
        ...


class AgentLinkRepository(Protocol):
    """The agents each board selected (``board_agents``)."""

    def agent_ids(self, board_id: str) -> list[str]:
        """In the order they were selected (then by id)."""
        ...

    def by_board(self) -> dict[str, list[str]]:
        """Every board's selection, each in the order of ``agent_ids``."""
        ...

    def clear(self, board_id: str) -> None: ...

    def add(self, row: BoardAgentsRow) -> None: ...
