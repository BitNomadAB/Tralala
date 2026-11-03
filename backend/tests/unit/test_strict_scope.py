"""The pyright-strict scope has no way around the checker: no ``Any``, no ``cast``, no ignore.

``pyrightconfig.json`` lists the strict scope (the generated rows, the repositories, every service
converted to them, the unit tests and the build tools). Strict mode reports an *unknown* type but
accepts a declared ``Any``, a ``cast`` and an ignore comment, each of which switches the check off
for one value. This guard reads every file in the scope and refuses all three.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
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
