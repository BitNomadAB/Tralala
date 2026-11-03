"""The backend log: one JSON object per line, written by one formatter.

A call names its event and passes the rest as ``extra``::

    logger.info("backup_created", extra={"board_id": board_id, "pruned": 2})

and :class:`JsonFormatter` writes ``ts``, ``level``, ``event`` (the message), ``logger``,
``request_id`` (the request being served, from :data:`REQUEST_ID`; null outside a request), then
every ``extra`` key, then ``exc_info`` with the traceback when the call carried one. Nobody builds a
JSON string by hand: ``tests/unit/test_logging.py`` refuses ``json.dumps`` inside a logger call, a
JSON template as a message and a logger outside the ``tralala`` tree.

``extra`` never carries a prompt, a token or a key. The formatter redacts the values of keys named
``token``, ``api_key``, ``authorization`` or ``password`` (any case, at any depth) in case one slips
through. A key of ``extra`` is never one of :data:`RESERVED_KEYS`: a :class:`logging.LogRecord`
attribute (``name``, ``args``, ``message``...), which the logging module refuses to overwrite, or
a fixed field of the line. Such a field gets a longer name (``backup_name``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TypeGuard

from .config import Settings

ROOT_LOGGER = "tralala"
"""Every logger in ``app/`` is this one or a child of it (``tralala.agents``), so one handler
covers them all."""

REQUEST_ID: ContextVar[str | None] = ContextVar("tralala_request_id", default=None)
"""The id of the request being served; the observability middleware binds it per request."""

REDACTED_KEYS = frozenset({"token", "api_key", "authorization", "password"})
REDACTED = "[redacted]"

FIELDS = ("ts", "level", "event", "logger", "request_id")
"""What every line starts with, in this order."""

RESERVED_KEYS = (
    frozenset(vars(logging.LogRecord("", 0, "", 0, None, None, None)))
    | {"message", "asctime"}
    | set(FIELDS)
)
"""Names an ``extra`` key cannot have: a record's own attributes (the logging module refuses to
overwrite them) and the fixed fields of the line (which an extra must not shadow)."""


@contextmanager
def bound_request_id(request_id: str) -> Generator[None]:
    """Every line logged inside the block names the request.

    That covers the tasks the block starts and the worker threads anyio runs the routes in, which
    copy the context. An executor the services own does not copy it, so work handed to one is
    wrapped in ``carry_request_id``.
    """
    token = REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        REQUEST_ID.reset(token)


def carry_request_id[**P, R](work: Callable[P, R]) -> Callable[P, R]:
    """``work`` as a call that logs under the request id current now, on whichever thread it runs.

    A service submits background work (a generation run, a mention job, a discussion run) to its
    own executor, whose threads start with an empty context; wrapped here at submission, the work's
    lines name the request that started it. Work started without a request stays null.
    """
    request_id = REQUEST_ID.get()

    def run(*args: P.args, **kwargs: P.kwargs) -> R:
        token = REQUEST_ID.set(request_id)
        try:
            return work(*args, **kwargs)
        finally:
            REQUEST_ID.reset(token)

    return run


def _is_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _is_sequence(value: object) -> TypeGuard[list[object] | tuple[object, ...]]:
    return isinstance(value, (list, tuple))


def redact(value: object) -> object:
    """``value`` with the value of every key in :data:`REDACTED_KEYS` replaced, at any depth."""
    if _is_mapping(value):
        return {
            str(key): REDACTED if str(key).lower() in REDACTED_KEYS else redact(item)
            for key, item in value.items()
        }
    if _is_sequence(value):
        return [redact(item) for item in value]
    return value


def extras(record: logging.LogRecord) -> dict[str, object]:
    """The keys a call passed as ``extra``, in the order it passed them."""
    return {key: value for key, value in vars(record).items() if key not in RESERVED_KEYS}


class JsonFormatter(logging.Formatter):
    """A record as one JSON object: the fixed fields, the extras, then the traceback if any."""

    def fields(self, record: logging.LogRecord) -> dict[str, object]:
        """What :meth:`format` serialises: the line as a dict, already redacted."""
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
            "request_id": REQUEST_ID.get(),
        }
        for key, value in extras(record).items():
            payload[key] = REDACTED if key.lower() in REDACTED_KEYS else redact(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc_info"] = record.exc_text
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return payload

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self.fields(record), ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Send the ``tralala`` loggers to stderr through :class:`JsonFormatter`; safe to call twice."""
    logger = logging.getLogger(ROOT_LOGGER)
    if not any(isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False


__all__ = [
    "FIELDS",
    "REDACTED",
    "REDACTED_KEYS",
    "REQUEST_ID",
    "RESERVED_KEYS",
    "ROOT_LOGGER",
    "JsonFormatter",
    "bound_request_id",
    "configure_logging",
    "extras",
    "redact",
]
