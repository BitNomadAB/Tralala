# 0023 — Board counters are cached in the registry

- Status: accepted by the owner (2026-11-02)
- Date: 2026-11-02

## Context

The dashboard shows how many Loops, lists and Tickets each board holds. Those numbers live inside
`data/boards/{uuid}/board.sqlite`, because the board database is the only place board content
exists. A list of 100 boards therefore opened 100 SQLite files to answer one request.

Measured on this machine with 100 boards, `GET /boards?limit=100`: 1337 ms with no cache, 15 ms once
the counters were known, 13 ms with `with_counts=false`.

Rule 3 says the registry is authoritative for board *metadata*, and rule 2 says a board's data lives
only in its board database. Those two rules are what make the naive list expensive: the numbers
cannot be joined in one statement.

## Decision

The registry remembers the **last measurement** of a board's counters in `board_stats`, and the
board stays the source of truth.

1. A row is written only after measuring that board's own database with one statement.
2. The row is **dropped whenever the board is written to**. `BoardDatabaseManager` has one write
   choke point, so the cache attaches itself there (`on_write`) instead of asking every service to
   remember. Closing and deleting a board also drop the row, because restoring or replacing a file
   reports no transaction.
3. `TRALALA_BOARD_COUNTS_CACHE_SECONDS` (default 60) re-measures a row that nobody has written to.
   It exists only for a board file changed behind the app's back; `0` disables the cache.
4. A board whose schema is being repaired measures as zeros rather than vanishing from the list.
5. `GET /boards?with_counts=false` reports zeros and opens no board at all.
6. `board_stats` cascades from `boards`, so a deleted board takes its counters with it.

## Consequences

- A dashboard read costs one registry query instead of one file open per row.
- After a write, the next list re-measures that board (one open), so the numbers a person sees after
  their own change are always theirs.
- Worst case staleness is the time limit, and only for a board changed outside the app.
- One extra registry statement per write transaction, whether or not the counters were cached.
- A known cost: a board migration that changes Loop/list/Ticket counts would need to clear the cache.
  Today no revision does; the time limit bounds it if one ever does.
