# 0002 — Explicit recovery states instead of distributed transactions

- Status: accepted
- Date: 2026-10-30

## Context

Registry metadata and board files cannot be updated atomically. A crash between "insert registry
row" and "initialize board database" must not leave a board that appears usable but has no data
file, and must never half-delete a user's board.

## Decision

1. **Board creation** inserts the registry row with status `maintenance`, initializes the database
   and default lists, then flips the row to `active`. Any exception sets `error`.
2. **Startup recovery** (`BoardService.recover`) converts leftover `maintenance` rows: `active`
   when the database exists, `error` otherwise.
3. **Duplication/import** follow the same `maintenance → active|error` pattern.
4. **Cross-board transfer** copies into the target board first and deletes the source second; the
   response includes `finalized` and a warning if the source could not be removed.
5. **Deletion** requires an archived board plus an exact name confirmation, then removes the
   database, backups and registry row.

## Consequences

- Every intermediate state is observable in the dashboard as `maintenance`/`error`.
- A failed finalize leaves a recoverable duplicate rather than data loss.
- No operation claims atomicity it cannot provide; `docs/api.md` documents the semantics.
