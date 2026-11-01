from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..schemas.agents import (
    AgentCreate,
    AgentDuplicate,
    AgentTestRequest,
    AgentUpdate,
    RoleTemplateCreate,
    RoleTemplateDuplicate,
    RoleTemplateUpdate,
)
from ..storage.registry import Registry
from ..storage.sqlite import utcnow
from . import connections
from .role_defaults import BUILTIN_ROLES

ROLE_PROMPT_LIMIT = 20_000

logger = logging.getLogger("tralala.agents")


def _serialize_role(row: dict[str, Any], *, agent_count: int = 0) -> dict[str, Any]:
    entry = dict(row)
    entry["built_in"] = bool(entry.pop("built_in", 0))
    entry["default_system_prompt"] = entry.get("default_system_prompt") or ""
    entry["customized"] = entry["system_prompt"] != entry["default_system_prompt"]
    entry["agent_count"] = agent_count
    entry.pop("default_system_prompt", None)
    return entry


class RoleTemplateService:
    """Central role definitions. Agents reference them; discussions snapshot them."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    # --- seeding ---------------------------------------------------------------

    def seed_defaults(self) -> int:
        """Insert missing built-ins. Existing rows are never overwritten."""
        created = 0
        now = utcnow()
        with self.registry.connect() as conn:
            for role in BUILTIN_ROLES:
                existing = conn.execute(
                    text("SELECT id FROM role_templates WHERE builtin_key = :key"),
                    {"key": role["key"]},
                ).first()
                if existing is not None:
                    continue
                conn.execute(
                    text(
                        "INSERT INTO role_templates"
                        " (id, name, description, system_prompt, default_system_prompt, built_in,"
                        "  builtin_key, created_at, updated_at)"
                        " VALUES (:id, :name, :description, :prompt, :prompt, 1, :key, :now, :now)"
                    ),
                    {
                        "id": str(uuid4()),
                        "name": role["name"],
                        "description": role["description"],
                        "prompt": role["prompt"],
                        "key": role["key"],
                        "now": now,
                    },
                )
                created += 1
        return created

    # --- queries ---------------------------------------------------------------

    def _agent_counts(self) -> dict[str, int]:
        rows = self.registry.read(
            "SELECT role_template_id, COUNT(*) AS total FROM agents"
            " WHERE role_template_id IS NOT NULL GROUP BY role_template_id"
        )
        return {row["role_template_id"]: int(row["total"]) for row in rows}

    def serialize(
        self, row: dict[str, Any], counts: dict[str, int] | None = None
    ) -> dict[str, Any]:
        counts = counts if counts is not None else self._agent_counts()
        return _serialize_role(row, agent_count=counts.get(row["id"], 0))

    def list(self) -> list[dict[str, Any]]:
        rows = self.registry.read("SELECT * FROM role_templates ORDER BY built_in DESC, name")
        counts = self._agent_counts()
        return [self.serialize(row, counts) for row in rows]

    def find(self, role_id: str) -> dict[str, Any] | None:
        row = self.registry.read_one("SELECT * FROM role_templates WHERE id = :id", {"id": role_id})
        return self.serialize(row) if row else None

    def get(self, role_id: str) -> dict[str, Any]:
        role = self.find(role_id)
        if role is None:
            raise NotFound("Role template not found")
        return role

    # --- commands --------------------------------------------------------------

    def create(self, actor: ActorContext, payload: RoleTemplateCreate) -> dict[str, Any]:
        actor.require("agents:write")
        return self._insert(
            name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
            built_in=False,
            builtin_key=None,
        )

    def _insert(
        self,
        *,
        name: str,
        description: str,
        system_prompt: str,
        built_in: bool,
        builtin_key: str | None,
    ) -> dict[str, Any]:
        role_id = str(uuid4())
        now = utcnow()
        try:
            with self.registry.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO role_templates"
                        " (id, name, description, system_prompt, default_system_prompt, built_in,"
                        "  builtin_key, created_at, updated_at)"
                        " VALUES (:id, :name, :description, :prompt, :prompt, :built_in, :key,"
                        "         :now, :now)"
                    ),
                    {
                        "id": role_id,
                        "name": name,
                        "description": description,
                        "prompt": system_prompt,
                        "built_in": 1 if built_in else 0,
                        "key": builtin_key,
                        "now": now,
                    },
                )
        except IntegrityError as exc:
            raise Conflict(
                "A role template with this name already exists",
                code="role_template_name_taken",
                details={"name": name},
            ) from exc
        return self.get(role_id)

    def update(
        self, actor: ActorContext, role_id: str, payload: RoleTemplateUpdate
    ) -> dict[str, Any]:
        actor.require("agents:write")
        current = self.get(role_id)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            return current
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        try:
            with self.registry.connect() as conn:
                conn.execute(
                    text(
                        f"UPDATE role_templates SET {assignments}, updated_at = :updated_at"
                        " WHERE id = :id"
                    ),
                    {**updates, "updated_at": utcnow(), "id": role_id},
                )
        except IntegrityError as exc:
            raise Conflict(
                "A role template with this name already exists",
                code="role_template_name_taken",
                details={"name": updates.get("name", current["name"])},
            ) from exc
        return self.get(role_id)

    def duplicate(
        self, actor: ActorContext, role_id: str, payload: RoleTemplateDuplicate
    ) -> dict[str, Any]:
        actor.require("agents:write")
        current = self.get(role_id)
        name = (payload.name or f"{current['name']} (copy)").strip()
        return self._insert(
            name=name,
            description=current["description"],
            system_prompt=current["system_prompt"],
            built_in=False,
            builtin_key=None,
        )

    def restore_defaults(self, actor: ActorContext, role_id: str) -> dict[str, Any]:
        actor.require("agents:admin")
        current = self.get(role_id)
        if not current["built_in"]:
            raise Conflict(
                "Only built-in role templates have factory defaults",
                code="role_template_not_builtin",
            )
        with self.registry.connect() as conn:
            conn.execute(
                text(
                    "UPDATE role_templates SET system_prompt = default_system_prompt,"
                    " updated_at = :now WHERE id = :id"
                ),
                {"now": utcnow(), "id": role_id},
            )
        return self.get(role_id)

    def delete(self, actor: ActorContext, role_id: str) -> None:
        actor.require("agents:admin")
        current = self.get(role_id)
        if current["built_in"]:
            raise Conflict(
                "Built-in role templates can be customized or duplicated but not deleted",
                code="role_template_builtin",
            )
        with self.registry.connect() as conn:
            conn.execute(
                text("UPDATE agents SET role_template_id = NULL WHERE role_template_id = :id"),
                {"id": role_id},
            )
            conn.execute(text("DELETE FROM role_templates WHERE id = :id"), {"id": role_id})


class AgentService:
    """Agent configurations: identity, connection, credentials and role assignment."""

    def __init__(self, settings: Any, registry: Registry, roles: RoleTemplateService) -> None:
        self.settings = settings
        self.registry = registry
        self.roles = roles

    # --- serialization ---------------------------------------------------------

    def serialize(self, row: dict[str, Any], roles: dict[str, dict[str, Any]]) -> dict[str, Any]:
        entry = dict(row)
        entry.pop("api_key_ciphertext", None)
        role = roles.get(str(row.get("role_template_id") or ""))
        entry["role_template_name"] = role["name"] if role else None
        entry["role_template_updated_at"] = role["updated_at"] if role else None
        entry["has_role_override"] = bool(row.get("role_prompt_override"))
        entry["has_api_key"] = bool(row.get("api_key_ciphertext"))
        entry["api_key_hint"] = row.get("api_key_hint")
        entry["enabled"] = bool(row.get("enabled"))
        entry.pop("role_prompt_override", None)
        return entry

    def _role_map(self) -> dict[str, dict[str, Any]]:
        return {role["id"]: role for role in self.roles.list()}

    def find_row(self, agent_id: str) -> dict[str, Any] | None:
        return self.registry.read_one("SELECT * FROM agents WHERE id = :id", {"id": agent_id})

    def get(self, agent_id: str) -> dict[str, Any]:
        row = self.find_row(agent_id)
        if row is None:
            raise NotFound("Agent not found")
        return self.serialize(row, self._role_map())

    def get_row(self, agent_id: str) -> dict[str, Any]:
        row = self.find_row(agent_id)
        if row is None:
            raise NotFound("Agent not found")
        return row

    def list(self, *, q: str | None = None, enabled: bool | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if q:
            clauses.append("(name LIKE :q OR description LIKE :q)")
            params["q"] = f"%{q}%"
        if enabled is not None:
            clauses.append("enabled = :enabled")
            params["enabled"] = 1 if enabled else 0
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.registry.read(f"SELECT * FROM agents{where} ORDER BY name", params)
        roles = self._role_map()
        return [self.serialize(row, roles) for row in rows]

    def directory(self) -> list[dict[str, Any]]:
        """Enabled agents as an autocomplete needs them: no endpoint, model or credential hint."""
        roles = self._role_map()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "role_template_id": row.get("role_template_id"),
                "role_template_name": (
                    roles.get(str(row.get("role_template_id") or "")) or {}
                ).get("name"),
            }
            for row in self.registry.read(
                "SELECT id, name, role_template_id FROM agents WHERE enabled = 1 ORDER BY name"
            )
        ]

    # --- role resolution (the architecture seam) -------------------------------

    def effective_role(self, agent_id: str) -> dict[str, Any]:
        """Current effective role for an agent.

        Templates are resolved at call time so central edits apply to *future* work; callers that
        need history must persist :meth:`role_snapshot` instead of this result.
        """
        row = self.get_row(agent_id)
        role = None
        if row.get("role_template_id"):
            role = self.roles.find(str(row["role_template_id"]))
        override = row.get("role_prompt_override")
        if role is None and not override:
            raise ValidationFailure(
                "Agent has no usable role; assign a role template or a prompt override",
                details={"agent_id": agent_id},
            )
        return {
            "agent_id": row["id"],
            "agent_name": row["name"],
            "role_template_id": role["id"] if role else None,
            "role_template_name": role["name"] if role else None,
            "role_template_updated_at": role["updated_at"] if role else None,
            "template_system_prompt": role["system_prompt"] if role else None,
            "override_system_prompt": override,
            "system_prompt": override or (role["system_prompt"] if role else ""),
            "role_source": "override" if override else "template",
        }

    def role_snapshot(self, agent_id: str) -> dict[str, Any]:
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
            "snapshot_at": utcnow(),
        }

    # --- commands --------------------------------------------------------------

    def _credential_columns(self, api_key: str | None) -> dict[str, Any]:
        from ..core.secrets import seal_secret, secret_hint

        if api_key is None:
            return {}
        if not api_key:
            return {"api_key_ciphertext": None, "api_key_hint": None}
        return {
            "api_key_ciphertext": seal_secret(self.settings, api_key),
            "api_key_hint": secret_hint(api_key),
        }

    def _validate_role_reference(self, role_template_id: str | None, override: str | None) -> None:
        if role_template_id is None and not override:
            raise ValidationFailure(
                "Assign a role template or provide a role prompt override",
                details={"field": "role_template_id"},
            )
        if role_template_id is not None:
            self.roles.get(role_template_id)

    def create(self, actor: ActorContext, payload: AgentCreate) -> dict[str, Any]:
        actor.require("agents:write")
        self._validate_role_reference(payload.role_template_id, payload.role_prompt_override)
        agent_id = str(uuid4())
        now = utcnow()
        values: dict[str, Any] = {
            "id": agent_id,
            "name": payload.name,
            "description": payload.description,
            "role_template_id": payload.role_template_id,
            "role_prompt_override": payload.role_prompt_override,
            "connection_type": payload.connection_type,
            "base_url": connections.validate_endpoint(
                payload.base_url, allow_private=self.settings.agents_allow_private_endpoints
            ),
            "model": payload.model,
            "temperature": payload.temperature,
            "max_output_tokens": payload.max_output_tokens,
            "timeout_seconds": payload.timeout_seconds,
            "enabled": 1 if payload.enabled else 0,
            "created_at": now,
            "updated_at": now,
            **self._credential_columns(payload.api_key),
        }
        columns = ", ".join(values)
        placeholders = ", ".join(f":{key}" for key in values)
        try:
            with self.registry.connect() as conn:
                conn.execute(
                    text(f"INSERT INTO agents ({columns}) VALUES ({placeholders})"), values
                )
        except IntegrityError as exc:
            raise Conflict(
                "An agent with this name already exists",
                code="agent_name_taken",
                details={"name": payload.name},
            ) from exc
        return self.get(agent_id)

    def update(self, actor: ActorContext, agent_id: str, payload: AgentUpdate) -> dict[str, Any]:
        actor.require("agents:write")
        current = self.get_row(agent_id)
        updates: dict[str, Any] = payload.model_dump(exclude_none=True)
        updates.pop("clear_api_key", None)
        if "role_template_id" in updates or "role_prompt_override" in updates:
            self._validate_role_reference(
                updates.get("role_template_id", current.get("role_template_id")),
                updates.get("role_prompt_override", current.get("role_prompt_override")),
            )
        if "base_url" in updates:
            updates["base_url"] = connections.validate_endpoint(
                updates["base_url"], allow_private=self.settings.agents_allow_private_endpoints
            )
        if "enabled" in updates:
            updates["enabled"] = 1 if updates["enabled"] else 0
        if "api_key" in updates:
            key = updates.pop("api_key")
            updates.update(self._credential_columns(key))
        if payload.clear_api_key:
            updates.update({"api_key_ciphertext": None, "api_key_hint": None})
        if not updates:
            return self.get(agent_id)
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        try:
            with self.registry.connect() as conn:
                conn.execute(
                    text(
                        f"UPDATE agents SET {assignments}, updated_at = :updated_at"
                        " WHERE id = :id"
                    ),
                    {**updates, "updated_at": utcnow(), "id": agent_id},
                )
        except IntegrityError as exc:
            raise Conflict(
                "An agent with this name already exists",
                code="agent_name_taken",
                details={"name": updates.get("name", current["name"])},
            ) from exc
        return self.get(agent_id)

    def duplicate(
        self, actor: ActorContext, agent_id: str, payload: AgentDuplicate
    ) -> dict[str, Any]:
        actor.require("agents:write")
        row = self.get_row(agent_id)
        name = (payload.name or f"{row['name']} (copy)").strip()
        values = {
            "id": str(uuid4()),
            "name": name,
            "description": row["description"],
            "role_template_id": row["role_template_id"],
            "role_prompt_override": row["role_prompt_override"],
            "connection_type": row["connection_type"],
            "base_url": row["base_url"],
            "model": row["model"],
            "temperature": row["temperature"],
            "max_output_tokens": row["max_output_tokens"],
            "timeout_seconds": row["timeout_seconds"],
            "enabled": row["enabled"],
            "created_at": utcnow(),
            "updated_at": utcnow(),
            # Credentials are intentionally not cloned; the copy must be tested again.
            "api_key_ciphertext": None,
            "api_key_hint": None,
        }
        columns = ", ".join(values)
        placeholders = ", ".join(f":{key}" for key in values)
        try:
            with self.registry.connect() as conn:
                conn.execute(
                    text(f"INSERT INTO agents ({columns}) VALUES ({placeholders})"), values
                )
        except IntegrityError as exc:
            raise Conflict(
                "An agent with this name already exists",
                code="agent_name_taken",
                details={"name": name},
            ) from exc
        return self.get(values["id"])

    def delete(self, actor: ActorContext, agent_id: str) -> None:
        actor.require("agents:admin")
        self.get_row(agent_id)
        with self.registry.connect() as conn:
            conn.execute(text("DELETE FROM agents WHERE id = :id"), {"id": agent_id})

    # --- secret rotation -------------------------------------------------------

    def reseal_credentials(self) -> int:
        """Re-seal provider keys that were sealed with TRALALA_PREVIOUS_SECRET_KEY.

        Called once at startup: after a secret change every key moves to the new secret, so the
        previous one can be dropped from the environment afterwards.
        """
        from ..core.secrets import CredentialError, open_secret_state, seal_secret

        rows = self.registry.read(
            "SELECT id, api_key_ciphertext FROM agents WHERE api_key_ciphertext IS NOT NULL"
        )
        resealed = 0
        for row in rows:
            try:
                value, current = open_secret_state(self.settings, row["api_key_ciphertext"])
            except CredentialError:
                logger.warning(
                    "agent %s has a credential that no configured secret can open", row["id"]
                )
                continue
            if current:
                continue
            resealed += 1
            with self.registry.connect() as conn:
                conn.execute(
                    text("UPDATE agents SET api_key_ciphertext = :value WHERE id = :id"),
                    {"value": seal_secret(self.settings, value), "id": row["id"]},
                )
        return resealed

    # --- connection testing ----------------------------------------------------

    def test(
        self, actor: ActorContext, agent_id: str, payload: AgentTestRequest
    ) -> dict[str, Any]:
        actor.require("agents:write")
        from ..core.secrets import CredentialError, open_secret

        row = self.get_row(agent_id)
        overrides = payload.model_dump(exclude_none=True)
        connection_type = overrides.get("connection_type", row["connection_type"])
        base_url = overrides.get("base_url", row["base_url"])
        api_key: str | None = overrides.get("api_key")
        if api_key is None and row.get("api_key_ciphertext"):
            try:
                api_key = open_secret(self.settings, row["api_key_ciphertext"])
            except CredentialError:
                api_key = None
        timeout = float(overrides.get("timeout_seconds", row["timeout_seconds"]))
        validated = connections.validate_endpoint(
            base_url, allow_private=self.settings.agents_allow_private_endpoints
        )
        probe = (
            connections.probe_openai_compatible
            if connection_type == "openai_compatible"
            else connections.probe_a2a
        )
        result = probe(validated, api_key=api_key, timeout=timeout)
        with self.registry.connect() as conn:
            conn.execute(
                text(
                    "UPDATE agents SET last_test_status = :status, last_test_message = :message,"
                    " last_tested_at = :now WHERE id = :id"
                ),
                {
                    "status": result["status"],
                    "message": result["message"][:500],
                    "now": utcnow(),
                    "id": agent_id,
                },
            )
        return result


__all__ = ["AgentService", "RoleTemplateService"]
