"""Captured log records as the JSON lines the backend writes, for the tests that read the log.

``caplog`` keeps the records; the backend's :class:`JsonFormatter` turns each into its line, so a
test asserts what an operator reads rather than the arguments of a logger call.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from app.core.logging import JsonFormatter

_FRAME = ("ts", "level", "logger", "request_id")


def lines(records: Iterable[logging.LogRecord]) -> list[dict[str, object]]:
    """Each record exactly as the backend log writes it, parsed back."""
    formatter = JsonFormatter()
    return [json.loads(formatter.format(record)) for record in records]


def events(records: Iterable[logging.LogRecord]) -> list[dict[str, object]]:
    """Each line without its frame (time, level, logger, request id): the event and its fields."""
    return [
        {key: value for key, value in line.items() if key not in _FRAME} for line in lines(records)
    ]
