"""Role templates: the central role definitions that agents reference and discussions snapshot.

The service reaches the registry only through the repositories and the registry unit of work
(``app/repositories``). The clock and the id source are passed in, with the real ones as defaults,
so every rule here runs in a unit test without a database. ``services.agents`` re-exports it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound
from ..db.generated.registry import RoleTemplatesRow
from ..repositories.agents import RoleTemplateChanges
from ..repositories.errors import ConstraintViolationError
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.agents import RoleTemplateCreate, RoleTemplateDuplicate, RoleTemplateUpdate
from .role_defaults import BUILTIN_ROLES


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
