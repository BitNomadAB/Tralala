"""Whether the generated rows were built from the migrations as they are now.

``python -m tools.dbgen`` writes the rows and a manifest that records a SHA-256 of everything the
schema is built from: the migrations, the schema bootstrap the application runs after them and the
build tool itself. Comparing that hash needs no database, so the unit tests can refuse to run
against stale rows and say what to do instead.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = BACKEND_ROOT / "app" / "db" / "generated"
MANIFEST_PATH = GENERATED_DIR / "manifest.json"

REBUILD = "run python -m tools.dbgen"
MISSING = f"The generated database rows are missing: {REBUILD}"
STALE = f"The generated database rows are stale: {REBUILD}"

# Everything the migrated schema, the generated rows and the SQL check depend on.
_INPUTS = (
    BACKEND_ROOT / "migrations",
    BACKEND_ROOT / "app" / "storage" / "schema",
    BACKEND_ROOT / "tools" / "dbgen",
)


def schema_inputs() -> list[Path]:
    """The input files in a stable order; bytecode is not an input."""
    files = [
        path
        for root in _INPUTS
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    return sorted(files, key=lambda path: path.relative_to(BACKEND_ROOT).as_posix())


def schema_hash() -> str:
    digest = hashlib.sha256()
    for path in schema_inputs():
        digest.update(path.relative_to(BACKEND_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        # Line endings are not content: a Windows checkout with CRLF hashes like a Linux one.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def recorded_schema_hash() -> str | None:
    """The schema hash the last complete build recorded, or None without a readable manifest."""
    try:
        manifest: object = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    match manifest:
        case {"schema_hash": str() as recorded}:
            return recorded
        case _:
            return None


def problem() -> str | None:
    """Why the generated rows cannot be trusted, or None when they match the inputs."""
    recorded = recorded_schema_hash()
    if recorded is None:
        return MISSING
    if recorded != schema_hash():
        return STALE
    return None
