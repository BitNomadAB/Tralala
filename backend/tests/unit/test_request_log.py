"""The ``http_request`` line: the same fields as always, plus the API error on a 4xx answer.

``request_line`` builds the line's ``extra`` from what the observability middleware knows (the
method, the path, the status, the time taken and what the handlers left on ``request.state``), so
these tests read it without building the app. The last one writes it through the backend's
``JsonFormatter``, as an operator reads it.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import RESERVED_KEYS, bound_request_id
from app.core.request_log import ERROR_MESSAGE_CHARS, bounded_message, request_line
from tests.unit.log_lines import lines

CARD_PATH = "/api/v1/boards/b-1/loops/l-1/cards/c-1"
TODAY_FIELDS = ["method", "path", "status", "duration_ms", "actor_id", "replayed"]


def test_a_422_names_the_validation_error() -> None:
    line = request_line(
        method="POST",
        path="/api/v1/agents",
        status=422,
        duration_ms=4.21,
        actor_id="u-1",
        replayed=False,
        error_code="validation_failed",
        error_message="Request validation failed",
    )
    assert line == {
        "method": "POST",
        "path": "/api/v1/agents",
        "status": 422,
        "duration_ms": 4.21,
        "actor_id": "u-1",
        "replayed": False,
        "error_code": "validation_failed",
        "error_message": "Request validation failed",
    }
    assert list(line) == [*TODAY_FIELDS, "error_code", "error_message"]


def test_a_409_names_the_version_conflict() -> None:
    line = request_line(
        method="PATCH",
        path=CARD_PATH,
        status=409,
        duration_ms=12.5,
        actor_id="u-1",
        replayed=False,
        error_code="version_conflict",
        error_message="Card was modified by another actor",
    )
    assert (line["status"], line["error_code"], line["error_message"]) == (
        409,
        "version_conflict",
        "Card was modified by another actor",
    )


def test_a_200_line_keeps_exactly_the_fields_it_always_had() -> None:
    line = request_line(
        method="GET",
        path=CARD_PATH,
        status=200,
        duration_ms=1.0,
        actor_id="u-1",
        replayed=True,
    )
    assert line == {
        "method": "GET",
        "path": CARD_PATH,
        "status": 200,
        "duration_ms": 1.0,
        "actor_id": "u-1",
        "replayed": True,
    }
    assert list(line) == TODAY_FIELDS


@pytest.mark.parametrize("status", [200, 201, 204, 304, 399])
def test_below_400_an_error_left_on_the_request_stays_out_of_the_line(status: int) -> None:
    line = request_line(
        method="GET",
        path=CARD_PATH,
        status=status,
        duration_ms=1.0,
        actor_id=None,
        replayed=False,
        error_code="version_conflict",
        error_message="Card was modified by another actor",
    )
    assert list(line) == TODAY_FIELDS


def test_an_error_no_handler_named_is_logged_as_unknown() -> None:
    line = request_line(
        method="GET", path="/api/v1/x", status=404, duration_ms=0.3, actor_id=None, replayed=False
    )
    assert (line["error_code"], line["error_message"]) == (None, None)


def test_the_message_is_bounded() -> None:
    long = "x" * (ERROR_MESSAGE_CHARS * 3)
    assert bounded_message(long) == "x" * ERROR_MESSAGE_CHARS
    assert bounded_message("short") == "short"
    line = request_line(
        method="POST",
        path="/api/v1/agents",
        status=400,
        duration_ms=1.0,
        actor_id="u-1",
        replayed=False,
        error_code="bad_request",
        error_message=long,
    )
    assert line["error_message"] == "x" * ERROR_MESSAGE_CHARS


def test_no_field_of_the_line_is_a_record_attribute_or_a_fixed_field() -> None:
    line = request_line(
        method="POST", path="/", status=500, duration_ms=1.0, actor_id=None, replayed=False
    )
    assert set(line) & RESERVED_KEYS == set()


def test_the_written_409_line_names_the_error_and_nothing_else(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fields = request_line(
        method="PATCH",
        path=CARD_PATH,
        status=409,
        duration_ms=12.5,
        actor_id="u-1",
        replayed=False,
        error_code="version_conflict",
        error_message="Card was modified by another actor",
    )
    with caplog.at_level(logging.INFO, logger="tralala"), bound_request_id("req-409"):
        logging.getLogger("tralala").info("http_request", extra=fields)
        [line] = lines(caplog.records)
    assert {key: value for key, value in line.items() if key != "ts"} == {
        "level": "INFO",
        "event": "http_request",
        "logger": "tralala",
        "request_id": "req-409",
        "method": "PATCH",
        "path": CARD_PATH,
        "status": 409,
        "duration_ms": 12.5,
        "actor_id": "u-1",
        "replayed": False,
        "error_code": "version_conflict",
        "error_message": "Card was modified by another actor",
    }
    assert "details" not in json.dumps(line)
