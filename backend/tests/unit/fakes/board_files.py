"""Several board databases in memory, each with a real directory for its files.

``BoardService`` creates, copies, exports, imports and deletes whole boards, so its fake holds one
``BoardState`` per board and a directory per board under a temporary root. A board's database file
holds a short marker instead of SQLite pages: ``snapshot`` writes a marker and keeps a copy of the
rows under it, and opening a file whose board has no rows yet takes the rows of its marker. So a
duplicated, exported or imported board carries its rows the way the real file copy does, and no
test opens SQLite.
"""

from __future__ import annotations

import shutil
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import NotFound, ServiceUnavailable
from app.core.identifiers import canonical_board_id
from app.db.generated.board import BoardMetadataRow
from app.repositories.board import BoardUnitOfWork
from app.repositories.board_files import BoardFiles, BoardMigrator, MigrationOutcome
from tests.unit.fakes.board import CREATED, BoardState, FakeBoardRepositories


@dataclass(frozen=True, slots=True)
class FakeMigration:
    status: str


@dataclass(slots=True)
class FakeBoardDatabases:
    """The board unit of work, the board files and the migrator, over ``root``."""

    root: Path
    schema_version: int = 10
    states: dict[str, BoardState] = field(default_factory=dict[str, BoardState])
    # A database file's marker -> the rows a copy of it carries.
    images: dict[bytes, BoardState] = field(default_factory=dict[bytes, BoardState])
    # Boards whose schema is being repaired: opening one answers 503, as the manager does.
    unavailable: set[str] = field(default_factory=set[str])
    # Boards whose files the host holds open: deleting them raises, as remove_tree would.
    busy: set[str] = field(default_factory=set[str])
    # What migrating a board answers; "up_to_date" when absent.
    migration_status: dict[str, str] = field(default_factory=dict[str, str])
    migrated: list[str] = field(default_factory=list[str])
    locked_boards: list[str] = field(default_factory=list[str])
    commits: int = 0
    rollbacks: int = 0

    # --- the files ---------------------------------------------------------------------------

    def path(self, board_id: str) -> Path:
        return self.root / canonical_board_id(board_id) / "board.sqlite"

    def attachments_dir(self, board_id: str) -> Path:
        return self.root / canonical_board_id(board_id) / "attachments"

    def create_database(self, board_id: str, description: str) -> None:
        path = self.path(board_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"created:{board_id}".encode())
        self.states[canonical_board_id(board_id)] = BoardState(
            metadata=BoardMetadataRow(
                id=board_id,
                description=description,
                created_at=CREATED,
                updated_at=CREATED,
                schema_version=self.schema_version,
            )
        )

    def snapshot(self, board_id: str, target: Path) -> None:
        state = self._open(board_id)
        marker = f"image:{len(self.images) + 1}".encode()
        self.images[marker] = state.snapshot()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(marker)

    @contextmanager
    def locked(self, board_id: str) -> Generator[None]:
        self.locked_boards.append(board_id)
        yield

    def delete_database(self, board_id: str) -> None:
        if board_id in self.busy:
            raise PermissionError(13, "The process cannot access the file")
        self.states.pop(canonical_board_id(board_id), None)
        shutil.rmtree(self.path(board_id).parent, ignore_errors=True)

    # --- the unit of work --------------------------------------------------------------------

    def exists(self, board_id: str) -> bool:
        try:
            return self.path(board_id).exists()
        except NotFound:
            return False

    def _open(self, board_id: str) -> BoardState:
        path = self.path(board_id)
        if not path.exists():
            raise NotFound("Board database not found")
        if board_id in self.unavailable:
            raise ServiceUnavailable(
                "Board schema is not at the current revision", code="board_schema_outdated"
            )
        key = canonical_board_id(board_id)
        state = self.states.get(key)
        if state is None:
            image = self.images.get(path.read_bytes())
            if image is None:
                raise ServiceUnavailable("Board database is not one this fake wrote")
            state = image.snapshot()
            self.states[key] = state
        return state

    @contextmanager
    def reader(self, board_id: str) -> Generator[FakeBoardRepositories]:
        state = self._open(board_id)
        snapshot = state.snapshot()
        try:
            yield FakeBoardRepositories(state)
        finally:
            state.restore(snapshot)

    @contextmanager
    def writer(self, board_id: str) -> Generator[FakeBoardRepositories]:
        state = self._open(board_id)
        snapshot = state.snapshot()
        try:
            yield FakeBoardRepositories(state)
        except BaseException:
            state.restore(snapshot)
            self.rollbacks += 1
            raise
        self.commits += 1

    # --- the migrator ------------------------------------------------------------------------

    def migrate_board(self, board_id: str) -> MigrationOutcome:
        self.migrated.append(board_id)
        return FakeMigration(self.migration_status.get(board_id, "up_to_date"))


def as_unit_of_work(databases: FakeBoardDatabases) -> BoardUnitOfWork:
    """The fake as the Protocols a service takes; pyright proves each contract."""
    return databases


def as_files(databases: FakeBoardDatabases) -> BoardFiles:
    return databases


def as_migrator(databases: FakeBoardDatabases) -> BoardMigrator:
    return databases
