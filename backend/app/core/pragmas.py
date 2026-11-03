"""The PRAGMAs the storage layer sends to a database, by the moment it sends them.

Each list follows SQLite's documentation for that moment (https://www.sqlite.org/pragma.html,
https://www.sqlite.org/wal.html). They are constants so the unit suite holds them to it without
opening a database; ``app/storage/sqlite.py`` runs them.

* **At connect**, on every connection of ``create_sqlite_engine``: the settings that last only as
  long as the connection, ``journal_size_limit`` among them (it is not stored in the file), and WAL
  mode, which the file keeps but which a new file needs once.
* **When a board goes out of use** (the idle sweep, the eviction of the oldest cached board and
  shutdown): ``optimize``, then a ``TRUNCATE`` checkpoint, on a connection of their own.
* **After a restore** wrote a snapshot into a board's live file: a ``TRUNCATE`` checkpoint.
* **Before a backup: nothing.** The online backup API copies every committed page through the
  source's own pager, the pages still in the ``-wal`` file included, and Python's
  ``Connection.backup`` copies them all in one step, so in one read transaction
  (https://www.sqlite.org/backup.html). A checkpoint would not change the copy; a RESTART or
  TRUNCATE one would only make writers wait.

Every board connection is short-lived (``NullPool``), and when the last connection to a database
closes, SQLite checkpoints it and deletes the ``-wal`` and ``-shm`` files itself (wal.html, "The WAL
File"). The checkpoints here matter when another connection still has the file open at that moment:
then the ``-wal`` file is emptied now instead of keeping its size until that connection closes.
"""

from __future__ import annotations

from typing import Final

BUSY_TIMEOUT_MS: Final = 5000
"""How long a connection waits for a lock another connection holds (``busy_timeout``)."""

JOURNAL_SIZE_LIMIT_BYTES: Final = 67_108_864
"""64 MiB: the most a ``-wal`` file keeps on disk once it is reset.

SQLite reuses a WAL file after a checkpoint instead of shrinking it, unless this limit is set
(pragma.html#pragma_journal_size_limit). In normal use the WAL is reset at about 1000 pages,
4 MiB (wal.html, "Automatic Checkpoint"), far below the limit, so no ordinary commit pays for a
truncation; only an outsized transaction (a migration that rebuilds a table, a restore) grows it
further, and the limit caps what stays behind while another connection keeps the file open.
"""

CONNECT_PRAGMAS: Final = (
    "PRAGMA foreign_keys=ON",
    "PRAGMA journal_mode=WAL",
    f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
    "PRAGMA synchronous=NORMAL",
    f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT_BYTES}",
)
"""Sent by every connection of ``create_sqlite_engine`` when it opens, in this order."""

OPTIMIZE: Final = "PRAGMA optimize=0x1fffe"
"""``optimize`` with the documented default mask ``0xfffe`` plus ``0x10000``.

``0xfffe`` is everything but debug mode, including ``0x10``, the temporary analysis limit that keeps
an ANALYZE short. ``0x10000`` makes it look at every table: without it only tables the connection
itself has queried are candidates, and the connection that runs this has queried none. That is the
reason SQLite's pattern for long-lived connections opens them with ``0x10002``.

Why not before every connection closes, SQLite's pattern for short-lived connections: it assumes the
pragma is nearly free, and it is not before SQLite 3.46.0. There, a connection that queried an empty
table with an index runs ANALYZE on it again at every close (ANALYZE stores no statistics for an
empty table), taking the write lock each time, and with ``NullPool`` every request closes several
connections. A board's cached engine is the long-lived handle here, so the long-lived pattern
applies: once when the board goes out of use. Before 3.46.0 the ``0x10000`` bit does not exist and
the pragma finds nothing to do on a fresh connection, which is harmless.
"""

CHECKPOINT: Final = "PRAGMA wal_checkpoint(TRUNCATE)"
"""Move every frame of the ``-wal`` file into the database and truncate the ``-wal`` to zero bytes.

TRUNCATE rather than PASSIVE, because only RESTART and TRUNCATE run to completion and reset the WAL
(wal.html, "Checkpoint starvation"), and TRUNCATE also gives the disk space back. When a reader
still uses the WAL once the connection's busy timeout has passed, it answers ``1`` in its first
column instead of finishing; nothing is lost, the next checkpoint finishes the work.
"""

CLOSE_PRAGMAS: Final = (OPTIMIZE, CHECKPOINT)
"""Sent when a board goes out of use. ``optimize`` first: its ANALYZE writes into the WAL, which the
checkpoint then moves into the database file."""

AFTER_RESTORE_PRAGMAS: Final = (CHECKPOINT,)
"""Sent on the connection that restored a snapshot into a board's live file.

The board's file is in WAL mode, so the backup API writes the whole snapshot into its ``-wal`` file
in one transaction; the checkpoint moves it into the database file at once.
"""

INTEGRITY_CHECK: Final = "PRAGMA integrity_check"
"""Asked of a snapshot before it is restored; it answers one ``ok`` row or one row per problem."""

FOREIGN_KEY_CHECK: Final = "PRAGMA foreign_key_check"
"""Asked of a snapshot that passed ``INTEGRITY_CHECK``; it answers one row per row whose key names a
missing row, whether or not the connection enforces foreign keys."""
