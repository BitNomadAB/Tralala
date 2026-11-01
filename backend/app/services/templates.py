from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..schemas.templates import TemplateCreate, TemplateFromBoard, TemplateUpdate
from ..storage.board_db import BoardDatabaseManager
from ..storage.registry import Registry
from ..storage.sqlite import utcnow


def _parse_list(raw: Any) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str)]


def _parse_labels(raw: Any) -> list[dict[str, str]]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    labels: list[dict[str, str]] = []
    for entry in value:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            labels.append({"name": entry["name"], "color": str(entry.get("color") or "#64748b")})
    return labels


def _unique_names(names: list[str], *, field: str) -> list[str]:
    seen: set[str] = set()
    for name in names:
        key = name.strip().lower()
        if key in seen:
            raise ValidationFailure(
                f"Duplicate {field} name",
                details={"field": field, "value": name},
            )
        seen.add(key)
    return names


def _dedupe_names(names: list[str]) -> list[str]:
    """Boards may legitimately repeat a list name; a template snapshot keeps the first."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


class TemplateService:
    """Board templates stored in the registry database and reusable across new boards."""

    def __init__(
        self,
        registry: Registry,
        boards: BoardDatabaseManager,
        board_service: Any,
    ) -> None:
        self.registry = registry
        self.boards = boards
        self.board_service = board_service

    # --- helpers ---------------------------------------------------------------

    def serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        lists = _parse_list(row.get("lists_json"))
        labels = _parse_labels(row.get("labels_json"))
        entry = dict(row)
        entry.pop("lists_json", None)
        entry.pop("labels_json", None)
        entry["lists"] = lists
        entry["labels"] = labels
        entry["list_count"] = len(lists)
        return entry

    def find(self, template_id: str) -> dict[str, Any] | None:
        row = self.registry.read_one(
            "SELECT * FROM board_templates WHERE id = :id", {"id": template_id}
        )
        return self.serialize(row) if row else None

    def get(self, template_id: str) -> dict[str, Any]:
        template = self.find(template_id)
        if template is None:
            raise NotFound("Template not found")
        return template

    def resolve(self, template_id: str) -> dict[str, Any]:
        """Resolve a template for board creation; raises when it no longer exists."""
        template = self.find(template_id)
        if template is None:
            raise ValidationFailure(
                "Template not found",
                details={"template_id": template_id},
            )
        return template

    def _write(
        self,
        actor: ActorContext,
        *,
        name: str,
        description: str,
        lists: list[str],
        labels: list[dict[str, str]],
        template_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        row_id = template_id or str(uuid4())
        try:
            with self.registry.connect() as conn:
                if template_id is None:
                    conn.execute(
                        text(
                            "INSERT INTO board_templates"
                            " (id, name, description, lists_json, labels_json, created_at,"
                            "  updated_at)"
                            " VALUES (:id, :name, :description, :lists, :labels, :now, :now)"
                        ),
                        {
                            "id": row_id,
                            "name": name,
                            "description": description,
                            "lists": json.dumps(lists),
                            "labels": json.dumps(labels),
                            "now": now,
                        },
                    )
                else:
                    conn.execute(
                        text(
                            "UPDATE board_templates SET name = :name,"
                            " description = :description, lists_json = :lists,"
                            " labels_json = :labels, updated_at = :now"
                            " WHERE id = :id"
                        ),
                        {
                            "id": row_id,
                            "name": name,
                            "description": description,
                            "lists": json.dumps(lists),
                            "labels": json.dumps(labels),
                            "now": now,
                        },
                    )
        except IntegrityError as exc:
            raise Conflict(
                "A template with this name already exists",
                code="template_name_taken",
                details={"name": name},
            ) from exc
        return self.get(row_id)

    # --- commands --------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        rows = self.registry.read("SELECT * FROM board_templates ORDER BY name")
        return [self.serialize(row) for row in rows]

    def create(self, actor: ActorContext, payload: TemplateCreate) -> dict[str, Any]:
        actor.require("boards:write")
        lists = _unique_names(list(payload.lists), field="list")
        labels = [label.model_dump() for label in payload.labels]
        _unique_names([label["name"] for label in labels], field="label")
        return self._write(
            actor,
            name=payload.name,
            description=payload.description,
            lists=lists,
            labels=labels,
        )

    def update(
        self, actor: ActorContext, template_id: str, payload: TemplateUpdate
    ) -> dict[str, Any]:
        actor.require("boards:write")
        current = self.get(template_id)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            return current
        lists = (
            _unique_names(list(updates["lists"]), field="list")
            if "lists" in updates
            else current["lists"]
        )
        labels = updates["labels"] if "labels" in updates else current["labels"]
        if "labels" in updates:
            _unique_names([label["name"] for label in labels], field="label")
        return self._write(
            actor,
            template_id=template_id,
            name=updates.get("name", current["name"]),
            description=updates.get("description", current["description"]),
            lists=lists,
            labels=labels,
        )

    def delete(self, actor: ActorContext, template_id: str) -> None:
        actor.require("boards:admin")
        self.get(template_id)
        with self.registry.connect() as conn:
            conn.execute(text("DELETE FROM board_templates WHERE id = :id"), {"id": template_id})

    def create_from_loop(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: TemplateFromBoard
    ) -> dict[str, Any]:
        """A layout snapshot comes from one Loop, never from merged Board-wide columns."""
        actor.require("boards:write")
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            loop = conn.execute(
                text("SELECT id FROM loops WHERE id = :id"), {"id": loop_id}
            ).first()
            if loop is None:
                raise NotFound("Loop not found", code="loop_not_found")
            lists = [
                row["name"]
                for row in conn.execute(
                    text(
                        "SELECT name FROM lists WHERE loop_id = :loop_id"
                        " AND archived_at IS NULL ORDER BY position, created_at"
                    ),
                    {"loop_id": loop_id},
                ).mappings()
            ]
            labels = [
                {"name": row["name"], "color": row["color"]}
                for row in conn.execute(
                    text("SELECT name, color FROM labels ORDER BY name")
                ).mappings()
            ]
        return self._write(
            actor,
            name=payload.name,
            description=payload.description,
            lists=_dedupe_names(lists),
            labels=labels,
        )
