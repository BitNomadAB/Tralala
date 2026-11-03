"""Role templates and agent profiles: identity, connection, sealed credentials and role assignment.

Both services reach the registry only through the repositories and the registry unit of work
(``app/repositories``). The clock, the id source and the endpoint rule and probes
(``services.connections``) are passed in, with the real ones as defaults, so every rule here runs in
a unit test without a database or a network. Provider keys are sealed with ``core.secrets`` before
they are stored; a response carries only ``has_api_key`` and the hint.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from typing import NotRequired, Protocol, TypedDict
from uuid import uuid4

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..core.secrets import CredentialError, open_secret, open_secret_state, seal_secret, secret_hint
from ..db.generated.registry import AgentsRow, BoardAgentsRow, RoleTemplatesRow
from ..repositories.agents import AgentChanges, RoleTemplateChanges
from ..repositories.errors import ConstraintViolationError
from ..repositories.registry import RegistryRepositories, RegistryUnitOfWork
from ..schemas.agents import (
    AgentCreate,
    AgentDuplicate,
    AgentTestRequest,
    AgentUpdate,
    RoleTemplateCreate,
    RoleTemplateDuplicate,
    RoleTemplateUpdate,
)
from . import connections
from .connections import CompletionProbe, EndpointProbe
from .role_defaults import BUILTIN_ROLES

ROLE_PROMPT_LIMIT = 20_000

logger = logging.getLogger("tralala.agents")


class RoleTemplateEntry(TypedDict):
    """A role template as the API returns it: never its factory copy, only whether it differs."""

    id: str
    name: str
    description: str
    system_prompt: str
    builtin_key: str | None
    created_at: str
    updated_at: str
    scope: str
    built_in: bool
    customized: bool
    agent_count: int


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


class ProbeOutcome(TypedDict):
    """A connection test: the endpoint probe, plus the model call when a model was named.

    ``supports_json_schema`` is what the model call found (``connections.probe_completion``), and
    false when no model call was made or it failed.
    """

    ok: bool
    status: str
    message: str
    latency_ms: int
    models: list[str]
    supports_json_schema: bool
    completion: NotRequired[CompletionProbe]


class AgentEndpoints(Protocol):
    """The endpoint rule and the probes; ``services.connections`` is the real one."""

    def validate_endpoint(self, url: str, *, allow_private: bool) -> str: ...

    def probe_openai_compatible(
        self, base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
    ) -> EndpointProbe: ...

    def probe_a2a(
        self, base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
    ) -> EndpointProbe: ...

    def probe_completion(
        self,
        base_url: str,
        *,
        model: str,
        api_key: str | None,
        timeout: float,
        allow_private: bool,
    ) -> CompletionProbe: ...


def _new_id() -> str:
    return str(uuid4())


def _role_entry(row: RoleTemplatesRow, *, agent_count: int) -> RoleTemplateEntry:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "system_prompt": row.system_prompt,
        "builtin_key": row.builtin_key,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "scope": row.scope,
        "built_in": bool(row.built_in),
        "customized": row.system_prompt != row.default_system_prompt,
        "agent_count": agent_count,
    }


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


class RoleTemplateService:
    """Central role definitions. Agents reference them; discussions snapshot them."""

    def __init__(
        self,
        store: RegistryUnitOfWork,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.store = store
        self._clock = clock
        self._new_id = new_id

    # --- seeding ---------------------------------------------------------------------------------

    def seed_defaults(self) -> int:
        """Insert missing built-ins and keep unedited ones in step with the seed.

        A built-in the user has not touched follows the factory text, so a prompt rewrite reaches
        an existing installation. A customized built-in keeps its own prompt; only its factory copy
        moves, which is what "restore defaults" restores. Scope always follows the seed.
        """
        created = 0
        now = self._clock()
        with self.store.writer() as repos:
            for role in BUILTIN_ROLES:
                existing = repos.role_templates.by_builtin_key(role["key"])
                if existing is not None:
                    untouched = existing.system_prompt == existing.default_system_prompt
                    prompt_moves = untouched and existing.system_prompt != role["prompt"]
                    changes: RoleTemplateChanges = {
                        "system_prompt": role["prompt"] if untouched else existing.system_prompt,
                        "default_system_prompt": role["prompt"],
                        "scope": role["scope"],
                    }
                    stamp = now if prompt_moves else existing.updated_at
                    repos.role_templates.update(existing.id, changes, now=stamp)
                    continue
                repos.role_templates.add(
                    RoleTemplatesRow(
                        id=self._new_id(),
                        name=role["name"],
                        description=role["description"],
                        system_prompt=role["prompt"],
                        default_system_prompt=role["prompt"],
                        built_in=1,
                        builtin_key=role["key"],
                        created_at=now,
                        updated_at=now,
                        scope=role["scope"],
                    )
                )
                created += 1
        return created

    # --- queries ---------------------------------------------------------------------------------

    def list(self) -> list[RoleTemplateEntry]:
        with self.store.reader() as repos:
            rows = repos.role_templates.all()
            counts = repos.agents.count_by_role_template()
        return [_role_entry(row, agent_count=counts.get(row.id, 0)) for row in rows]

    def find(self, role_id: str) -> RoleTemplateEntry | None:
        with self.store.reader() as repos:
            row = repos.role_templates.get(role_id)
            counts = repos.agents.count_by_role_template() if row is not None else {}
        if row is None:
            return None
        return _role_entry(row, agent_count=counts.get(row.id, 0))

    def get(self, role_id: str) -> RoleTemplateEntry:
        role = self.find(role_id)
        if role is None:
            raise NotFound("Role template not found")
        return role

    # --- commands --------------------------------------------------------------------------------

    def create(self, actor: ActorContext, payload: RoleTemplateCreate) -> RoleTemplateEntry:
        actor.require("agents:write")
        return self._insert(
            name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
            scope="board",
        )

    def _insert(
        self, *, name: str, description: str, system_prompt: str, scope: str
    ) -> RoleTemplateEntry:
        """A template a person made: never built-in, its own prompt is its factory copy."""
        role_id = self._new_id()
        now = self._clock()
        row = RoleTemplatesRow(
            id=role_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            default_system_prompt=system_prompt,
            built_in=0,
            builtin_key=None,
            created_at=now,
            updated_at=now,
            scope=scope,
        )
        try:
            with self.store.writer() as repos:
                repos.role_templates.add(row)
        except ConstraintViolationError as exc:
            raise Conflict(
                "A role template with this name already exists",
                code="role_template_name_taken",
                details={"name": name},
            ) from exc
        return self.get(role_id)

    def update(
        self, actor: ActorContext, role_id: str, payload: RoleTemplateUpdate
    ) -> RoleTemplateEntry:
        actor.require("agents:write")
        current = self.get(role_id)
        changes: RoleTemplateChanges = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.description is not None:
            changes["description"] = payload.description
        if payload.system_prompt is not None:
            changes["system_prompt"] = payload.system_prompt
        if not changes:
            return current
        try:
            with self.store.writer() as repos:
                repos.role_templates.update(role_id, changes, now=self._clock())
        except ConstraintViolationError as exc:
            raise Conflict(
                "A role template with this name already exists",
                code="role_template_name_taken",
                details={"name": changes.get("name", current["name"])},
            ) from exc
        return self.get(role_id)

    def duplicate(
        self, actor: ActorContext, role_id: str, payload: RoleTemplateDuplicate
    ) -> RoleTemplateEntry:
        actor.require("agents:write")
        current = self.get(role_id)
        name = (payload.name or f"{current['name']} (copy)").strip()
        return self._insert(
            name=name,
            description=current["description"],
            system_prompt=current["system_prompt"],
            scope=current["scope"] or "board",
        )

    def restore_defaults(self, actor: ActorContext, role_id: str) -> RoleTemplateEntry:
        actor.require("agents:admin")
        current = self.get(role_id)
        if not current["built_in"]:
            raise Conflict(
                "Only built-in role templates have factory defaults",
                code="role_template_not_builtin",
            )
        with self.store.writer() as repos:
            row = repos.role_templates.get(role_id)
            if row is not None:
                factory: RoleTemplateChanges = {"system_prompt": row.default_system_prompt}
                repos.role_templates.update(role_id, factory, now=self._clock())
        return self.get(role_id)

    def delete(self, actor: ActorContext, role_id: str) -> None:
        actor.require("agents:admin")
        current = self.get(role_id)
        if current["built_in"]:
            raise Conflict(
                "Built-in role templates can be customized or duplicated but not deleted",
                code="role_template_builtin",
            )
        with self.store.writer() as repos:
            repos.agents.clear_role_template(role_id)
            repos.role_templates.delete(role_id)


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
        """``None`` leaves the stored key alone; an empty key removes it; any other is sealed."""
        if api_key is None:
            return {}
        if not api_key:
            return {"api_key_ciphertext": None, "api_key_hint": None}
        return {
            "api_key_ciphertext": seal_secret(self.settings, api_key),
            "api_key_hint": secret_hint(api_key),
        }

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
        with self.store.reader() as repos:
            sealed = repos.agents.sealed_keys()
        resealed: dict[str, str] = {}
        for agent_id, ciphertext in sealed.items():
            try:
                value, current = open_secret_state(self.settings, ciphertext)
            except CredentialError:
                logger.warning(
                    "agent %s has a credential that no configured secret can open", agent_id
                )
                continue
            if not current:
                resealed[agent_id] = seal_secret(self.settings, value)
        if resealed:
            with self.store.writer() as repos:
                for agent_id, ciphertext in resealed.items():
                    repos.agents.reseal(agent_id, ciphertext)
        return len(resealed)

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
        connection_type = payload.connection_type or (
            row.connection_type if row else "openai_compatible"
        )
        base_url = payload.base_url or (row.base_url if row else "")
        if not base_url:
            raise ValidationFailure(
                "An endpoint is required to test a connection",
                details={"field": "base_url"},
            )
        api_key = payload.api_key
        if payload.no_api_key:
            # Explicit: this endpoint is called without a credential, stored one or not.
            api_key = None
        elif api_key is None and row is not None and row.api_key_ciphertext:
            try:
                api_key = open_secret(self.settings, row.api_key_ciphertext)
            except CredentialError:
                api_key = None
        fallback_timeout = row.timeout_seconds if row else 30
        timeout = float(payload.timeout_seconds or fallback_timeout)
        fallback_model = row.model if row else ""
        selected_model = (payload.model or fallback_model or "").strip()
        allow_private = self.settings.agents_allow_private_endpoints
        validated = self._validate_endpoint(base_url)

        # One pair of events per attempt: an operator reading the log can tell a refused credential
        # from a model the endpoint does not serve, without the request or the key ever appearing.
        self._log_probe(
            "agent_probe_started",
            agent_id=agent_id,
            connection_type=connection_type,
            endpoint=validated,
            model=selected_model,
            has_api_key=bool(api_key),
            timeout_seconds=timeout,
        )
        probe = (
            self._endpoints.probe_openai_compatible
            if connection_type == "openai_compatible"
            else self._endpoints.probe_a2a
        )
        try:
            found = probe(validated, api_key=api_key, timeout=timeout, allow_private=allow_private)
        except Exception as exc:  # the probe reports, it does not raise
            self._log_probe(
                "agent_probe_failed",
                agent_id=agent_id,
                connection_type=connection_type,
                endpoint=validated,
                reason=type(exc).__name__,
            )
            raise
        result: ProbeOutcome = {
            "ok": found["ok"],
            "status": found["status"],
            "message": found["message"],
            "latency_ms": found["latency_ms"],
            "models": found["models"],
            "supports_json_schema": False,
        }

        completion: CompletionProbe | None = None
        if result["ok"] and connection_type == "openai_compatible" and selected_model:
            completion = self._endpoints.probe_completion(
                validated,
                model=selected_model,
                api_key=api_key,
                timeout=timeout,
                allow_private=allow_private,
            )
            result["completion"] = completion
            if completion["ok"]:
                result["supports_json_schema"] = completion["supports_json_schema"]
                result["message"] = (
                    f"{result['message']}; model {selected_model} answered "
                    f"in {completion['latency_ms']} ms"
                )
            else:
                # The list answered, the model call did not: say so, and keep the model list so the
                # form can still offer what the endpoint knows.
                result["ok"] = False
                result["status"] = completion["status"]
                result["message"] = (
                    f"Endpoint answers, but the model call failed. {completion['message']}"
                )

        self._log_probe(
            "agent_probe_finished" if result["ok"] else "agent_probe_failed",
            agent_id=agent_id,
            connection_type=connection_type,
            endpoint=validated,
            model=selected_model,
            status=result["status"],
            latency_ms=result["latency_ms"],
            models=len(result["models"]),
            completion_status=completion["status"] if completion else None,
            reason=None if result["ok"] else result["message"][:200],
        )
        return result

    @staticmethod
    def _log_probe(event: str, **fields: object) -> None:
        started_or_finished = event in {"agent_probe_started", "agent_probe_finished"}
        level = logging.INFO if started_or_finished else logging.WARNING
        logger.log(level, event, extra=fields)


__all__ = ["AgentService", "RoleTemplateService"]
