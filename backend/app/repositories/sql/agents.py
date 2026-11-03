"""The role template, agent and board-agent repositories over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from ...core import sql
from ...db import values
from ...db.generated.registry import (
    AGENTS_COLUMNS,
    ROLE_TEMPLATES_COLUMNS,
    AgentsRow,
    BoardAgentsRow,
    RoleTemplatesRow,
)
from ..agents import AGENT_EDITABLE, ROLE_TEMPLATE_EDITABLE, AgentChanges, RoleTemplateChanges
from ..errors import ConstraintViolationError

# What the agent list formats into its SQL text (see core/sql.py).
_AGENT_FILTERS: sql.Filters = (
    ("contains", "(name LIKE :contains OR description LIKE :contains)"),
    ("enabled", "enabled = :enabled"),
)

# --- role templates ------------------------------------------------------------------------------

_ROLE_TEMPLATE = (
    f"SELECT {sql.column_list(ROLE_TEMPLATES_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM role_templates"
)
_ALL_ROLE_TEMPLATES = text(f"{_ROLE_TEMPLATE} ORDER BY built_in DESC, name")
_ROLE_TEMPLATE_BY_ID = text(f"{_ROLE_TEMPLATE} WHERE id = :id")
_ROLE_TEMPLATE_BY_KEY = text(f"{_ROLE_TEMPLATE} WHERE builtin_key = :key")
_ADD_ROLE_TEMPLATE = text(
    "INSERT INTO role_templates"
    " (id, name, description, system_prompt, default_system_prompt, built_in, builtin_key,"
    "  scope, created_at, updated_at)"
    " VALUES (:id, :name, :description, :system_prompt, :default_system_prompt, :built_in,"
    "         :builtin_key, :scope, :created_at, :updated_at)"
)
_DELETE_ROLE_TEMPLATE = text("DELETE FROM role_templates WHERE id = :id")

# --- agents --------------------------------------------------------------------------------------

_AGENT = (
    f"SELECT {sql.column_list(AGENTS_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM agents"
)
_AGENT_BY_ID = text(f"{_AGENT} WHERE id = :id")
_COUNT_BY_ROLE_TEMPLATE = text(
    "SELECT role_template_id, COUNT(*) AS total FROM agents"
    " WHERE role_template_id IS NOT NULL GROUP BY role_template_id"
)
_ADD_AGENT = text(
    "INSERT INTO agents"
    " (id, name, description, role_template_id, role_prompt_override, connection_type,"
    "  base_url, model, api_key_ciphertext, api_key_hint, temperature, max_output_tokens,"
    "  timeout_seconds, enabled, last_test_status, last_test_message, last_tested_at,"
    "  created_at, updated_at)"
    " VALUES (:id, :name, :description, :role_template_id, :role_prompt_override,"
    "         :connection_type, :base_url, :model, :api_key_ciphertext, :api_key_hint,"
    "         :temperature, :max_output_tokens, :timeout_seconds, :enabled, :last_test_status,"
    "         :last_test_message, :last_tested_at, :created_at, :updated_at)"
)
_RECORD_TEST = text(
    "UPDATE agents SET last_test_status = :status, last_test_message = :message,"
    " last_tested_at = :now WHERE id = :id"
)
_CLEAR_ROLE_TEMPLATE = text(
    "UPDATE agents SET role_template_id = NULL WHERE role_template_id = :id"
)
_DELETE_AGENT = text("DELETE FROM agents WHERE id = :id")
_SEALED_KEYS = text(
    "SELECT id, api_key_ciphertext FROM agents WHERE api_key_ciphertext IS NOT NULL"
)
_RESEAL_KEY = text("UPDATE agents SET api_key_ciphertext = :value WHERE id = :id")

# --- board selections ----------------------------------------------------------------------------

_BOARD_AGENT_IDS = text(
    "SELECT agent_id FROM board_agents WHERE board_id = :id ORDER BY created_at, agent_id"
)
_ALL_BOARD_AGENTS = text(
    "SELECT board_id, agent_id FROM board_agents ORDER BY created_at, agent_id"
)
_CLEAR_BOARD_AGENTS = text("DELETE FROM board_agents WHERE board_id = :id")
_ADD_BOARD_AGENT = text(
    "INSERT INTO board_agents (board_id, agent_id, created_at)"
    " VALUES (:board_id, :agent_id, :created_at)"
)


class SqlRoleTemplateRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def all(self) -> list[RoleTemplatesRow]:
        result = self._connection.execute(_ALL_ROLE_TEMPLATES).mappings()
        return [RoleTemplatesRow.from_mapping(row) for row in result]

    def get(self, role_id: str) -> RoleTemplatesRow | None:
        row = self._connection.execute(_ROLE_TEMPLATE_BY_ID, {"id": role_id}).mappings().first()
        return None if row is None else RoleTemplatesRow.from_mapping(row)

    def by_builtin_key(self, key: str) -> RoleTemplatesRow | None:
        row = self._connection.execute(_ROLE_TEMPLATE_BY_KEY, {"key": key}).mappings().first()
        return None if row is None else RoleTemplatesRow.from_mapping(row)

    def add(self, row: RoleTemplatesRow) -> None:
        parameters = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "system_prompt": row.system_prompt,
            "default_system_prompt": row.default_system_prompt,
            "built_in": row.built_in,
            "builtin_key": row.builtin_key,
            "scope": row.scope,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        try:
            self._connection.execute(_ADD_ROLE_TEMPLATE, parameters)
        except IntegrityError as exc:
            raise ConstraintViolationError(str(exc.orig)) from exc

    def update(self, role_id: str, changes: RoleTemplateChanges, *, now: str) -> None:
        assignments = sql.assignments(changes, ROLE_TEMPLATE_EDITABLE)
        statement = text(
            "UPDATE role_templates"  # noqa: S608 - from ROLE_TEMPLATE_EDITABLE
            f" SET {assignments}, updated_at = :updated_at WHERE id = :id"
        )
        try:
            self._connection.execute(statement, {**changes, "updated_at": now, "id": role_id})
        except IntegrityError as exc:
            raise ConstraintViolationError(str(exc.orig)) from exc

    def delete(self, role_id: str) -> None:
        self._connection.execute(_DELETE_ROLE_TEMPLATE, {"id": role_id})


class SqlAgentRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, agent_id: str) -> AgentsRow | None:
        row = self._connection.execute(_AGENT_BY_ID, {"id": agent_id}).mappings().first()
        return None if row is None else AgentsRow.from_mapping(row)

    def listing(self, *, contains: str | None, enabled: bool | None) -> list[AgentsRow]:
        parameters: dict[str, object] = {}
        if contains is not None:
            parameters["contains"] = f"%{contains}%"
        if enabled is not None:
            parameters["enabled"] = 1 if enabled else 0
        where = sql.where(_AGENT_FILTERS, parameters)
        statement = text(f"{_AGENT}{where} ORDER BY name")
        result = self._connection.execute(statement, parameters).mappings()
        return [AgentsRow.from_mapping(row) for row in result]

    def count_by_role_template(self) -> dict[str, int]:
        result = self._connection.execute(_COUNT_BY_ROLE_TEMPLATE).mappings()
        return {
            values.text(row, "role_template_id"): values.integer(row, "total") for row in result
        }

    def add(self, row: AgentsRow) -> None:
        parameters = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "role_template_id": row.role_template_id,
            "role_prompt_override": row.role_prompt_override,
            "connection_type": row.connection_type,
            "base_url": row.base_url,
            "model": row.model,
            "api_key_ciphertext": row.api_key_ciphertext,
            "api_key_hint": row.api_key_hint,
            "temperature": row.temperature,
            "max_output_tokens": row.max_output_tokens,
            "timeout_seconds": row.timeout_seconds,
            "enabled": row.enabled,
            "last_test_status": row.last_test_status,
            "last_test_message": row.last_test_message,
            "last_tested_at": row.last_tested_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        try:
            self._connection.execute(_ADD_AGENT, parameters)
        except IntegrityError as exc:
            raise ConstraintViolationError(str(exc.orig)) from exc

    def update(self, agent_id: str, changes: AgentChanges, *, now: str) -> None:
        assignments = sql.assignments(changes, AGENT_EDITABLE)
        statement = text(
            "UPDATE agents"  # noqa: S608 - from AGENT_EDITABLE
            f" SET {assignments}, updated_at = :updated_at WHERE id = :id"
        )
        try:
            self._connection.execute(statement, {**changes, "updated_at": now, "id": agent_id})
        except IntegrityError as exc:
            raise ConstraintViolationError(str(exc.orig)) from exc

    def record_test(self, agent_id: str, *, status: str, message: str, now: str) -> None:
        parameters = {"status": status, "message": message, "now": now, "id": agent_id}
        self._connection.execute(_RECORD_TEST, parameters)

    def clear_role_template(self, role_id: str) -> None:
        self._connection.execute(_CLEAR_ROLE_TEMPLATE, {"id": role_id})

    def delete(self, agent_id: str) -> None:
        self._connection.execute(_DELETE_AGENT, {"id": agent_id})

    def sealed_keys(self) -> dict[str, str]:
        result = self._connection.execute(_SEALED_KEYS).mappings()
        return {values.text(row, "id"): values.text(row, "api_key_ciphertext") for row in result}

    def reseal(self, agent_id: str, ciphertext: str) -> None:
        self._connection.execute(_RESEAL_KEY, {"value": ciphertext, "id": agent_id})


class SqlAgentLinkRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def agent_ids(self, board_id: str) -> list[str]:
        result = self._connection.execute(_BOARD_AGENT_IDS, {"id": board_id}).mappings()
        return [values.text(row, "agent_id") for row in result]

    def by_board(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for row in self._connection.execute(_ALL_BOARD_AGENTS).mappings():
            grouped.setdefault(values.text(row, "board_id"), []).append(
                values.text(row, "agent_id")
            )
        return grouped

    def clear(self, board_id: str) -> None:
        self._connection.execute(_CLEAR_BOARD_AGENTS, {"id": board_id})

    def add(self, row: BoardAgentsRow) -> None:
        self._connection.execute(
            _ADD_BOARD_AGENT,
            {"board_id": row.board_id, "agent_id": row.agent_id, "created_at": row.created_at},
        )
