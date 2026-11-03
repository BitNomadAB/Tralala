"""The unit suite is unit tests only: no application, no database, no waiting, no threads.

A test gives a function a fixed input and checks what comes back. It never builds the FastAPI app,
never opens SQLite, never runs a migration, never sleeps and never starts a thread, so the whole
suite runs in seconds and the same input always gives the same answer. Whatever is expensive and
shared is a session-scoped fixture, built once. A service is tested through its repository
Protocols with the in-memory fakes in ``tests/unit/fakes``, never through their SQL implementations
or the build tool's in-memory database.

This guard reads every Python file under ``tests/unit/`` and fails on the imports and calls that
turn a unit test back into an integration test. It reads the syntax tree, so a forbidden name inside
a string (like the fixtures below) is not a violation. ``tests/infrastructure/`` is the one place
that opens SQLite, and it is a separate command.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

UNIT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = UNIT_ROOT.parents[1]

# The application factory and its HTTP test clients, and every layer that opens a database: the
# storage layer, the SQL repositories and the build tool that migrates into memory.
FORBIDDEN_MODULES = (
    "fastapi.testclient",
    "starlette.testclient",
    "app.main",
    "sqlite3",
    "sqlalchemy",
    "alembic",
    "app.storage",
    "app.repositories.sql",
    "tools.dbgen",
)
# Modules inside a forbidden package that open nothing: the build tool's schema rules are plain
# functions over plain data, so the unit suite holds them to fixed descriptions.
PURE_MODULES = ("tools.dbgen.rules",)
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
    if any(name == pure or name.startswith(pure + ".") for pure in PURE_MODULES):
        return None
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
                # "from tools.dbgen import rules" names a pure module inside a forbidden package.
                if _forbidden_module(full):
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
    for path in sorted(UNIT_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(BACKEND_ROOT).as_posix()
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
        "from app.repositories.sql.lists import SqlListRepository",
        "from app.repositories import sql",
        "import app.repositories.sql.board",
        "from tools.dbgen import schema",
        "from tools import dbgen",
        "import tools.dbgen.sqlcheck",
        "from tools.dbgen import rules, schema",
        "from tools.dbgen.rulesets import anything",
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
        "from app.repositories.board import BoardUnitOfWork",
        "from app.db.generated.board import ListsRow",
        "from app.core import sql",
        "note = 'time.sleep(1) and import sqlite3 are fine inside a string'",
        "class Fake:\n    def sleep(self, seconds):\n        return seconds\nFake().sleep(1)",
        "from app.core import platform\nplatform.remove_tree",
        "from tools.dbgen import rules",
        "from tools.dbgen.rules import Table, schema_problems",
        "import tools.dbgen.rules",
    ],
)
def test_the_guard_accepts_a_unit_test(source: str) -> None:
    assert violations(source) == []


def test_a_violation_names_the_file_and_the_line() -> None:
    source = "import json\n\nfrom sqlalchemy import text\n"
    assert violations(source, "tests/test_example.py") == [
        "tests/test_example.py:3: imports sqlalchemy.text"
    ]


def test_a_pure_module_imports_nothing_that_opens_a_database() -> None:
    """A pure module uses the standard library only: no sibling module, no database layer."""
    for module in PURE_MODULES:
        path = BACKEND_ROOT.joinpath(*module.split(".")).with_suffix(".py")
        source = path.read_text(encoding="utf-8")
        relative = [
            node.lineno
            for node in ast.walk(ast.parse(source, str(path)))
            if isinstance(node, ast.ImportFrom) and node.level > 0
        ]
        assert relative == [], f"{module} imports a sibling module at line(s) {relative}"
        assert violations(source, module) == []
