"""The backend log is one JSON object per line, and only ``JsonFormatter`` writes it.

The formatter tests build records the way a logger does (``Logger.makeRecord``, which applies
``extra``) and read back the line. The guard reads every module in ``app/`` and refuses the ways a
line used to be built by hand: ``json.dumps`` inside a logger call, a message that is a JSON
template, an ``extra`` key that is a record attribute or a fixed field, and a logger outside the
``tralala`` tree, which the handler would never see.
"""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Generator, Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import (
    FIELDS,
    REDACTED,
    REQUEST_ID,
    RESERVED_KEYS,
    ROOT_LOGGER,
    JsonFormatter,
    bound_request_id,
    configure_logging,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP = BACKEND_ROOT / "app"
LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})
MOMENT = 1_793_786_400.5  # 2026-11-04T10:00:00.500Z


def _record(
    message: str = "backup_created",
    *,
    level: int = logging.INFO,
    extra: Mapping[str, object] | None = None,
    error: BaseException | None = None,
) -> logging.LogRecord:
    exc_info = (type(error), error, error.__traceback__) if error is not None else None
    record = logging.getLogger("tralala.tests").makeRecord(
        "tralala.tests", level, __file__, 1, message, (), exc_info, extra=extra
    )
    record.created = MOMENT
    return record


def _line(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(JsonFormatter().format(record))


# --- the formatter -------------------------------------------------------------------------------


def test_a_line_has_the_fixed_fields_and_then_every_extra_in_order() -> None:
    line = _line(_record(extra={"board_id": "b-1", "pruned": 2, "integrity": "ok"}))
    assert line == {
        "ts": "2026-11-04T10:00:00.500Z",
        "level": "INFO",
        "event": "backup_created",
        "logger": "tralala.tests",
        "request_id": None,
        "board_id": "b-1",
        "pruned": 2,
        "integrity": "ok",
    }
    assert list(line) == [*FIELDS, "board_id", "pruned", "integrity"]


def test_the_event_is_the_message_with_its_arguments_applied() -> None:
    record = logging.getLogger("tralala.tests").makeRecord(
        "tralala.tests", logging.WARNING, __file__, 1, "agent %s has no key", ("a-1",), None
    )
    line = _line(record)
    assert (line["event"], line["level"]) == ("agent a-1 has no key", "WARNING")


def test_the_request_id_is_the_one_bound_where_the_record_is_formatted() -> None:
    record = _record()
    assert _line(record)["request_id"] is None
    with bound_request_id("req-1"):
        assert _line(record)["request_id"] == "req-1"
        with bound_request_id("req-2"):
            assert _line(record)["request_id"] == "req-2"
        assert _line(record)["request_id"] == "req-1"
    assert REQUEST_ID.get() is None
    assert _line(record)["request_id"] is None


def test_an_extra_cannot_replace_a_fixed_field() -> None:
    with bound_request_id("req-1"):
        line = _line(_record(extra={"request_id": "spoofed", "event": "other", "level": "x"}))
    assert (line["request_id"], line["event"], line["level"]) == ("req-1", "backup_created", "INFO")


def test_a_record_attribute_cannot_be_an_extra_so_such_a_field_needs_another_name() -> None:
    with pytest.raises(KeyError, match="name"):
        _record(extra={"name": "backup.sqlite"})
    assert {"name", "args", "message", "msg", "module", "exc_info"} <= RESERVED_KEYS


def test_a_value_json_cannot_hold_is_written_as_text() -> None:
    line = _line(_record(extra={"path": Path("boards") / "b-1", "addresses": ("10.0.0.1",)}))
    assert (line["path"], line["addresses"]) == (str(Path("boards") / "b-1"), ["10.0.0.1"])


def test_text_outside_ascii_is_written_as_it_is() -> None:
    written = JsonFormatter().format(_record(extra={"agent_name": "Åsa"}))
    assert '"agent_name": "Åsa"' in written


def test_secret_keys_are_redacted_in_any_case_and_at_any_depth() -> None:
    line = _line(
        _record(
            extra={
                "token": "ghp-1111",
                "Authorization": "Bearer abc",
                "settings": {"API_KEY": "sk-2222", "inner": [{"Password": "p", "kept": 1}]},
                "has_token": True,
                "has_api_key": False,
            }
        )
    )
    assert line["token"] == REDACTED
    assert line["Authorization"] == REDACTED
    assert line["settings"] == {"API_KEY": REDACTED, "inner": [{"Password": REDACTED, "kept": 1}]}
    assert (line["has_token"], line["has_api_key"]) == (True, False)
    written = json.dumps(line)
    assert all(secret not in written for secret in ("ghp-1111", "abc", "sk-2222"))


def _fail() -> None:
    raise ValueError("boom")


def test_an_exception_keeps_its_traceback_in_the_line() -> None:
    with pytest.raises(ValueError, match="boom") as raised:
        _fail()
    record = _record("loop generation run failed", level=logging.ERROR, error=raised.value)
    line = _line(record)
    trace = line["exc_info"]
    assert isinstance(trace, str)
    assert trace.startswith("Traceback (most recent call last):")
    assert trace.endswith("ValueError: boom")
    assert line["event"] == "loop generation run failed"
    assert list(line)[-1] == "exc_info"


def test_a_line_without_an_exception_has_no_traceback_field() -> None:
    assert "exc_info" not in _line(_record())
    assert "stack_info" not in _line(_record())


# --- configuration -------------------------------------------------------------------------------


@pytest.fixture
def root_logger() -> Generator[logging.Logger]:
    """The ``tralala`` logger, put back as it was after the test."""
    logger = logging.getLogger(ROOT_LOGGER)
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    for handler in handlers:
        logger.removeHandler(handler)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    for handler in handlers:
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = propagate


def test_configuring_twice_leaves_one_json_handler_at_the_configured_level(
    settings: Settings, root_logger: logging.Logger
) -> None:
    configure_logging(settings)
    configure_logging(settings.model_copy(update={"log_level": "WARNING"}))
    [handler] = root_logger.handlers
    assert isinstance(handler, logging.StreamHandler)
    assert isinstance(handler.formatter, JsonFormatter)
    assert (root_logger.level, root_logger.propagate) == (logging.WARNING, False)


def test_the_log_level_setting_takes_a_level_name_in_any_case() -> None:
    assert Settings.model_fields["log_level"].default == "INFO"
    assert Settings(log_level=" debug ").log_level == "DEBUG"
    with pytest.raises(ValidationError, match="log_level must be one of"):
        Settings(log_level="loud")


# --- the guard -----------------------------------------------------------------------------------


def _receiver_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _is_log_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in LOG_METHODS
        and "log" in _receiver_name(func.value).lower()
    )


