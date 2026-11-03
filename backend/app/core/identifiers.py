"""Identifiers that end up in a filesystem path.

A board's database lives under ``data/boards/{uuid}/``, so the id is the only user-supplied text
that reaches a path. It is accepted only as a UUID and always written in its canonical form.
"""

from __future__ import annotations

import uuid

from .errors import NotFound


def canonical_board_id(board_id: str) -> str:
    """The canonical UUID text of ``board_id``; anything else reads as a missing board."""
    try:
        return str(uuid.UUID(board_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise NotFound("Board not found") from exc
