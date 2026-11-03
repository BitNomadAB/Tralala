"""The fields of the ``http_request`` line, written once for every request the app answers.

The observability middleware in ``app/main.py`` logs the line; its fields are built here, away from
the app, so a unit test reads them without serving a request. Every line names the method, the
path, the status, the time taken, the authenticated actor and whether a stored answer was replayed.
An answer with a status of 400 or above also names the API error: the error handler leaves its
``code`` and the first :data:`ERROR_MESSAGE_CHARS` characters of its message on ``request.state``,
and the line carries them as ``error_code`` and ``error_message`` (``None`` when no handler named
one). The line never holds a request or response body, a header, the error's details or a token.
"""

from __future__ import annotations

ERROR_MESSAGE_CHARS = 300
"""At most this many characters of an error's message reach the request log."""

ERROR_STATUS = 400
"""The lowest status whose line names the error."""


def bounded_message(message: str) -> str:
    """The start of ``message`` that the request log keeps."""
    return message[:ERROR_MESSAGE_CHARS]


def request_line(
    *,
    method: str,
    path: str,
    status: int,
    duration_ms: float,
    actor_id: str | None,
    replayed: bool,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    """The ``extra`` of the ``http_request`` line.

    ``error_code`` and ``error_message`` are what the error handler left on the request; they join
    the line only when ``status`` is :data:`ERROR_STATUS` or above, so a successful answer's line
    keeps exactly the fields it always had.
    """
    line: dict[str, object] = {
        "method": method,
        "path": path,
        "status": status,
        "duration_ms": duration_ms,
        "actor_id": actor_id,
        "replayed": replayed,
    }
    if status >= ERROR_STATUS:
        line["error_code"] = error_code
        line["error_message"] = None if error_message is None else bounded_message(error_message)
    return line


__all__ = ["ERROR_MESSAGE_CHARS", "ERROR_STATUS", "bounded_message", "request_line"]
