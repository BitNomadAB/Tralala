# 0001 — One SQLite database per board, registry as authority

- Status: accepted
- Date: 2026-10-30

## Context

The product requires strict board isolation, portable single-board export/backup, and a host that
can hold at least 100 boards. A single shared database would simplify joins but weaken isolation
and make per-board backup/restore a slicing exercise.

## Decision

Each board owns `data/boards/{uuid}/board.sqlite`. A small `registry.sqlite` stores board metadata,
actors and credentials, and is consulted before a board database is opened. Board ids are UUIDs
resolved through `BoardDatabaseManager`; no path is ever built from user text.

## Consequences

- Board backup, restore, export and physical deletion are file-scoped and simple.
- Cross-board operations (duplicate, transfer, global search) need explicit, recoverable workflows;
  they never span two databases in one transaction.
- Global search iterates boards individually, as specified.
- Connection handling must be bounded: engines use `NullPool`, idle engines are disposed and the
  cache is capped.

See `docs/decisions/0002` for interrupted-operation recovery.
