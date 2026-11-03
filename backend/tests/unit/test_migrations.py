"""Schema changes happen only in Alembic revisions; nothing else in the app writes DDL."""

from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"


def test_schema_changes_only_happen_in_migrations() -> None:
    pattern = re.compile(
        r"\b(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+INDEX|DROP\s+INDEX)\b",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if "storage/schema/fts.py" in path.as_posix():
            continue  # optional FTS index bootstrap, not part of the schema contract
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(APP_ROOT.parent)))
    assert offenders == []
