"""Board templates: registry rows a new board's lists and labels are taken from."""

from __future__ import annotations

from typing import Protocol

from ..db.generated.registry import BoardTemplatesRow


class BoardTemplateRepository(Protocol):
    def all(self) -> list[BoardTemplatesRow]:
        """By name (case-insensitive, as the column compares)."""
        ...

    def get(self, template_id: str) -> BoardTemplatesRow | None: ...

    def add(self, row: BoardTemplatesRow) -> None:
        """Raises ``ConstraintViolationError`` when the name is taken."""
        ...

    def update(self, row: BoardTemplatesRow) -> None:
        """Rewrite the template's name, description, lists, labels and ``updated_at`` from
        ``row``; ``ConstraintViolationError`` when the new name is taken."""
        ...

    def delete(self, template_id: str) -> None: ...
