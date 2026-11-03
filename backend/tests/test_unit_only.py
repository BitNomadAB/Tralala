"""The backend suite is unit tests only: no application, no database, no waiting, no threads.

A test gives a function a fixed input and checks what comes back. It never builds the FastAPI app,
never opens SQLite, never runs a migration, never sleeps and never starts a thread, so the whole
suite runs in seconds and the same input always gives the same answer. Whatever is expensive and
shared is a session-scoped fixture, built once.

This guard reads every Python file under ``tests/`` and fails on the imports and calls that turn a
unit test back into an integration test. It reads the syntax tree, so a forbidden name inside a
string (like the fixtures below) is not a violation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parent

# The application factory and its HTTP test clients, and every layer that opens a database.
FORBIDDEN_MODULES = (
    "fastapi.testclient",
    "starlette.testclient",
    "app.main",
    "sqlite3",
    "sqlalchemy",
    "alembic",
    "app.storage",
)
# Calls that wait for real time or run work beside the test: (module, attribute).
FORBIDDEN_CALLS = frozenset(
    {
        ("time", "sleep"),
        ("asyncio", "sleep"),
        ("threading", "Thread"),
    }
)
DYNAMIC_IMPORTS = frozenset({("importlib", "import_module"), ("builtins", "__import__")})


def _forbidden_module(name: str) -> str | None:
    for prefix in FORBIDDEN_MODULES:
        if name == prefix or name.startswith(prefix + "."):
            return prefix
    return None


def _bindings(tree: ast.AST) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Local names bound to a module, and local names bound to a module attribute."""
    modules: dict[str, str] = {}
    attributes: dict[str, tuple[str, str]] = {"__import__": ("builtins", "__import__")}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    modules[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                attributes[alias.asname or alias.name] = (node.module, alias.name)
    return modules, attributes


def _call_target(
    func: ast.expr, modules: dict[str, str], attributes: dict[str, tuple[str, str]]
) -> tuple[str, str] | None:
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return modules.get(func.value.id, func.value.id), func.attr
    if isinstance(func, ast.Name):
        return attributes.get(func.id)
    return None


def violations(source: str, filename: str = "<source>") -> list[str]:
    """Every forbidden import and call in ``source``, as ``file:line: reason``."""
    tree = ast.parse(source, filename)
    modules, attributes = _bindings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                f"{filename}:{node.lineno}: imports {alias.name}"
                for alias in node.names
                if _forbidden_module(alias.name)
            )
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if _forbidden_module(node.module) or _forbidden_module(full):
                    found.append(f"{filename}:{node.lineno}: imports {full}")
        elif isinstance(node, ast.Call):
            target = _call_target(node.func, modules, attributes)
            if target in FORBIDDEN_CALLS:
                found.append(f"{filename}:{node.lineno}: calls {target[0]}.{target[1]}")
            elif target in DYNAMIC_IMPORTS and node.args:
                first = node.args[0]
                if (
                    isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                    and _forbidden_module(first.value)
                ):
                    found.append(f"{filename}:{node.lineno}: imports {first.value}")
    return found


def test_the_test_suite_is_unit_tests_only() -> None:
    found: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(TESTS_ROOT.parent).as_posix()
        found += violations(path.read_text(encoding="utf-8"), relative)
    assert found == [], "Backend tests are unit tests only:\n" + "\n".join(found)


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi.testclient import TestClient",
        "from starlette.testclient import TestClient",
        "from fastapi import testclient",
        "from app.main import create_app",
        "import app.main",
        "from app import main",
        "import sqlite3",
        "import sqlite3 as db",
        "import sqlalchemy",
        "from sqlalchemy import text",
        "from sqlalchemy.engine import Engine",
        "import alembic",
        "from alembic import command",
        "from app.storage.board_db import BoardDatabaseManager",
        "from app.storage import registry",
        "from app import storage",
        "import importlib\nimportlib.import_module('sqlite3')",
        "__import__('sqlalchemy.orm')",
        "import time\ntime.sleep(0.05)",
        "import time as clock\nclock.sleep(1)",
        "from time import sleep\nsleep(1)",
        "from time import sleep as nap\nnap(1)",
        "import asyncio\nasync def wait():\n    await asyncio.sleep(0)",
        "from asyncio import sleep\nasync def wait():\n    await sleep(0)",
        "import threading\nthreading.Thread(target=print).start()",
        "from threading import Thread\nThread(target=print)",
        "def helper():\n    import time\n    time.sleep(0.1)",
    ],
)
def test_the_guard_flags_an_integration_habit(source: str) -> None:
    assert violations(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "import time\ntime.monotonic()",
        "import threading\nthreading.Lock()",
        "from app.core.security import hash_password",
        "from app.services.backups import BACKUP_PATTERN",
        "from app.api.mcp import render_bootstrap",
        "note = 'time.sleep(1) and import sqlite3 are fine inside a string'",
        "class Fake:\n    def sleep(self, seconds):\n        return seconds\nFake().sleep(1)",
        "from app.core import platform\nplatform.remove_tree",
    ],
)
def test_the_guard_accepts_a_unit_test(source: str) -> None:
    assert violations(source) == []


def test_a_violation_names_the_file_and_the_line() -> None:
    source = "import json\n\nfrom sqlalchemy import text\n"
    assert violations(source, "tests/test_example.py") == [
        "tests/test_example.py:3: imports sqlalchemy.text"
    ]
