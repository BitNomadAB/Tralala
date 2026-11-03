"""Every Alembic command runs under ``runner._ALEMBIC_LOCK``, and the lock is the innermost one.

For the length of a command Alembic writes its ``EnvironmentContext`` and, while revisions run, its
``Operations`` into the globals of the modules ``alembic.context`` and ``alembic.op``, and deletes
them again on exit, so two commands in two threads break each other. The runner
(``app/storage/schema/runner.py``) holds one process-wide lock around each command; this guard
reads the source (no database, no import of Alembic) and keeps it that way:

* only the runner imports an Alembic module whose API installs those globals (a command, the
  environment, ``Operations``, or the two modules themselves), in ``app/`` and in ``tools/``;
* every use of such an import sits inside ``with _ALEMBIC_LOCK:``;
* the locked block calls nothing but the Alembic command, and the code the command runs (env.py
  and the revisions) imports nothing from the application, so the lock is never held while another
  lock (a board's, the board manager's, a database's) is awaited: no lock-order inversion.

``tests/infrastructure/test_alembic_lock.py`` shows two board databases migrating at once on real
files.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNNER = "app/storage/schema/runner.py"
LOCK = "_ALEMBIC_LOCK"
SCANNED = ("app", "tools")
APPLICATION_PACKAGES = frozenset({"app", "tools"})

# Alembic modules with an API that installs the alembic.context / alembic.op globals: every command
# (each enters an EnvironmentContext), the environment itself, ``Operations.context``, and the two
# proxy modules. ``alembic.config``, ``alembic.migration`` (``MigrationContext.configure``) and
# ``alembic.script`` (``ScriptDirectory``) install none and stay outside the lock.
PROXY_MODULES = (
    "alembic.command",
    "alembic.context",
    "alembic.op",
    "alembic.environment",
    "alembic.runtime.environment",
    "alembic.operations",
)


def _installs_proxies(dotted: str) -> bool:
    return any(dotted == module or dotted.startswith(module + ".") for module in PROXY_MODULES)


def proxy_bindings(tree: ast.AST) -> dict[str, int]:
    """Names bound to the proxy-installing part of Alembic, with the line of their import."""
    bound: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is None and alias.name.split(".")[0] == "alembic":
                    # ``import alembic`` or ``import alembic.x`` binds the package: it reaches all.
                    bound["alembic"] = node.lineno
                elif alias.asname is not None and _installs_proxies(alias.name):
                    bound[alias.asname] = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            for alias in node.names:
                if _installs_proxies(f"{node.module}.{alias.name}"):
                    bound[alias.asname or alias.name] = node.lineno
    return bound


def _is_lock(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Name) and expression.id == LOCK


def _root(expression: ast.expr) -> str | None:
    while isinstance(expression, ast.Attribute):
        expression = expression.value
    return expression.id if isinstance(expression, ast.Name) else None


class _Scan:
    def __init__(self, filename: str, bindings: dict[str, int]) -> None:
        self.filename = filename
        self.bindings = bindings
        self.found: list[str] = []
        self.locked_calls: list[str] = []

    def walk(self, node: ast.AST, locked: bool) -> None:
        if isinstance(node, ast.With | ast.AsyncWith):
            index = next(
                (i for i, item in enumerate(node.items) if _is_lock(item.context_expr)), None
            )
            if index is not None:
                for item in node.items[:index]:
                    self.walk(item, locked)
                # Everything after the lock in the with statement runs while it is held.
                for child in [*node.items[index + 1 :], *node.body]:
                    self.walk(child, True)
                return
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            locked = False  # a body defined under the lock runs whenever it is called
        if isinstance(node, ast.Call) and locked:
            if _root(node.func) in self.bindings:
                self.locked_calls.append(ast.unparse(node))
            else:
                self.found.append(
                    f"{self.filename}:{node.lineno}: {ast.unparse(node)} runs under {LOCK}; the"
                    " locked block may only run the Alembic command (compute arguments first)"
                )
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in self.bindings
            and not locked
        ):
            self.found.append(
                f"{self.filename}:{node.lineno}: {node.id} is used outside `with {LOCK}:`"
            )
        for child in ast.iter_child_nodes(node):
            self.walk(child, locked)


def _scan(source: str, filename: str) -> _Scan:
    tree = ast.parse(source, filename)
    scan = _Scan(filename, proxy_bindings(tree))
    if filename != RUNNER:
        scan.found += [
            f"{filename}:{line}: imports {name} from Alembic; run commands through"
            f" {RUNNER} (stamp, upgrade)"
            for name, line in sorted(scan.bindings.items(), key=lambda item: item[1])
        ]
    scan.walk(tree, False)
    return scan


def violations(source: str, filename: str = RUNNER) -> list[str]:
    return _scan(source, filename).found


def application_imports(source: str, filename: str = "<revision>") -> list[str]:
    """Imports of the application in code that runs inside an Alembic command."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] if node.level == 0 else ["." * node.level]
        else:
            continue
        found += [
            f"{filename}:{node.lineno}: imports {name}"
            for name in names
            if name.startswith(".") or name.split(".")[0] in APPLICATION_PACKAGES
        ]
    return found