def _calls_json_dumps(node: ast.AST) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            if isinstance(func, ast.Attribute) and func.attr == "dumps":
                return True
            if isinstance(func, ast.Name) and func.id == "dumps":
                return True
    return False


def _message(node: ast.Call) -> ast.expr | None:
    position = 1 if isinstance(node.func, ast.Attribute) and node.func.attr == "log" else 0
    return node.args[position] if len(node.args) > position else None


def _log_call_problems(node: ast.Call) -> list[str]:
    found: list[str] = []
    if any(_calls_json_dumps(part) for part in [*node.args, *node.keywords]):
        found.append("json.dumps inside a logger call: name the event and pass extra=")
    message = _message(node)
    if (
        isinstance(message, ast.Constant)
        and isinstance(message.value, str)
        and message.value.lstrip().startswith("{")
    ):
        found.append("a JSON template as the message: name the event and pass extra=")
    for keyword in node.keywords:
        if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
            found.extend(
                f"extra key {key.value!r} is a record attribute or a fixed field"
                for key in keyword.value.keys
                if isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value in RESERVED_KEYS
            )
    return found


def _logger_name_problem(node: ast.Call) -> str | None:
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "getLogger"):
        return None
    [name] = node.args or [ast.Constant(None)]
    if isinstance(name, ast.Name) and name.id == "ROOT_LOGGER":
        return None
    if (
        isinstance(name, ast.Constant)
        and isinstance(name.value, str)
        and (name.value == ROOT_LOGGER or name.value.startswith(ROOT_LOGGER + "."))
    ):
        return None
    return f"a logger outside the {ROOT_LOGGER!r} tree is never written by the JSON handler"


def hand_built_log_lines(source: str, filename: str = "<source>") -> list[str]:
    """Every log line in ``source`` that the formatter would not build, as ``file:line: why``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call):
            continue
        if _is_log_call(node):
            found += [f"{filename}:{node.lineno}: {why}" for why in _log_call_problems(node)]
        problem = _logger_name_problem(node)
        if problem is not None:
            found.append(f"{filename}:{node.lineno}: {problem}")
    return found


def test_no_log_line_in_the_application_is_built_by_hand() -> None:
    found: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        found += hand_built_log_lines(path.read_text(encoding="utf-8"), relative)
    assert found == [], "log through JsonFormatter (app/core/logging.py):\n" + "\n".join(found)


@pytest.mark.parametrize(
    "source",
    [
        'logger.info(json.dumps({"event": "startup"}))\n',
        'logger.log(level, json.dumps({"event": e, **fields}, ensure_ascii=False))\n',
        'self.logger.error("failed %s", json.dumps(details))\n',
        'log.warning(dumps({"event": "x"}))\n',
        """logger.warning('{"event": "x", "board_id": "%s"}', board_id)\n""",
        'logger.info("backup_created", extra={"name": "backup.sqlite"})\n',
        'logger.info("http_request", extra={"request_id": request_id})\n',
        "logger = logging.getLogger(__name__)\n",
        'logger = logging.getLogger("app.services.runs")\n',
        'logger = logging.getLogger("tralalala")\n',
    ],
)
def test_the_guard_refuses_each_hand_built_line(source: str) -> None:
    assert hand_built_log_lines(source)


@pytest.mark.parametrize(
    "source",
    [
        'logger.info("backup_created", extra={"board_id": board_id, "backup_name": name})\n',
        'logger.exception("loop generation run failed", extra={"run_id": run_id})\n',
        "logger.log(level, event, extra=fields)\n",
        'logger.warning("agent %s has no usable key", agent_id)\n',
        'payload_json = json.dumps({"event": "x"})\n',
        'logger = logging.getLogger("tralala.cards")\n',
        "logger = logging.getLogger(ROOT_LOGGER)\n",
    ],
)
def test_the_guard_accepts_a_formatted_line(source: str) -> None:
    assert not hand_built_log_lines(source)
