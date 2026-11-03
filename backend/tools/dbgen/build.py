"""Run the pipeline, cache it in a manifest, and report what was done and how long it took."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict

from pydantic import TypeAdapter, ValidationError

from app.db import freshness

from . import BuildError, sqlcheck

if TYPE_CHECKING:
    from .schema import Migrated

# render and schema import SQLAlchemy and Alembic; they are imported where a run needs to migrate.

GENERATED = ("registry.py", "board.py")


class _ManifestData(TypedDict):
    schema_hash: str
    sqlite_version: str
    generated: dict[str, str]
    statements: list[str]


_MANIFEST = TypeAdapter(_ManifestData)


@dataclass(slots=True)
class Manifest:
    """What the last complete build was made from; written only when every step passed."""

    schema_hash: str = ""
    sqlite_version: str = ""
    generated: dict[str, str] = field(default_factory=dict[str, str])
    statements: list[str] = field(default_factory=list[str])

    @classmethod
    def read(cls) -> Manifest:
        try:
            data = _MANIFEST.validate_json(freshness.MANIFEST_PATH.read_bytes())
        except (OSError, ValidationError):
            return cls()
        return cls(
            data["schema_hash"], data["sqlite_version"], data["generated"], data["statements"]
        )

    def text(self) -> str:
        data = {
            "schema_hash": self.schema_hash,
            "sqlite_version": self.sqlite_version,
            "generated": self.generated,
            "statements": sorted(set(self.statements)),
        }
        return json.dumps(data, indent=2) + "\n"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _generated_digests() -> dict[str, str]:
    found: dict[str, str] = {}
    for name in GENERATED:
        path = freshness.GENERATED_DIR / name
        if path.is_file():
            found[name] = _digest(path.read_bytes())
    return found


def _write(name: str, content: str) -> bool:
    """Write LF text; leave an identical file alone, so a no-op run touches nothing."""
    path = freshness.GENERATED_DIR / name
    data = content.encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True


class _Clock:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def seconds(self) -> str:
        return f"{time.perf_counter() - self.started:.2f} s"


def _say(line: str) -> None:
    sys.stdout.write(f"dbgen: {line}\n")


def _fail(lines: Sequence[str]) -> int:
    for line in lines:
        sys.stderr.write(f"{line}\n")
    return 1


@dataclass(slots=True)
class _Databases:
    """The in-memory databases, migrated on first use only: a warm run never needs them."""

    opened: dict[str, Migrated] = field(default_factory=dict[str, "Migrated"])

    def migrated(self) -> dict[str, Migrated]:
        from . import schema

        if not self.opened:
            for chain in schema.CHAINS:
                self.opened[chain] = schema.migrate(chain)
        return self.opened

    def get(self) -> dict[str, sqlite3.Connection]:
        return {chain: migrated.database for chain, migrated in self.migrated().items()}

    def close(self) -> None:
        for migrated in self.opened.values():
            migrated.database.close()


def _generate(databases: _Databases) -> list[str]:
    """Validate the chains, migrate, apply the schema rules and write the rows; problems or []."""
    from . import render, rules, schema

    problems = [problem for chain in schema.CHAINS for problem in schema.chain_problems(chain)]
    if problems:
        return problems
    tables = {chain: schema.read_tables(found) for chain, found in databases.migrated().items()}
    problems = rules.schema_problems(tables)
    if problems:
        return problems
    freshness.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    written = [_write(f"{chain}.py", render.render(chain, tables[chain])) for chain in tables]
    counts = ", ".join(f"{chain} {len(found)} tables" for chain, found in tables.items())
    state = "written" if any(written) else "unchanged"
    _say(f"rows: {counts} -> app/db/generated ({state})")
    return []


def run(*, check_only: bool) -> int:
    clock = _Clock()
    manifest = Manifest.read()
    schema_hash = freshness.schema_hash()
    sqlite_version = sqlite3.sqlite_version
    current = (
        manifest.schema_hash == schema_hash
        and manifest.sqlite_version == sqlite_version
        and manifest.generated == _generated_digests()
    )
    if check_only and not current:
        reason = freshness.problem() or (
            f"The generated database rows do not match the manifest: {freshness.REBUILD}"
        )
        return _fail([f"dbgen --check: {reason}"])
    databases = _Databases()
    try:
        if current:
            _say("schema unchanged: not migrated, rows not regenerated")
        else:
            problems = _generate(databases)
            if problems:
                return _fail(problems)
            _say(f"migrated and generated in {clock.seconds()} (SQLite {sqlite_version})")
        # The rows exist now, so the generated column tuples can be followed.
        finder = sqlcheck.Finder(sqlcheck.load_modules(freshness.BACKEND_ROOT))
        statements, problems, exceptions = finder.find()
        if problems:
            return _fail(problems)
        validated = set(manifest.statements) if current else set[str]()
        pending = [statement for statement in statements if statement.digest() not in validated]
        if check_only:
            if pending:
                return _fail(
                    [
                        f"dbgen --check: stale: {len(pending)} SQL statements are new or changed:"
                        f" {freshness.REBUILD}"
                    ]
                )
            _say(f"up to date ({len(statements)} SQL statements) in {clock.seconds()}")
            return 0
        failures: list[sqlcheck.Failure] = []
        variants = 0
        for statement in pending:
            variants += statement.size()
            failures += sqlcheck.check(statement, databases.get())
    finally:
        databases.close()
    if failures:
        lines = [
            f"{failure.location}: {failure.error}\n    {failure.text.strip()}"
            for failure in failures
        ]
        lines.append(f"dbgen: {len(failures)} SQL statement(s) failed; the build stops here")
        return _fail(lines)
    _say(
        f"SQL: {len(statements)} statements in app/ ({exceptions} on the exception list),"
        f" {len(pending)} compiled ({variants} variants), {len(statements) - len(pending)} cached"
    )
    manifest = Manifest(
        schema_hash=schema_hash,
        sqlite_version=sqlite_version,
        generated=_generated_digests(),
        statements=[statement.digest() for statement in statements],
    )
    state = "updated" if _write("manifest.json", manifest.text()) else "unchanged"
    _say(f"manifest {state}; done in {clock.seconds()}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.dbgen",
        description="Validate the migrations, generate typed rows and check every SQL statement.",
    )
    parser.add_argument(
        "--check", action="store_true", help="verify only; exit 1 when anything is stale"
    )
    arguments = parser.parse_args(argv)
    try:
        return run(check_only=bool(arguments.check))
    except BuildError as exc:
        return _fail([f"dbgen: {exc}"])
