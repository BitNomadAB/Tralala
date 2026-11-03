"""Services reach a database only through the repository Protocols and the units of work.

AGENTS.md rule 1: a service never holds ``BoardDatabaseManager``, ``Registry``, a connection or SQL
text of its own. This guard reads every module in ``app/services/`` and fails on the two things
that make that possible: importing from SQLAlchemy or from ``app.storage``, and calling ``text`` or
``exec_driver_sql``. Without those imports a module in pyright's strict scope cannot type a storage
handle either, so the import rule and the strict scope together hold the line.

``NOT_YET_ON_REPOSITORIES`` lists the modules written before the rule. It only shrinks: a module
that no longer reaches storage itself must leave the list, and a module that is not on it must
follow the rule from its first line.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SERVICES = BACKEND_ROOT / "app" / "services"

# The composition root builds the storage objects and hands them to the SQL repositories; wiring is
# its job, so it is the one permanent exception.
COMPOSITION_ROOT = "__init__.py"

# Modules that still reach storage themselves. Each leaves the list when it is converted.
NOT_YET_ON_REPOSITORIES = frozenset(
    {
        "activity.py",  # log_activity(conn) stays for the unconverted callers below
        "common.py",  # SQL helpers the unconverted callers below still use
        "loop_bridge.py",  # transitional; deleted when loop_qa and loop_generation are converted
        "loop_generation.py",
    }
)

FORBIDDEN_CALLS = frozenset({"text", "exec_driver_sql"})
FORBIDDEN_PREFIXES = ("sqlalchemy.", "app.storage")


def _forbidden(module: str) -> bool:
    return module == "sqlalchemy" or module.startswith(FORBIDDEN_PREFIXES)


def _relative_module(node: ast.ImportFrom) -> str:
    """The absolute module an import names, as seen from ``app.services``."""
    if node.level == 0:
        return node.module or ""
    base = ["app", "services"][: max(0, 2 - (node.level - 1))]
    return ".".join([*base, *([node.module] if node.module else [])])


def storage_reaches(source: str) -> list[str]:
    """Every import or call in ``source`` that reaches a database without a repository."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if _forbidden(alias.name)
            )
        elif isinstance(node, ast.ImportFrom):
            module = _relative_module(node)
            if _forbidden(module):
                found.append(f"line {node.lineno}: from {module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else None
            if isinstance(func, ast.Name):
                name = func.id
            if name in FORBIDDEN_CALLS:
                found.append(f"line {node.lineno}: {name}(...)")
    return found


def _service_modules() -> list[Path]:
    return sorted(path for path in SERVICES.glob("*.py") if path.name != COMPOSITION_ROOT)


@pytest.mark.parametrize("path", _service_modules(), ids=lambda path: path.name)
def test_a_service_reaches_storage_only_through_repositories(path: Path) -> None:
    reaches = storage_reaches(path.read_text(encoding="utf-8"))
    if path.name in NOT_YET_ON_REPOSITORIES:
        assert reaches, (
            f"{path.name} no longer reaches storage itself: remove it from NOT_YET_ON_REPOSITORIES"
        )
    else:
        assert not reaches, (
            f"{path.name} reaches storage without a repository (AGENTS.md rule 1): {reaches}"
        )


def test_the_list_names_only_existing_modules() -> None:
    names = {path.name for path in _service_modules()}
    unknown = NOT_YET_ON_REPOSITORIES - names
    assert not unknown, sorted(unknown)


@pytest.mark.parametrize(
    "source",
    [
        "from sqlalchemy import text\n",
        "import sqlalchemy\n",
        "from sqlalchemy.engine import Connection\n",
        "from ..storage.board_db import BoardDatabaseManager\n",
        "from ..storage import registry\n",
        "from app.storage.sqlite import utcnow\n",
        "import app.storage.registry\n",
        "conn.execute(text('SELECT 1'))\n",
        "conn.exec_driver_sql('SELECT 1')\n",
        "def f(sql):\n    return sql.text('x')\n",
    ],
)
def test_the_guard_refuses_each_way_to_reach_storage(source: str) -> None:
    assert storage_reaches(source)


@pytest.mark.parametrize(
    "source",
    [
        "from ..repositories.board import BoardUnitOfWork\n",
        "from ..core.dates import utcnow\n",
        "from .ordering import place\n",
        "message = 'SELECT text FROM t'\n",
        "def text_of(x: str) -> str:\n    return x\n",
    ],
)
def test_the_guard_accepts_repository_code(source: str) -> None:
    assert not storage_reaches(source)
