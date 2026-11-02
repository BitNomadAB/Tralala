# 0019 — A board's files travel with its database

- **Status:** accepted
- **Date:** 2026-11-02
- **Context:** Uploaded attachments (`services/attachments.py`), backups (`services/backups.py`),
  board export and import (`services/boards.py`)

## Problem

A board is two things on disk: `data/boards/{id}/board.sqlite` and
`data/boards/{id}/attachments/*`. Every snapshot and every export took only the database. Restoring a
backup therefore produced a board whose attachment rows pointed at files that were not there, and a
board exported from one installation and imported into another lost its files entirely. Both
operations looked complete and were not.

## Decision

1. **A backup is a pair.** `create` writes the snapshot plus, when the board has files, one sidecar
   `backup-<timestamp>-attachments.zip` next to it. `restore` puts the files back inside the same
   board lock that replaces the database, and reports `attachments.restored`. A snapshot without a
   sidecar restores the database and leaves existing files alone — it never deletes evidence it does
   not cover.
2. **Retention treats them as one unit.** `prune` removes a sidecar together with the snapshot it
   belongs to, and never touches files that do not match `backup-<timestamp>.sqlite`.
3. **`list` says whether a snapshot carries files** (`has_attachments`, `attachments_size_bytes`), so
   an operator can see it before restoring.
4. **Export and import carry the files too.** The archive gains `attachments/<stored_filename>`
   entries and the manifest records `attachments: {files, bytes}`. Import validates every entry name
   (`Path(entry).name`, no duplicates), refuses an archive whose declared size exceeds
   `TRALALA_BOARD_ATTACHMENT_MAX_BYTES` or that carries more than 1000 files, and writes the files
   into the new board's directory before the database is migrated into place.
5. **One path helper.** `BoardDatabaseManager.attachments_dir(board_id)` is the only definition of
   where a board's files live; the attachment service and both snapshot paths use it.

## Consequences

- "Restore last night's backup" now restores what the user saw: rows and files.
- A backup can be up to twice the size of the database plus the files; retention counts snapshots, so
  the disk budget must include the sidecars. The alternative — an unrestorable backup — is worse.
- Moving a board between installations works for the first time, which is what
  `POST /boards/import` promised.
- The sidecar is a second artefact per snapshot. A single-file format (one zip containing both) would
  be tidier but changes the restore API and the UI list; that can come later without touching the
  services.

## Alternatives considered

- **Store attachments inside the board database as blobs.** One artefact and atomic snapshots, but
  every backup then grows by the total upload size, and SQLite is a poor place for 200 MB of PDFs.
- **Back up the whole board directory with a tar.** Equivalent outcome, new format, and the existing
  restore/verify path (integrity check on the SQLite file) would have to be rebuilt around it.
- **Leave export/import as database-only and document it.** Cheapest, but an import that silently
  loses every file is a data-loss feature, not a limitation.
