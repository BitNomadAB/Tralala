"""The pyright-strict scope has no way around the checker: no ``Any``, no ``cast``, no ignore.

``pyrightconfig.json`` lists the strict scope (``app/core``, ``app/schemas``, the generated rows,
the repositories, every service converted to them, the unit tests and the build tools). Strict mode
reports an *unknown* type but accepts a declared ``Any``, a ``cast`` and an ignore comment, each of
which switches the check off for one value. This guard reads every file in the scope and refuses all
three.

Everything else pyright checks runs in its ``standard`` mode, so an entry dropped from ``strict``
would lose strictness without a sound. The scope guard below names those modules, and the modules
of ``app/`` pyright does not check yet, exactly: the scope can only grow.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from collections.abc import Collection
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


# Checked in pyright's standard mode, not strict: the routes and the app factory pass the services'
# untyped results through. An entry leaves this set by moving into "strict".
STANDARD_ONLY = frozenset({"app/api", "app/dev_reset.py", "app/main.py"})
# Not checked yet: each joins the scope once its code is on the repositories.
UNCHECKED = frozenset({"app/services", "app/storage"})


def scope(root: Path = BACKEND_ROOT) -> tuple[list[str], list[str]]:
    """The ``include`` and ``strict`` entries of ``pyrightconfig.json``."""
    config = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
    return [str(entry) for entry in config["include"]], [str(entry) for entry in config["strict"]]


def covered(module: str, entries: Collection[str]) -> bool:
    """Whether ``module`` (relative to the backend) is, or lies inside, one of ``entries``."""
    return any(module == entry or module.startswith(f"{entry}/") for entry in entries)


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


def test_every_app_module_is_type_checked() -> None:
    include, _ = scope()
    unchecked = [module for module in app_modules() if not covered(module, include)]
    assert [module for module in unchecked if not covered(module, UNCHECKED)] == [], (
        "every module of app/ is in pyrightconfig.json's include list"
    )
    # Exact, so it can only shrink: an entry whose modules are all checked must go.
    stale = [
        entry for entry in sorted(UNCHECKED) if not any(covered(m, [entry]) for m in unchecked)
    ]
    assert stale == [], "every module under these is checked now; drop them from UNCHECKED"


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
