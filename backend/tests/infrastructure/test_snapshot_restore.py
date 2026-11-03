"""A backup is restored only when SQLite finds the snapshot sound; the copy leaves no -wal behind.

The verdict is pure and unit-tested (``tests/unit/test_integrity.py``). What a fake cannot show is
what SQLite answers for a real damaged file, a real broken key and a file that is not a database,
read through the read-only connection that ``check_snapshot`` and ``restore_snapshot`` share, which
writes nothing beside the snapshot; and that the copy into a board file another connection keeps
open lands in the database file with its ``-wal`` emptied (``AFTER_RESTORE_PRAGMAS``).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from app.core.integrity import SnapshotProblem
from app.storage.board_db import BoardDatabaseManager
from app.storage.sqlite import check_snapshot, restore_snapshot


def _write(path: Path, *statements: str) -> None:
    connection = sqlite3.connect(path)
    try:
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _root_page(path: Path, table: str) -> tuple[int, int]:
    """Where a table's b-tree starts in the file: (byte offset, page size)."""
    connection = sqlite3.connect(path)
    try:
        root = connection.execute(
            "SELECT rootpage FROM sqlite_master WHERE name = ?", (table,)
        ).fetchone()[0]
        size = connection.execute("PRAGMA page_size").fetchone()[0]
    finally:
        connection.close()
    return (root - 1) * size, size


def _index_out_of_step(path: Path) -> None:
    """One table row changed behind its index's back: integrity_check reports it as a row."""
    _write(
        path,
        "CREATE TABLE probe_damage (id INTEGER PRIMARY KEY, v TEXT)",
        "INSERT INTO probe_damage (id, v) WITH RECURSIVE n(i) AS"
        " (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 50)"
        " SELECT i, printf('value-%04d', i) FROM n",
        "CREATE INDEX probe_damage_v ON probe_damage (v)",
    )
    # Fifty short rows fit in the table's root page, so the value is changed there and only there.
    offset, size = _root_page(path, "probe_damage")
    data = bytearray(path.read_bytes())
    at = data.find(b"value-0042", offset, offset + size)
    assert at >= 0
    data[at : at + len(b"value-0042")] = b"VALUE-0042"
    path.write_bytes(bytes(data))


def _broken_page(path: Path) -> None:
    """A b-tree page that is no page at all: SQLite raises SQLITE_CORRUPT while checking."""
    _write(
        path,
        "CREATE TABLE probe_damage (id INTEGER PRIMARY KEY, v TEXT)",
        "INSERT INTO probe_damage (id, v) WITH RECURSIVE n(i) AS"
        " (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 100)"
        " SELECT i, printf('%0300d', i) FROM n",
    )
    offset, _size = _root_page(path, "probe_damage")
    data = bytearray(path.read_bytes())
    data[offset] = 0  # the page-type byte
    path.write_bytes(bytes(data))


def _orphan(path: Path) -> None:
    _write(
        path,
        "PRAGMA foreign_keys=OFF",
        "CREATE TABLE probe_parent (id INTEGER PRIMARY KEY)",
        "CREATE TABLE probe_child (id INTEGER PRIMARY KEY,"
        " parent_id INTEGER REFERENCES probe_parent (id))",
        "INSERT INTO probe_child (id, parent_id) VALUES (7, 42)",
    )


def test_only_a_sound_snapshot_is_restored_and_its_copy_empties_the_wal(
    boards: BoardDatabaseManager, board_id: str, tmp_path: Path
) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    sound = snapshots / "sound.sqlite"
    boards.snapshot(board_id, sound)
    for name, damage in (
        ("index.sqlite", _index_out_of_step),
        ("page.sqlite", _broken_page),
        ("orphan.sqlite", _orphan),
    ):
        shutil.copyfile(sound, snapshots / name)
        damage(snapshots / name)
    (snapshots / "garbage.sqlite").write_bytes(b"not a database at all " * 300)
    written = sorted(path.name for path in snapshots.iterdir())

    verdicts = {name: check_snapshot(snapshots / name) for name in written}

    page = verdicts.pop("page.sqlite")
    assert page is not None
    assert page.reason == "integrity_check_failed"
    assert page.detail.startswith("integrity_check: ")
    assert verdicts == {
        "garbage.sqlite": SnapshotProblem(reason="not_a_database", detail="file is not a database"),
        "index.sqlite": SnapshotProblem(
            reason="integrity_check_failed",
            detail="integrity_check: 1 problem(s): row 42 missing from index probe_damage_v",
        ),
        "orphan.sqlite": SnapshotProblem(
            reason="foreign_key_check_failed",
            detail=(
                "foreign_key_check: 1 row(s) name a row that does not exist:"
                " probe_child rowid 7 -> probe_parent (key 0)"
            ),
        ),
        "sound.sqlite": None,
    }
    # Read only and immutable: no -wal, -shm or journal beside any of them.
    assert sorted(path.name for path in snapshots.iterdir()) == written

    live = tmp_path / "board" / "board.sqlite"
    live.parent.mkdir()
    shutil.copyfile(sound, live)
    wal = live.with_name("board.sqlite-wal")
    holder = sqlite3.connect(live)
    try:
        holder.execute("SELECT count(*) FROM sqlite_master").fetchone()
        _write(live, "CREATE TABLE probe_newer (v TEXT)")
        # The control: while another connection has the file open, a commit stays in the -wal.
        assert wal.stat().st_size > 0

        restore_snapshot(sound, live)

        assert wal.stat().st_size == 0
        newer = "SELECT count(*) FROM sqlite_master WHERE name = 'probe_newer'"
        assert holder.execute(newer).fetchone() == (0,)
    finally:
        holder.close()
