"""Identifiers taken from a request that end up in a filesystem path, a header or a log.

A board's database lives under ``data/boards/{uuid}/``, so the id is the only user-supplied text
that reaches a path. It is accepted only as a UUID and always written in its canonical form. A
client's ``X-Request-ID`` is echoed in the response and written to logs, so it is kept only when the
whole value is a short token; ``fullmatch`` matters, because ``match`` with ``$`` also accepts a
trailing newline.
"""

from __future__ import annotations

import re
import uuid

from .errors import NotFound

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,100}")


def canonical_board_id(board_id: str) -> str:
    """The canonical UUID text of ``board_id``; anything else reads as a missing board."""
    try:
        return str(uuid.UUID(board_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise NotFound("Board not found") from exc


def accepted_request_id(value: str) -> bool:
    """Whether a client's request id is kept as it is (otherwise the server assigns one)."""
    return REQUEST_ID_PATTERN.fullmatch(value) is not None
