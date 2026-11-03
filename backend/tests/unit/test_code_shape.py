"""Code-shape guards over ``app/`` (GCS-T17), each with fixtures that prove it fails.

1. SQL text is fixed at import time. An f-string that reads as SQL may only interpolate a
   module-level or imported name, a call to one of the ``app.core.sql`` helpers (each checks an
   identifier against an allowed tuple), or a local name whose every assignment is built from those
   and literals (a choice between two fixed fragments included); ``%`` and ``.format`` never build
   SQL. ``python -m tools.dbgen`` compiles every statement, so this keeps request data out of the
   statement text as well as out of the binds.
2. No bare ``threading.Thread``: background work runs on the executors the services own, and the
   listed exceptions say why they are threads.
3. No ``print``: output goes through logging.

A route declared ``async def`` that blocks the event loop is refused by ``test_async_routes.py``
(GCS-T14), and hand-built JSON log lines by the logging guard (GCS-T13).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP = BACKEND_ROOT / "app"

SQL_WORDS = re.compile(
    r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM|WHERE|PRAGMA|CREATE|DROP|ALTER TABLE|VALUES)\b"
)
SQL_HELPERS = frozenset({"column_list", "identifier", "assignments", "insert_columns", "where"})

# Each exception names the file and the reason; the lists only shrink.
THREAD_EXCEPTIONS: dict[str, str] = {
    "app/services/backup_scheduler.py": "one long-lived daemon that wakes on a timer",
}
SQL_EXCEPTIONS: dict[str, str] = {
    "app/core/sql.py": "the helpers themselves join the fragments of the caller's allowed tuples",
}


def _modules() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py") if "generated" not in path.parts)


def _relative(path: Path) -> str:
    return path.relative_to(BACKEND_ROOT).as_posix()


def _is_sql(node: ast.JoinedStr | ast.Constant) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and bool(SQL_WORDS.search(node.value))
    return any(
        isinstance(part, ast.Constant)
        and isinstance(part.value, str)
        and SQL_WORDS.search(part.value)
        for part in node.values
    )


def _is_helper_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sql"
        and node.func.attr in SQL_HELPERS
    )


def _module_names(tree: ast.Module) -> set[str]:
    """Names bound at import time: module-level assignments and imports."""
    names: set[str] = set()
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        elif isinstance(statement, ast.Import | ast.ImportFrom):
            names.update((alias.asname or alias.name).split(".")[0] for alias in statement.names)
        for target in targets:
            names.update(node.id for node in ast.walk(target) if isinstance(node, ast.Name))
    return names


def _fixed(node: ast.expr, known: set[str]) -> bool:
    """Built only from literals, known fixed names and the SQL helpers."""
    if isinstance(node, ast.Constant) or _is_helper_call(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in known
    if isinstance(node, ast.IfExp):
        return _fixed(node.body, known) and _fixed(node.orelse, known)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _fixed(node.left, known) and _fixed(node.right, known)
    if isinstance(node, ast.JoinedStr):
        return all(
            _fixed(part.value, known)
            for part in node.values
            if isinstance(part, ast.FormattedValue)
        )
    return False


def _fixed_locals(function: ast.AST, module_names: set[str]) -> set[str]:
    """Local names whose every assignment in the function is fixed text."""
    assignments: dict[str, list[ast.expr]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
                elif _is_helper_call(node.value):
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name):
                            assignments.setdefault(name.id, []).append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            assignments.setdefault(node.target.id, []).append(node.value)
    fixed: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, values in assignments.items():
            known = module_names | fixed
            if name not in fixed and all(_fixed(value, known) for value in values):
                fixed.add(name)
                changed = True
    return fixed


def sql_findings(source: str) -> list[str]:
    """Every place SQL text is built from something that is not fixed at import time."""
    tree = ast.parse(source)
    module_names = _module_names(tree)
    allowed: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            local = _fixed_locals(node, module_names)
            for inner in ast.walk(node):
                allowed.setdefault(id(inner), set()).update(local)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and _is_sql(node):
            for part in node.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                value = part.value
                if _fixed(value, module_names | allowed.get(id(value), set())):
                    continue
                found.append(f"line {node.lineno}: {{{ast.unparse(value)}}}")
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and _is_sql(node.left)
        ):
            found.append(f"line {node.lineno}: SQL built with %")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and isinstance(node.func.value, ast.Constant)
            and _is_sql(node.func.value)
        ):
            found.append(f"line {node.lineno}: SQL built with .format")
    return found


def thread_findings(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "Thread":
                found.append(f"line {node.lineno}: Thread(...)")
    return found


def print_findings(source: str) -> list[str]:
    return [
        f"line {node.lineno}: print(...)"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_sql_text_is_fixed_at_import_time(path: Path) -> None:
    if _relative(path) in SQL_EXCEPTIONS:
        return
    found = sql_findings(path.read_text(encoding="utf-8"))
    assert not found, f"{_relative(path)} builds SQL from runtime values: {found}"


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_no_bare_thread(path: Path) -> None:
    found = thread_findings(path.read_text(encoding="utf-8"))
    if _relative(path) in THREAD_EXCEPTIONS:
        assert found, f"{_relative(path)} starts no thread any more: remove its exception"
        return
    assert not found, f"{_relative(path)} starts a bare thread: {found}"


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_no_print(path: Path) -> None:
    found = print_findings(path.read_text(encoding="utf-8"))
    assert not found, f"{_relative(path)} prints instead of logging: {found}"


def test_the_exception_lists_name_existing_files() -> None:
    names = {_relative(path) for path in _modules()}
    assert set(THREAD_EXCEPTIONS) <= names
    assert set(SQL_EXCEPTIONS) <= names


@pytest.mark.parametrize(
    "source",
    [
        'def f(name):\n    return text(f"SELECT * FROM {name}")\n',
        "def f(q):\n    return f\"SELECT id FROM cards WHERE title = '{q}'\"\n",
        'def f(q):\n    return text("SELECT * FROM cards WHERE id = %s" % q)\n',
        'def f(q):\n    return "DELETE FROM cards WHERE id = {}".format(q)\n',
        'def f(self):\n    return f"UPDATE cards SET {self.column} = 1"\n',
        'def f(q):\n    joins = ""\n    joins += q\n    return f"SELECT 1 FROM c{joins}"\n',
    ],
)
def test_the_sql_guard_flags_runtime_values(source: str) -> None:
    assert sql_findings(source)


@pytest.mark.parametrize(
    "source",
    [
        '_COLUMNS = "id, name"\n_Q = text(f"SELECT {_COLUMNS} FROM lists")\n',
        'def f(cols):\n    return text(f"SELECT {sql.column_list(cols)} FROM cards")\n',
        "def f(c, a):\n    name = sql.identifier(c, a)\n"
        '    return f"UPDATE loops SET {name} = 1"\n',
        'def f(q):\n    return f"Search for {q} returned nothing"\n',
        'from .sqlite import LIMIT\n_Q = f"PRAGMA busy_timeout={LIMIT}"\n',
        '_J = "x"\ndef f(q):\n    d = "DESC" if q else "ASC"\n    j = _J if q else ""\n'
        '    return f"SELECT 1 FROM c{j} ORDER BY a {d}"\n',
    ],
)
def test_the_sql_guard_accepts_fixed_text(source: str) -> None:
    assert not sql_findings(source)


@pytest.mark.parametrize(
    "source",
    [
        "import threading\nthreading.Thread(target=run).start()\n",
        "from threading import Thread\nThread(target=run).start()\n",
    ],
)
def test_the_thread_guard_flags_a_thread(source: str) -> None:
    assert thread_findings(source)


def test_the_thread_guard_accepts_an_executor() -> None:
    assert not thread_findings("ThreadPoolExecutor(max_workers=2).submit(run)\n")


def test_the_print_guard_flags_print_and_accepts_logging() -> None:
    assert print_findings("print('hello')\n")
    assert not print_findings("logger.info('hello')\n")