def _sources(*roots: str) -> dict[str, str]:
    return {
        path.relative_to(BACKEND_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for root in roots
        for path in sorted((BACKEND_ROOT / root).rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def test_every_alembic_command_runs_under_the_lock() -> None:
    sources = _sources(*SCANNED)
    found = [line for name, source in sources.items() for line in violations(source, name)]

    assert found == [], "Run Alembic commands one at a time:\n" + "\n".join(found)
    # Positive control: the scan sees runner.py's import and the two commands it locks.
    runner = _scan(sources[RUNNER], RUNNER)
    assert set(runner.bindings) == {"command"}
    assert runner.locked_calls == [
        "command.stamp(config, target)",
        "command.upgrade(config, revision)",
    ]


def test_the_code_a_command_runs_imports_nothing_from_the_application() -> None:
    sources = _sources("migrations")
    found = [line for name, source in sources.items() for line in application_imports(source, name)]

    assert found == [], "A revision runs under the Alembic lock:\n" + "\n".join(found)
    # Positive control: env.py and both chains' revisions were read.
    assert "migrations/env.py" in sources
    assert any(name.startswith("migrations/board/versions/") for name in sources)
    assert any(name.startswith("migrations/registry/versions/") for name in sources)


@pytest.mark.parametrize(
    ("source", "filename"),
    [
        ("from alembic import command\ncommand.upgrade(config, 'head')", RUNNER),
        (
            "from alembic import command as c\nwith _ALEMBIC_LOCK:\n    pass\nc.stamp(config, 'x')",
            RUNNER,
        ),
        ("from alembic.command import upgrade\nupgrade(config, 'head')", RUNNER),
        ("import alembic.command\nalembic.command.upgrade(config, 'head')", RUNNER),
        ("import alembic\nalembic.command.stamp(config, 'base')", RUNNER),
        ("import alembic.command as commands\ncommands.upgrade(config, 'head')", RUNNER),
        ("from alembic import command\nrun = command.upgrade", RUNNER),
        (
            "from alembic import command\nwith other_lock:\n    command.upgrade(config, 'head')",
            RUNNER,
        ),
        (
            "from alembic.runtime.environment import EnvironmentContext\n"
            "with EnvironmentContext(config, script):\n    script.run_env()",
            RUNNER,
        ),
        (
            "from alembic.operations import Operations\n"
            "with Operations.context(migration_context):\n    pass",
            RUNNER,
        ),
        ("from alembic import context\ncontext.configure(connection=connection)", RUNNER),
        (
            "from alembic import command\n"
            "def upgrade(config):\n    command.upgrade(config, 'head')",
            RUNNER,
        ),
        (
            "from alembic import command\nwith _ALEMBIC_LOCK:\n"
            "    def later():\n        command.upgrade(config, 'head')",
            RUNNER,
        ),
        # The locked block runs nothing else, so it can never wait for a board lock.
        (
            "from alembic import command\nwith _ALEMBIC_LOCK:\n"
            "    boards.locked(board_id)\n    command.upgrade(config, 'head')",
            RUNNER,
        ),
        (
            "from alembic import command\nwith _ALEMBIC_LOCK:\n"
            "    command.upgrade(_config(chain, connection), 'head')",
            RUNNER,
        ),
        (
            "from alembic import command\nwith _ALEMBIC_LOCK, boards.locked(board_id):\n"
            "    command.upgrade(config, 'head')",
            RUNNER,
        ),
        # Outside runner.py even a locked command is refused: there is one place for them.
        (
            "from alembic import command\nwith _ALEMBIC_LOCK:\n    command.upgrade(config, 'head')",
            "app/storage/migration_manager.py",
        ),
        ("from alembic.operations import Operations", "app/storage/board_db.py"),
        ("def migrate():\n    from alembic import command", "tools/dbgen/schema.py"),
    ],
)
def test_the_guard_flags_a_command_outside_the_lock(source: str, filename: str) -> None:
    assert violations(source, filename) != []


@pytest.mark.parametrize(
    ("source", "filename"),
    [
        (
            "from alembic import command\nconfig = _config(chain, connection)\n"
            "with _ALEMBIC_LOCK:\n    command.upgrade(config, revision)",
            RUNNER,
        ),
        (
            "from alembic import command\ndef stamp(config, revision):\n"
            "    with _ALEMBIC_LOCK:\n        command.stamp(config, revision or BASELINE)",
            RUNNER,
        ),
        (
            "from alembic.migration import MigrationContext\n"
            "MigrationContext.configure(connection).get_current_revision()",
            "app/storage/board_db.py",
        ),
        (
            "from alembic.script import ScriptDirectory\n"
            "ScriptDirectory.from_config(config).get_current_head()",
            "tools/dbgen/schema.py",
        ),
        (
            "from alembic.config import Config\nconfig = Config()",
            "app/storage/migration_manager.py",
        ),
        ("import alembic.config as alembic_config\nalembic_config.Config()", "app/main.py"),
        ("runner.upgrade('board', connection)", "tools/dbgen/schema.py"),
        ("note = 'command.upgrade(config) inside a string is not a call'", RUNNER),
    ],
)
def test_the_guard_accepts_a_locked_command_and_the_readers(source: str, filename: str) -> None:
    assert violations(source, filename) == []


@pytest.mark.parametrize(
    "source",
    [
        "from app.storage.board_db import BoardDatabaseManager",
        "import app.services.boards",
        "from tools.dbgen import schema",
        "from . import helpers",
        "def upgrade():\n    from app.storage import registry",
    ],
)
def test_the_revision_scan_flags_an_application_import(source: str) -> None:
    assert application_imports(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from alembic import op",
        "import sqlalchemy as sa",
        "from sqlalchemy.dialects import sqlite",
        "from alembic import context",
        "import logging",
    ],
)
def test_the_revision_scan_accepts_alembic_and_sqlalchemy(source: str) -> None:
    assert application_imports(source) == []
