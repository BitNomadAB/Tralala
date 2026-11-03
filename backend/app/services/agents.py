"""Role templates and agent profiles: identity, connection, sealed credentials and role assignment.

Both services reach the registry only through the repositories and the registry unit of work
(``app/repositories``). The clock, the id source and the endpoint rule and probes
(``services.connections``) are passed in, with the real ones as defaults, so every rule here runs in
a unit test without a database or a network. Provider keys are sealed with ``core.secrets`` before
they are stored; a response carries only ``has_api_key`` and the hint.

This module is the public import path. It keeps ``AgentService`` and re-exports the use cases that
live beside it: role templates (``agents_roles``), connection tests (``agents_probe``) and the
sealing of provider keys (``agents_credentials``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import TypedDict
from uuid import uuid4

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..db.generated.registry import AgentsRow, BoardAgentsRow, RoleTemplatesRow
from ..repositories.agents import AgentChanges
from ..repositories.errors import ConstraintViolationError
from ..repositories.registry import RegistryRepositories, RegistryUnitOfWork
from ..schemas.agents import AgentCreate, AgentDuplicate, AgentTestRequest, AgentUpdate
from . import connections
from .agents_credentials import credential_changes, reseal_provider_keys
from .agents_probe import AgentEndpoints, ProbeOutcome, probe_connection
from .agents_roles import RoleTemplateEntry, RoleTemplateService

ROLE_PROMPT_LIMIT = 20_000


class AgentEntry(TypedDict):
    """An agent as the API returns it: never the sealed key or the override text."""

    id: str
    name: str
    description: str
    role_template_id: str | None
    connection_type: str
    base_url: str
    model: str | None
    api_key_hint: str | None
    temperature: float | None
    max_output_tokens: int | None
    timeout_seconds: int
    enabled: bool
    last_test_status: str | None
    last_test_message: str | None
    last_tested_at: str | None
    supports_json_schema: bool
    created_at: str
    updated_at: str
    role_template_name: str | None
    role_template_scope: str
    role_template_updated_at: str | None
    has_role_override: bool
    has_api_key: bool


class DirectoryEntry(TypedDict):
    """An enabled agent as an autocomplete needs it: no endpoint, model or credential hint."""

    id: str
    name: str
    role_template_id: str | None
    role_template_name: str | None
    role_template_scope: str


class AskableAgent(TypedDict):
    id: str
    name: str
    role_template_name: str | None


class AssignablePerson(TypedDict):
    id: str
    name: str
    type: str
    role: str


class EffectiveRole(TypedDict):
    agent_id: str
    agent_name: str
    role_template_id: str | None
    role_template_name: str | None
    role_template_updated_at: str | None
    template_system_prompt: str | None
    override_system_prompt: str | None
    system_prompt: str
    role_source: str


class RoleSnapshot(TypedDict):
    """What a discussion or run stores of the role it ran with; template edits never reach it."""

    agent_id: str
    agent_name: str
    role_template_id: str | None
    role_template_name: str | None
    role_template_updated_at: str | None
    role_source: str
    system_prompt: str
    system_prompt_sha256: str
    snapshot_at: str


def _new_id() -> str:
    return str(uuid4())


def _agent_entry(row: AgentsRow, roles: Mapping[str, RoleTemplatesRow]) -> AgentEntry:
    role = roles.get(row.role_template_id or "")
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "role_template_id": row.role_template_id,
        "connection_type": row.connection_type,
        "base_url": row.base_url,
        "model": row.model,
        "api_key_hint": row.api_key_hint,
        "temperature": row.temperature,
        "max_output_tokens": row.max_output_tokens,
        "timeout_seconds": row.timeout_seconds,
        "enabled": bool(row.enabled),
        "last_test_status": row.last_test_status,
        "last_test_message": row.last_test_message,
        "last_tested_at": row.last_tested_at,
        "supports_json_schema": bool(row.supports_json_schema),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "role_template_name": role.name if role else None,
        "role_template_scope": (role.scope if role else "") or "board",
        "role_template_updated_at": role.updated_at if role else None,
        "has_role_override": bool(row.role_prompt_override),
        "has_api_key": bool(row.api_key_ciphertext),
    }


def _role_map(repos: RegistryRepositories) -> dict[str, RoleTemplatesRow]:
    return {row.id: row for row in repos.role_templates.all()}


class AgentService:
    """Agent configurations: identity, connection, credentials and role assignment."""

    def __init__(
        self,
        settings: Settings,
        store: RegistryUnitOfWork,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
        endpoints: AgentEndpoints = connections,
    ) -> None:
        self.settings = settings
        self.store = store
        self._clock = clock
        self._new_id = new_id
        self._endpoints = endpoints

    # --- queries ---------------------------------------------------------------------------------

    def find_row(self, agent_id: str) -> AgentsRow | None:
        with self.store.reader() as repos:
            return repos.agents.get(agent_id)

    def get_row(self, agent_id: str) -> AgentsRow:
        row = self.find_row(agent_id)
        if row is None:
            raise NotFound("Agent not found")
        return row

    def get(self, agent_id: str) -> AgentEntry:
        with self.store.reader() as repos:
            row = repos.agents.get(agent_id)
            roles = _role_map(repos) if row is not None else {}
        if row is None:
            raise NotFound("Agent not found")
        return _agent_entry(row, roles)

    def list(self, *, q: str | None = None, enabled: bool | None = None) -> list[AgentEntry]:
        with self.store.reader() as repos:
            rows = repos.agents.listing(contains=q or None, enabled=enabled)
            roles = _role_map(repos)
        return [_agent_entry(row, roles) for row in rows]

    def directory(self) -> list[DirectoryEntry]:
        """Enabled agents as an autocomplete needs them: no endpoint, model or credential hint."""
        with self.store.reader() as repos:
            rows = repos.agents.listing(contains=None, enabled=True)
            roles = _role_map(repos)
        entries: list[DirectoryEntry] = []
        for row in rows:
            role = roles.get(row.role_template_id or "")
            entries.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "role_template_id": row.role_template_id,
                    "role_template_name": role.name if role else None,
                    "role_template_scope": (role.scope if role else "") or "board",
                }
            )
        return entries

    def assignable_people(self) -> list[AssignablePerson]:
        """Enabled people, as a worker needs them to assign a Ticket to someone.

        A token belongs to its own agent actor, so it cannot look people up elsewhere: this is the
        only list a worker token may read, and it carries no password, session or role detail
        beyond the role name an assignee list needs.
        """
        with self.store.reader() as repos:
            users = repos.users.all()
        return [
            {
                "id": user.actor.id,
                "name": user.actor.name,
                "type": "user",
                "role": user.credentials.role,
            }
            for user in users
            if user.actor.disabled_at is None
        ]

    def askable_agents(self, board_id: str) -> list[AskableAgent]:
        """Enabled board profiles a worker may ask, honouring the board's selection.

        A board that lists no agents keeps the documented "any board profile" behaviour, so an
        older board still answers.
        """
        selected = set(self.agent_ids(board_id))
        return [
            {
                "id": entry["id"],
                "name": entry["name"],
                "role_template_name": entry["role_template_name"],
            }
            for entry in self.directory()
            if entry["role_template_scope"] != "organisation"
            and (not selected or entry["id"] in selected)
        ]

    # --- role resolution (the architecture seam) -------------------------------------------------

    def effective_role(self, agent_id: str) -> EffectiveRole:
        """Current effective role for an agent.

        Templates are resolved at call time so central edits apply to *future* work; callers that
        need history must persist :meth:`role_snapshot` instead of this result.
        """
        with self.store.reader() as repos:
            row = repos.agents.get(agent_id)
            role_id = row.role_template_id if row is not None else None
            role = repos.role_templates.get(role_id) if role_id else None
        if row is None:
            raise NotFound("Agent not found")
        override = row.role_prompt_override
        if role is None and not override:
            raise ValidationFailure(
                "Agent has no usable role; assign a role template or a prompt override",
                details={"agent_id": agent_id},
            )
        return {
            "agent_id": row.id,
            "agent_name": row.name,
            "role_template_id": role.id if role else None,
            "role_template_name": role.name if role else None,
            "role_template_updated_at": role.updated_at if role else None,
            "template_system_prompt": role.system_prompt if role else None,
            "override_system_prompt": override,
            "system_prompt": override or (role.system_prompt if role else ""),
            "role_source": "override" if override else "template",
        }

    def role_snapshot(self, agent_id: str) -> RoleSnapshot:
        """Immutable copy stored with a discussion participant."""
        role = self.effective_role(agent_id)
        digest = hashlib.sha256(role["system_prompt"].encode("utf-8")).hexdigest()
        return {
            "agent_id": role["agent_id"],
            "agent_name": role["agent_name"],
            "role_template_id": role["role_template_id"],
            "role_template_name": role["role_template_name"],
            "role_template_updated_at": role["role_template_updated_at"],
            "role_source": role["role_source"],
            "system_prompt": role["system_prompt"],
            "system_prompt_sha256": digest,
            "snapshot_at": self._clock(),
        }

    # --- commands --------------------------------------------------------------------------------

    def _credential_changes(self, api_key: str | None) -> AgentChanges:
        return credential_changes(self.settings, api_key)

    def _validate_endpoint(self, url: str) -> str:
        return self._endpoints.validate_endpoint(
            url, allow_private=self.settings.agents_allow_private_endpoints
        )

    def _validate_role_reference(self, role_template_id: str | None, override: str | None) -> None:
        if role_template_id is None and not override:
            raise ValidationFailure(
                "Assign a role template or provide a role prompt override",
                details={"field": "role_template_id"},
            )
        if role_template_id is not None:
            with self.store.reader() as repos:
                role = repos.role_templates.get(role_template_id)
            if role is None:
                raise NotFound("Role template not found")

    def create(self, actor: ActorContext, payload: AgentCreate) -> AgentEntry:
        actor.require("agents:write")
        self._validate_role_reference(payload.role_template_id, payload.role_prompt_override)
        agent_id = self._new_id()
        now = self._clock()
        base_url = self._validate_endpoint(payload.base_url)
        credentials = self._credential_changes(payload.api_key)
        row = AgentsRow(
            id=agent_id,
            name=payload.name,
            description=payload.description,
            role_template_id=payload.role_template_id,
            role_prompt_override=payload.role_prompt_override,
            connection_type=payload.connection_type,
            base_url=base_url,
            model=payload.model,
            api_key_ciphertext=credentials.get("api_key_ciphertext"),
            api_key_hint=credentials.get("api_key_hint"),
            temperature=payload.temperature,
            max_output_tokens=payload.max_output_tokens,
            timeout_seconds=payload.timeout_seconds,
            enabled=1 if payload.enabled else 0,
            last_test_status=None,
            last_test_message=None,
            last_tested_at=None,
            created_at=now,
            updated_at=now,
            supports_json_schema=0,
        )
        try:
            with self.store.writer() as repos:
                repos.agents.add(row)
        except ConstraintViolationError as exc:
            raise Conflict(
                "An agent with this name already exists",
                code="agent_name_taken",
                details={"name": payload.name},
            ) from exc
        return self.get(agent_id)

    def update(self, actor: ActorContext, agent_id: str, payload: AgentUpdate) -> AgentEntry:
        actor.require("agents:write")
        current = self.get_row(agent_id)
        changes: AgentChanges = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.description is not None:
            changes["description"] = payload.description
        if payload.role_template_id is not None:
            changes["role_template_id"] = payload.role_template_id
        if payload.role_prompt_override is not None:
            changes["role_prompt_override"] = payload.role_prompt_override
        if payload.connection_type is not None:
            changes["connection_type"] = payload.connection_type
        if payload.model is not None:
            changes["model"] = payload.model
        if payload.temperature is not None:
            changes["temperature"] = payload.temperature
        if payload.max_output_tokens is not None:
            changes["max_output_tokens"] = payload.max_output_tokens
        if payload.timeout_seconds is not None:
            changes["timeout_seconds"] = payload.timeout_seconds
        if "role_template_id" in changes or "role_prompt_override" in changes:
            self._validate_role_reference(
                changes.get("role_template_id", current.role_template_id),
                changes.get("role_prompt_override", current.role_prompt_override),
            )
        if payload.base_url is not None:
            changes["base_url"] = self._validate_endpoint(payload.base_url)
        if payload.enabled is not None:
            changes["enabled"] = 1 if payload.enabled else 0
        if payload.api_key is not None:
            changes.update(self._credential_changes(payload.api_key))
        if payload.clear_api_key:
            changes["api_key_ciphertext"] = None
            changes["api_key_hint"] = None
        if not changes:
            return self.get(agent_id)
        try:
            with self.store.writer() as repos:
                repos.agents.update(agent_id, changes, now=self._clock())
        except ConstraintViolationError as exc:
            raise Conflict(
                "An agent with this name already exists",
                code="agent_name_taken",
                details={"name": changes.get("name", current.name)},
            ) from exc
        return self.get(agent_id)

    def duplicate(self, actor: ActorContext, agent_id: str, payload: AgentDuplicate) -> AgentEntry:
        actor.require("agents:write")
        row = self.get_row(agent_id)
        name = (payload.name or f"{row.name} (copy)").strip()
        now = self._clock()
        copy = row.__replace__(
            id=self._new_id(),
            name=name,
            # Credentials are intentionally not cloned; the copy must be tested again.
            api_key_ciphertext=None,
            api_key_hint=None,
            last_test_status=None,
            last_test_message=None,
            last_tested_at=None,
            supports_json_schema=0,
            created_at=now,
            updated_at=now,
        )
        try:
            with self.store.writer() as repos:
                repos.agents.add(copy)
        except ConstraintViolationError as exc:
            raise Conflict(
                "An agent with this name already exists",
                code="agent_name_taken",
                details={"name": name},
            ) from exc
        return self.get(copy.id)

    def delete(self, actor: ActorContext, agent_id: str) -> None:
        actor.require("agents:admin")
        self.get_row(agent_id)
        with self.store.writer() as repos:
            repos.agents.delete(agent_id)

    # --- board membership ------------------------------------------------------------------------

    def validate_ids(self, agent_ids: list[str]) -> None:
        """Every id must exist and be a board profile before it is written to a board."""
        with self.store.reader() as repos:
            for agent_id in agent_ids:
                agent = repos.agents.get(agent_id)
                if agent is None:
                    raise NotFound("Agent not found", code="agent_not_found")
                role_id = agent.role_template_id
                role = repos.role_templates.get(role_id) if role_id else None
                if role is not None and role.scope == "organisation":
                    raise ValidationFailure(
                        "An organisation-wide profile works across boards and is not a board agent",
                        code="agent_scope_organisation",
                        details={"agent_id": agent_id},
                    )

    def set_board_agents(self, board_id: str, agent_ids: list[str]) -> None:
        """Replace a board's selection; called after the board row exists."""
        self.validate_ids(list(agent_ids))
        now = self._clock()
        with self.store.writer() as repos:
            repos.agent_links.clear(board_id)
            for agent_id in dict.fromkeys(agent_ids):
                repos.agent_links.add(
                    BoardAgentsRow(board_id=board_id, agent_id=agent_id, created_at=now)
                )

    def agent_ids(self, board_id: str) -> list[str]:
        with self.store.reader() as repos:
            return repos.agent_links.agent_ids(board_id)

    def agent_ids_for_boards(self) -> dict[str, list[str]]:
        with self.store.reader() as repos:
            return repos.agent_links.by_board()

    # --- secret rotation -------------------------------------------------------------------------

    def reseal_credentials(self) -> int:
        """Re-seal provider keys that were sealed with TRALALA_PREVIOUS_SECRET_KEY.

        Called once at startup: after a secret change every key moves to the new secret, so the
        previous one can be dropped from the environment afterwards.
        """
        return reseal_provider_keys(self.settings, self.store)

    # --- connection testing ----------------------------------------------------------------------

    def test(self, actor: ActorContext, agent_id: str, payload: AgentTestRequest) -> ProbeOutcome:
        """Probe a stored agent and record the outcome on it.

        The outcome includes whether the model took a JSON schema as the answer's format, which a
        generation reads (``runtime.call_completion``); every test writes it afresh, so a failed
        test or one without a model call leaves the agent without it until a test shows it again.
        """
        actor.require("agents:write")
        row = self.get_row(agent_id)
        result = self._probe(payload, row=row, agent_id=agent_id)
        with self.store.writer() as repos:
            repos.agents.record_test(
                agent_id,
                status=result["status"],
                message=result["message"][:500],
                now=self._clock(),
                supports_json_schema=result["supports_json_schema"],
            )
        return result

    def probe(self, actor: ActorContext, payload: AgentTestRequest) -> ProbeOutcome:
        """Probe a configuration that has not been saved yet.

        The form asks before saving, because a connection that cannot answer is not worth a row in
        the registry. Nothing is persisted here, so there is no `last_test_*` to update.
        """
        actor.require("agents:write")
        return self._probe(payload, row=None, agent_id=None)

    def _probe(
        self,
        payload: AgentTestRequest,
        *,
        row: AgentsRow | None,
        agent_id: str | None,
    ) -> ProbeOutcome:
        return probe_connection(self.settings, self._endpoints, payload, row=row, agent_id=agent_id)


__all__ = [
    "ROLE_PROMPT_LIMIT",
    "AgentEndpoints",
    "AgentEntry",
    "AgentService",
    "AskableAgent",
    "AssignablePerson",
    "DirectoryEntry",
    "EffectiveRole",
    "ProbeOutcome",
    "RoleSnapshot",
    "RoleTemplateEntry",
    "RoleTemplateService",
]
