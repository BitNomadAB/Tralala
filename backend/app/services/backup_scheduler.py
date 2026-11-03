"""Periodic snapshots and retention, so a self-hosted install is not one disk away from loss.

An administrator can always take a backup by hand, and the migration manager takes one before it
touches a schema. What was missing is the boring case: nobody remembers for a month. This thread
checks every board that is due, snapshots it, and prunes the oldest snapshots beyond the
configured keep count.

It is deliberately in-process and daemon-threaded, like the run and mention workers: the product is
one backend per data directory, and a second process taking snapshots would fight the writer lock.
"""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Protocol, TypedDict

from ..core.context import SCOPES, ActorContext
from ..repositories.registry import RegistryUnitOfWork
from .backups import BackupCreated

logger = logging.getLogger("tralala.backups")

# A restart should not wait a whole interval to notice that the last snapshot is old.
FIRST_CHECK_SECONDS = 30.0
# Checking more often than hourly buys nothing; the interval itself is measured in hours.
MAX_CHECK_SECONDS = 3600.0


def system_actor() -> ActorContext:
    """The identity an automatic snapshot runs as; it is neither a person nor an agent key."""
    return ActorContext(
        actor_id="system:backup",
        actor_type="service",
        actor_name="automatic backup",
        scopes=frozenset(SCOPES),
    )


class Backups(Protocol):
    """What the scheduler asks of ``BackupService``."""

    def newest_age_hours(self, board_id: str) -> float | None: ...

    def create(self, actor: ActorContext, board_id: str) -> BackupCreated: ...

    def prune(self, board_id: str, keep: int) -> list[str]: ...


class CreatedEntry(TypedDict):
    board_id: str
    name: str


class PrunedEntry(TypedDict):
    board_id: str
    names: list[str]


class FailedEntry(TypedDict):
    board_id: str
    error: str


class CycleReport(TypedDict):
    created: list[CreatedEntry]
    pruned: list[PrunedEntry]
    failed: list[FailedEntry]


class BackupScheduler:
    def __init__(
        self, backups: Backups, *, store: RegistryUnitOfWork, interval_hours: int, keep: int
    ) -> None:
        self.backups = backups
        self.store = store
        self.interval_hours = int(interval_hours)
        self.keep = int(keep)
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def enabled(self) -> bool:
        return self.interval_hours > 0

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = Thread(target=self._loop, name="tralala-backup", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            self._thread = None

    def _loop(self) -> None:
        delay = min(FIRST_CHECK_SECONDS, self.interval_hours * 3600.0)
        while True:
            if self._stop.wait(delay):
                return
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - a failed cycle must not kill the thread
                logger.error("backup_cycle_failed", extra={"error_type": type(exc).__name__})
            delay = min(self.interval_hours * 3600.0, MAX_CHECK_SECONDS)

    def run_once(self) -> CycleReport:
        """Snapshot every board that is due, then prune; returns a small report."""
        report: CycleReport = {"created": [], "pruned": [], "failed": []}
        if not self.enabled:
            return report
        actor = system_actor()
        with self.store.reader() as repos:
            active = sorted(repos.boards.with_status("active"), key=lambda row: row.name)
        for row in active:
            board_id = row.id
            try:
                age = self.backups.newest_age_hours(board_id)
                if age is not None and age < self.interval_hours:
                    continue
                created = self.backups.create(actor, board_id)
                removed = self.backups.prune(board_id, self.keep)
                report["created"].append({"board_id": board_id, "name": created["name"]})
                report["pruned"].append({"board_id": board_id, "names": removed})
                # "name" is a LogRecord attribute, so the backup's file name is "backup_name".
                logger.info(
                    "backup_created",
                    extra={
                        "board_id": board_id,
                        "backup_name": created["name"],
                        "size_bytes": created["size_bytes"],
                        "integrity": created["verification"]["integrity"],
                        "pruned": len(removed),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - one broken board must not stop the rest
                report["failed"].append({"board_id": board_id, "error": type(exc).__name__})
                logger.error(
                    "backup_failed",
                    extra={"board_id": board_id, "error_type": type(exc).__name__},
                )
        return report


__all__ = ["BackupScheduler", "system_actor"]
