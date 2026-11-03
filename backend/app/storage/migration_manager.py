"""Central schema Migration Manager.

Responsibilities:

* run the registry chain at startup and fail fast if it cannot reach the head revision;
* migrate every existing board eagerly, one at a time, before the application serves requests;
* snapshot each board with SQLite's online backup API before its schema changes;
* validate ``integrity_check`` and ``foreign_key_check`` after migrating;
* mark a board ``migration_failed`` on any error, keep the backup, and block writes;
* judge an imported board file before anything opens it (:meth:`check_imported`).

The orchestration is idempotent: a database already at head is skipped (and only reconciled in
the registry), and a failed migration can be re-run once the cause is fixed. Lazily migrating a
board later only requires calling :meth:`migrate_board` from the read path instead of startup.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Connection, Engine

from ..core.config import Settings
from ..core.errors import NotFound
from ..core.integrity import foreign_key_problem
from ..repositories.board_files import DatabaseProblem
from ..storage.board_db import BoardDatabaseManager
from ..storage.registry import Registry
from ..storage.schema import ensure_fts, runner
from ..storage.sqlite import connect_untrusted, create_sqlite_engine, snapshot_database

logger = logging.getLogger("tralala.migrations")

DETAIL_MAX_CHARS = 300


def _short(text: str) -> str:
    return text if len(text) <= DETAIL_MAX_CHARS else text[: DETAIL_MAX_CHARS - 3] + "..."


@dataclass(frozen=True)
class MigrationReport:
    chain: str
    board_id: str | None
    status: str
    from_revision: str | None
    to_revision: str | None
    backup: str | None
    duration_ms: int
    adopted: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MigrationManager:
    def __init__(
        self, settings: Settings, registry: Registry, boards: BoardDatabaseManager
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.boards = boards

    # --- public API -----------------------------------------------------------

    def migrate_registry(self) -> MigrationReport:
        """Bring ``registry.sqlite`` to head. Raises on failure: the app must not start."""
        started = time.perf_counter()
        engine = self.registry.engine
        head = runner.head_revision("registry")
        with engine.connect() as connection:
            current = runner.current_revision(connection)
            has_schema = runner.has_legacy_schema("registry", connection)
        backup: str | None = None
        if has_schema and current != head:
            backup = self._backup(
                self.settings.backups_dir / "registry", self.settings.registry_path
            )
        from_revision, to_revision, adopted, validation = self._upgrade_chain(
            "registry", engine, "registry failed post-migration validation"
        )
        report = MigrationReport(
            chain="registry",
            board_id=None,
            status="migrated" if from_revision != to_revision or adopted else "up_to_date",
            from_revision=from_revision,
            to_revision=to_revision,
            backup=backup,
            duration_ms=int((time.perf_counter() - started) * 1000),
            adopted=adopted,
        )
        self._log("migration_completed", report, validation=validation)
        return report

    def migrate_all_boards(self) -> list[MigrationReport]:
        """Eagerly migrate every registered board, sequentially. Never raises per board."""
        reports: list[MigrationReport] = []
        rows = self.registry.read("SELECT id FROM boards ORDER BY created_at, id")
        self._log("board_migration_batch_started", boards=len(rows))
        for row in rows:
            try:
                reports.append(self.migrate_board(row["id"]))
            except Exception as exc:  # one board must not stop the others
                logger.exception("unexpected error while migrating board %s", row["id"])
                reports.append(
                    MigrationReport(
                        chain="board",
                        board_id=row["id"],
                        status="failed",
                        from_revision=None,
                        to_revision=None,
                        backup=None,
                        duration_ms=0,
                        error=str(exc),
                    )
                )
        failed = sum(1 for report in reports if report.status == "failed")
        self._log(
            "board_migration_batch_completed",
            boards=len(reports),
            migrated=sum(1 for report in reports if report.status == "migrated"),
            up_to_date=sum(1 for report in reports if report.status == "up_to_date"),
            skipped=sum(1 for report in reports if report.status == "skipped"),
            failed=failed,
        )
        return reports

    def migrate_board(self, board_id: str) -> MigrationReport:
        """Migrate one board inside the shared per-board lock."""
        started = time.perf_counter()
        board_id = self.boards.validate_board_id(board_id)
        row = self.registry.board(board_id)
        if row is None:
            raise NotFound("Board not found")
        if not self.boards.exists(board_id):
            report = MigrationReport(
                chain="board",
                board_id=board_id,
                status="skipped",
                from_revision=None,
                to_revision=None,
                backup=None,
                duration_ms=0,
                error="board database file is missing",
            )
            self._log("migration_skipped", report)
            return report

        path = self.boards.path(board_id)
        previous_status = row["status"]
        backup: str | None = None

        with self.boards.locked(board_id):
            self.boards.close(board_id)
            engine = create_sqlite_engine(path)
            try:
                with engine.connect() as connection:
                    from_revision = runner.current_revision(connection)
                    has_schema = runner.has_legacy_schema("board", connection)
                head = runner.head_revision("board")
                needs_change = has_schema and from_revision != head
                if needs_change:
                    backup = self._backup(self.settings.backups_dir / board_id, path)
                from_revision, to_revision, adopted, validation = self._upgrade_chain(
                    "board", engine, "post-migration validation failed"
                )
                ensure_fts(engine)
                self._reconcile_registry(row, to_revision, previous_status)
                report = MigrationReport(
                    chain="board",
                    board_id=board_id,
                    status=(
                        "migrated" if from_revision != to_revision or adopted else "up_to_date"
                    ),
                    from_revision=from_revision,
                    to_revision=to_revision,
                    backup=backup,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    adopted=adopted,
                )
                self._log("migration_completed", report, validation=validation)
            except Exception as exc:  # noqa: BLE001 - a failure marks the board migration_failed
                self._mark_failed(board_id, exc, previous_status)
                report = MigrationReport(
                    chain="board",
                    board_id=board_id,
                    status="failed",
                    from_revision=None,
                    to_revision=None,
                    backup=backup,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    error=str(exc),
                )
                self._log("migration_failed", report)
                return report
            else:
                return report
            finally:
                engine.dispose()
                self.boards.close(board_id)

    def check_imported(self, board_id: str) -> DatabaseProblem | None:
        """Judge an imported board file before the application opens it (``BoardMigrator``).

        The file is opened read only as one of unknown origin (``connect_untrusted``), the integrity
        check runs first, and then come the two questions :meth:`migrate_board` asks of a board: are
        the board's tables there, and at which revision. A file that this manager would otherwise
        turn into a board (any SQLite file gets the whole schema created in it) or could not upgrade
        (a revision this release does not know) is refused instead.
        """
        path = self.boards.path(board_id)
        try:
            connection = connect_untrusted(path)
        except sqlite3.Error as exc:
            return DatabaseProblem(reason="not_a_database", detail=_short(str(exc)))
        try:
            return self._judge_imported(connection)
        except sqlite3.Error as exc:
            return DatabaseProblem(reason="not_a_database", detail=_short(str(exc)))
        finally:
            connection.close()

    @staticmethod
    def _judge_imported(connection: sqlite3.Connection) -> DatabaseProblem | None:
        findings = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        if findings != ["ok"]:
            return DatabaseProblem(
                reason="integrity_check_failed", detail=_short("; ".join(findings))
            )
        objects = {
            str(name): str(kind)
            for name, kind in connection.execute("SELECT name, type FROM sqlite_master")
        }
        missing = sorted(
            name for name in runner.LEGACY_TABLE_MARKERS["board"] if objects.get(name) != "table"
        )
        if missing:
            return DatabaseProblem(
                reason="not_a_board_database", detail=f"missing tables: {', '.join(missing)}"
            )
        version_table = objects.get("alembic_version")
        if version_table is None:
            # A board from before revision tracking: migrate_board adopts it at the baseline.
            return None
        if version_table != "table":
            return DatabaseProblem(
                reason="not_a_board_database", detail=f"alembic_version is a {version_table}"
            )
        versions = connection.execute("SELECT version_num FROM alembic_version")
        found = [str(row[0]) for row in versions]
        if len(found) != 1 or found[0] not in runner.revisions("board"):
            return DatabaseProblem(
                reason="unknown_schema_revision", detail=_short(", ".join(found) or "none")
            )
        return None

    def status(self) -> dict[str, Any]:
        return {
            "registry_head": runner.head_revision("registry"),
            "board_head": runner.head_revision("board"),
            "board_revisions": runner.revision_count("board"),
        }

    # --- internals ------------------------------------------------------------

    def _upgrade_chain(
        self, chain: str, engine: Engine, invalid: str
    ) -> tuple[str | None, str, bool, dict[str, Any]]:
        """Stamp a legacy database, upgrade it to head and validate it. Safe to repeat."""
        baseline = runner.CHAIN_BASELINES[chain]
        head = runner.head_revision(chain)
        adopted = False
        # One transaction: Alembic participates in it, so a failure, a failed validation included,
        # leaves the version, schema and data untouched and the next start can resume from the
        # same point.
        with runner.migration_transaction(engine) as connection:
            from_revision = runner.current_revision(connection)
            if from_revision is None and runner.has_legacy_schema(chain, connection):
                runner.stamp(chain, connection, baseline)
                from_revision = baseline
                adopted = True
                self._log(
                    "migration_adopted_legacy_schema",
                    MigrationReport(
                        chain=chain,
                        board_id=None,
                        status="migrated",
                        from_revision=None,
                        to_revision=baseline,
                        backup=None,
                        duration_ms=0,
                        adopted=True,
                    ),
                )
            if runner.current_revision(connection) != head:
                runner.upgrade(chain, connection, "head")
            to_revision = runner.current_revision(connection)
            # Before the COMMIT, so a database that fails is left as it was.
            validation = self._validate(connection)
            self._require_valid(validation, invalid)
        if to_revision != head:
            raise RuntimeError(f"{chain} schema did not reach head ({to_revision!r} != {head!r})")
        return from_revision, to_revision, adopted, validation

    def _reconcile_registry(self, row: dict[str, Any], revision: str, previous_status: str) -> None:
        updates: dict[str, Any] = {
            "schema_revision": revision,
            "schema_version": runner.revision_count("board"),
        }
        if previous_status == "migration_failed":
            updates["status"] = "archived" if row["archived_at"] else "active"
        if (
            updates.get("schema_revision") != row.get("schema_revision")
            or updates["schema_version"] != row.get("schema_version")
            or "status" in updates
        ):
            self.registry.update_board(row["id"], **updates)

    def _mark_failed(self, board_id: str, exc: Exception, previous_status: str) -> None:
        logger.exception("board migration failed: %s", board_id)
        self.registry.update_board(board_id, status="migration_failed")
        self._log(
            "migration_failed_state",
            board_id=board_id,
            previous_status=previous_status,
            error=type(exc).__name__,
        )

    def _backup(self, directory: Path, source: Path) -> str:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"backup-{stamp}-pre-migration.sqlite"
        counter = 2
        while (directory / name).exists():
            name = f"backup-{stamp}-pre-migration-{counter}.sqlite"
            counter += 1
        target = directory / name
        snapshot_database(source, target)
        check = self._check_file(target)
        if not check["ok"]:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"pre-migration backup failed integrity check: {check}")
        return name

    @staticmethod
    def _check_file(path: Path) -> dict[str, Any]:
        try:
            connection = sqlite3.connect(path)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return {"integrity": f"unreadable: {exc}", "ok": False}
        return {"integrity": integrity, "ok": integrity == "ok"}

    @staticmethod
    def _require_valid(validation: dict[str, Any], message: str) -> None:
        if not validation["ok"]:
            raise RuntimeError(f"{message}: {validation}")

    @staticmethod
    def _validate(connection: Connection) -> dict[str, Any]:
        # integrity_check answers one row "ok", or one row per problem it found.
        findings = [str(row[0]) for row in connection.exec_driver_sql("PRAGMA integrity_check")]
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        validation: dict[str, Any] = {
            "integrity": "; ".join(findings),
            "foreign_key_violations": len(violations),
            "ok": findings == ["ok"] and not violations,
        }
        problem = foreign_key_problem(violations)
        if problem is not None:
            validation["foreign_key_detail"] = problem
        return validation

    def _log(self, event: str, report: MigrationReport | None = None, **fields: Any) -> None:
        payload: dict[str, Any] = dict(fields)
        if report is not None:
            payload.update(
                {key: value for key, value in report.to_dict().items() if value is not None}
            )
        logger.info(event, extra=payload)
