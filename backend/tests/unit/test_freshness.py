"""Whether the generated rows match the migrations is a comparison of hashes, not a database."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import freshness


def test_the_schema_inputs_are_the_migrations_the_schema_bootstrap_and_the_tool() -> None:
    root = freshness.BACKEND_ROOT
    inputs = {path.relative_to(root).as_posix() for path in freshness.schema_inputs()}

    assert "migrations/board/versions/0001_board_initial.py" in inputs
    assert "migrations/env.py" in inputs
    assert "app/storage/schema/fts.py" in inputs
    assert "tools/dbgen/schema.py" in inputs
    assert not any("__pycache__" in path for path in inputs)


def test_the_schema_hash_is_stable_and_the_suite_runs_on_current_rows() -> None:
    assert freshness.schema_hash() == freshness.schema_hash()
    assert freshness.problem() is None


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (None, freshness.MISSING),
        ("not json", freshness.MISSING),
        ('{"schema_hash": 1}', freshness.MISSING),
        ('{"schema_hash": "0000"}', freshness.STALE),
    ],
)
def test_a_missing_or_different_manifest_says_how_to_rebuild(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, manifest: str | None, problem: str
) -> None:
    path = tmp_path / "manifest.json"
    if manifest is not None:
        path.write_text(manifest, encoding="utf-8", newline="")
    monkeypatch.setattr(freshness, "MANIFEST_PATH", path)

    assert freshness.problem() == problem
    assert problem.endswith("run python -m tools.dbgen")
