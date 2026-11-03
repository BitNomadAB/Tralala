"""Board templates: list names and labels kept in the registry and reused by new boards.

The service reaches the registry through the registry unit of work and a board through the board
unit of work (``app/repositories``), and asks ``BoardLookup`` (BoardService) whether a board is
registered; the clock and the id source are passed in, so every rule here runs in a unit test
without a database.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol, TypedDict, TypeIs
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..db.generated.registry import BoardTemplatesRow
from ..repositories.board import BoardUnitOfWork
from ..repositories.errors import ConstraintViolationError
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.templates import TemplateCreate, TemplateFromBoard, TemplateUpdate

DEFAULT_LABEL_COLOR = "#64748b"


class BoardLookup(Protocol):
    """What TemplateService needs from BoardService: the board is registered."""

    def require_row(self, board_id: str) -> object: ...


class TemplateLabel(TypedDict):
    name: str
    color: str


class TemplateEntry(TypedDict):
    """A template as the API returns it: its lists and labels parsed, never the stored JSON."""

    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    lists: list[str]
    labels: list[TemplateLabel]
    list_count: int


def _new_id() -> str:
    return str(uuid4())


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_object(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _json_list(raw: str) -> list[object]:
    """The stored JSON as a list; anything that is not a JSON list is an empty one."""
    try:
        value: object = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if _is_list(value) else []


def _parse_list(raw: str) -> list[str]:
    return [entry for entry in _json_list(raw) if isinstance(entry, str)]


def _parse_labels(raw: str) -> list[TemplateLabel]:
    labels: list[TemplateLabel] = []
    for entry in _json_list(raw):
        if not _is_object(entry):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            labels.append({"name": name, "color": str(entry.get("color") or DEFAULT_LABEL_COLOR)})
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


def _entry(row: BoardTemplatesRow) -> TemplateEntry:
    lists = _parse_list(row.lists_json)
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "lists": lists,
        "labels": _parse_labels(row.labels_json),
        "list_count": len(lists),
    }


class TemplateService:
    """Board templates stored in the registry database and reusable across new boards."""

    def __init__(
        self,
        store: RegistryUnitOfWork,
        boards: BoardUnitOfWork,
        board_service: BoardLookup,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.store = store
        self.boards = boards
        self.board_service = board_service
        self._clock = clock
        self._new_id = new_id

    # --- helpers ---------------------------------------------------------------------------------

    def find(self, template_id: str) -> TemplateEntry | None:
        with self.store.reader() as repos:
            row = repos.board_templates.get(template_id)
        return None if row is None else _entry(row)

    def get(self, template_id: str) -> TemplateEntry:
        template = self.find(template_id)
        if template is None:
            raise NotFound("Template not found")
        return template

    def resolve(self, template_id: str) -> TemplateEntry:
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
        *,
        name: str,
        description: str,
        lists: list[str],
        labels: list[TemplateLabel],
        template_id: str | None = None,
    ) -> TemplateEntry:
        now = self._clock()
        row = BoardTemplatesRow(
            id=template_id or self._new_id(),
            name=name,
            description=description,
            lists_json=json.dumps(lists),
            labels_json=json.dumps(labels),
            created_at=now,
            updated_at=now,
        )
        try:
            with self.store.writer() as repos:
                if template_id is None:
                    repos.board_templates.add(row)
                else:
                    repos.board_templates.update(row)
        except ConstraintViolationError as exc:
            raise Conflict(
                "A template with this name already exists",
                code="template_name_taken",
                details={"name": name},
            ) from exc
        return self.get(row.id)

    # --- commands --------------------------------------------------------------------------------

    def list(self) -> list[TemplateEntry]:
        with self.store.reader() as repos:
            rows = repos.board_templates.all()
        return [_entry(row) for row in rows]

    def create(self, actor: ActorContext, payload: TemplateCreate) -> TemplateEntry:
        actor.require("boards:write")
        lists = _unique_names(list(payload.lists), field="list")
        labels: list[TemplateLabel] = [
            {"name": label.name, "color": label.color} for label in payload.labels
        ]
        _unique_names([label["name"] for label in labels], field="label")
        return self._write(
            name=payload.name,
            description=payload.description,
            lists=lists,
            labels=labels,
        )

    def update(
        self, actor: ActorContext, template_id: str, payload: TemplateUpdate
    ) -> TemplateEntry:
        actor.require("boards:write")
        current = self.get(template_id)
        if (
            payload.name is None
            and payload.description is None
            and payload.lists is None
            and payload.labels is None
        ):
            return current
        lists = (
            _unique_names(list(payload.lists), field="list")
            if payload.lists is not None
            else current["lists"]
        )
        labels: list[TemplateLabel] = (
            [{"name": label.name, "color": label.color} for label in payload.labels]
            if payload.labels is not None
            else current["labels"]
        )
        if payload.labels is not None:
            _unique_names([label["name"] for label in labels], field="label")
        return self._write(
            template_id=template_id,
            name=payload.name if payload.name is not None else current["name"],
            description=(
                payload.description if payload.description is not None else current["description"]
            ),
            lists=lists,
            labels=labels,
        )

    def delete(self, actor: ActorContext, template_id: str) -> None:
        actor.require("boards:admin")
        self.get(template_id)
        with self.store.writer() as repos:
            repos.board_templates.delete(template_id)

    def create_from_loop(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: TemplateFromBoard
    ) -> TemplateEntry:
        """A layout snapshot comes from one Loop, never from merged Board-wide columns."""
        actor.require("boards:write")
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as repos:
            if repos.loops.get(loop_id) is None:
                raise NotFound("Loop not found", code="loop_not_found")
            lists = repos.lists.active_names(loop_id)
            labels: list[TemplateLabel] = [
                {"name": label.name, "color": label.color} for label in repos.labels.all()
            ]
        return self._write(
            name=payload.name,
            description=payload.description,
            lists=_dedupe_names(lists),
            labels=labels,
        )
