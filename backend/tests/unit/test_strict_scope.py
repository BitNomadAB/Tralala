"""The pyright-strict scope has no way around the checker: no ``Any``, no ``cast``, no ignore.

``pyrightconfig.json`` lists the strict scope: all of ``app/`` (the routes, the app factory and the
development reset, ``app/core``, ``app/schemas``, the generated rows, the repositories, the storage
layer and every service), the unit tests and the build tools. Strict mode reports an *unknown* type
but accepts a declared ``Any``, a ``cast`` and an ignore comment, each of which switches the check
off for one value. This guard reads every file in the scope and refuses all three.

Every module pyright checks is in the strict scope; one that is included but not strict would run
in pyright's ``standard`` mode, so an entry dropped from ``strict`` would lose strictness without a
sound. The scope guard below names those modules (none) exactly, and refuses a module of ``app/``
that neither list covers, so a new module joins the strict scope with its first line: the scope
can only grow.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from collections.abc import Collection, Iterable
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TYPING = {"typing", "typing_extensions"}
_ESCAPES = {"Any", "cast"}
_IGNORE = re.compile(r"#\s*(?:type|pyright)\s*:\s*ignore\b")


def strict_files(root: Path = BACKEND_ROOT) -> list[Path]:
    config = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
    files: list[Path] = []
    for entry in config["strict"]:
        path = root / entry
        found = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        files += [file for file in found if "__pycache__" not in file.parts]
    return files


def escapes(source: str, filename: str = "<source>") -> list[str]:
    """Every ``Any``, ``cast`` and ignore comment in ``source``, as ``file:line: what``."""
    found: list[str] = []
    tree = ast.parse(source, filename)
    modules = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name in _TYPING
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _TYPING:
            found += [
                f"{filename}:{node.lineno}: imports {node.module}.{alias.name}"
                for alias in node.names
                if alias.name in _ESCAPES
            ]
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in _ESCAPES
            and isinstance(node.value, ast.Name)
            and node.value.id in modules
        ):
            found.append(f"{filename}:{node.lineno}: uses {node.value.id}.{node.attr}")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and _IGNORE.search(token.string):
            found.append(f"{filename}:{token.start[0]}: {token.string.strip()}")
    return found


def test_the_strict_scope_has_no_escape_hatch() -> None:
    files = strict_files()
    assert any(file.name == "lists.py" for file in files)
    found: list[str] = []
    for path in files:
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        found += escapes(path.read_text(encoding="utf-8"), relative)
    assert found == [], "the strict scope must type its values, not switch pyright off:\n" + (
        "\n".join(found)
    )


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any",
        "from typing import Protocol, cast",
        "from typing_extensions import Any",
        "import typing\nvalue: typing.Any = 1",
        "import typing as t\nvalue = t.cast(int, 1)",
        "value = 1  # type: ignore",
        "value = 1  # type: ignore[assignment]",
        "value = 1  # pyright: ignore[reportUnknownVariableType]",
    ],
)
def test_the_guard_flags_an_escape(source: str) -> None:
    assert escapes(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Protocol, Self",
        "# pyright: reportPrivateUsage=false",
        "note = 'Any cast # type: ignore inside a string is text'",
        "class Row:\n    def cast(self) -> None: ...\nRow().cast()",
    ],
)
def test_the_guard_accepts_typed_code(source: str) -> None:
    assert escapes(source) == []


# Checked in pyright's standard mode, not strict: nothing. An entry leaves this set by moving into
# "strict", and a new one needs the reason it cannot be strict yet.
STANDARD_ONLY: frozenset[str] = frozenset()


def scope(root: Path = BACKEND_ROOT) -> tuple[list[str], list[str]]:
    """The ``include`` and ``strict`` entries of ``pyrightconfig.json``."""
    config = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
    return [str(entry) for entry in config["include"]], [str(entry) for entry in config["strict"]]


def covered(module: str, entries: Collection[str]) -> bool:
    """Whether ``module`` (relative to the backend) is, or lies inside, one of ``entries``."""
    return any(module == entry or module.startswith(f"{entry}/") for entry in entries)


def uncovered(modules: Iterable[str], entries: Collection[str]) -> list[str]:
    """The ``modules`` that none of ``entries`` covers, in their order."""
    return [module for module in modules if not covered(module, entries)]


def app_modules(root: Path = BACKEND_ROOT) -> list[str]:
    """Every Python module of ``app/`` that holds code, as a path relative to the backend."""
    return [
        path.relative_to(root).as_posix()
        for path in sorted((root / "app").rglob("*.py"))
        if "__pycache__" not in path.parts and path.read_text(encoding="utf-8").strip()
    ]


def test_only_the_named_modules_are_checked_below_strict() -> None:
    include, strict = scope()
    assert [entry for entry in strict if entry not in include] == [], (
        "pyright ignores a strict entry that is not also included"
    )
    assert set(include) - set(strict) == STANDARD_ONLY


def test_every_app_module_is_type_checked_strictly() -> None:
    include, strict = scope()
    modules = app_modules()
    # The walk found the app, so the checks below cannot pass over nothing.
    assert {"app/main.py", "app/services/__init__.py", "app/services/runtime.py"} <= set(modules)
    assert uncovered(modules, include) == [], (
        "every module of app/ is in pyrightconfig.json's include list"
    )
    assert uncovered(modules, strict) == [], "every module of app/ is checked strictly"


def test_a_module_outside_the_scope_is_named() -> None:
    modules = ["app/core/dates.py", "app/services/new_service.py", "app/main.py"]
    assert uncovered(modules, ["app/core", "app/main.py"]) == ["app/services/new_service.py"]
    assert uncovered(modules, ["app/core", "app/services", "app/main.py"]) == []


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("app/core/dates.py", True),
        ("app/main.py", True),
        ("app/core", True),
        ("app/corelib/dates.py", False),
        ("app/main.pyc", False),
        ("app/storage/sqlite.py", False),
    ],
)
def test_covered_matches_whole_path_segments(module: str, expected: bool) -> None:
    assert covered(module, ["app/core", "app/main.py"]) is expected
