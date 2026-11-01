# 0003 — Gap-based integer ordering with lazy normalization

- Status: accepted
- Date: 2026-10-30

## Context

Lists and cards must support frequent drag-and-drop reordering, be stable after reload, and stay
queryable with `ORDER BY position`. Naive renumbering rewrites every row on each move; fractional
indices need floating-point types and eventually exhaust precision.

## Decision

- `position` is an integer, initially spaced by `POSITION_GAP = 1024`.
- An insert or move at index *i* computes the midpoint between neighbours.
- When two neighbours are adjacent (`difference <= 1`), the affected scope (one list's cards, or
  all active lists) is normalized to `1024, 2048, …` and the midpoint is recomputed.
- Positions of archived rows are ignored and re-appended on restore.

## Consequences

- Moves are a single-row `UPDATE` in the common case.
- Normalization cost is bounded to one list (or the list collection) and happens rarely.
- Ties are broken by id for deterministic reads.
- The strategy is implemented in `backend/app/services/common.py` and covered by ordering tests.
