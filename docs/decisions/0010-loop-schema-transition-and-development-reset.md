# 0010 — Loop schema transition and the development reset

- Status: accepted by the owner (2026-11-01). The revisit before the first public release is done:
  the reset is kept as the only path, and the consequence is stated for users in
  [public_docs/Release_notes.md](../../public_docs/Release_notes.md) instead of an import of the old
  archive format being written.
- Date: 2026-11-01

## Context

Until this change a board owned its Kanban directly: `lists.board_id` and `cards.list_id`. The Loop
refactor makes a Loop the owner of columns and Tickets, so every list and card needs a `loop_id`
that cannot be derived from the old shape without choosing a Loop name, key prefix and column set
for each legacy board. Revision `0008_loops` therefore recreates `lists` and `cards` instead of
adding nullable columns and leaving two shapes behind.

At the time of the decision the product is in its earliest phase: it has never been published,
advertised or handed to a customer, no installation holds production data, and the only databases
that exist are development leftovers. The owner confirmed that state on 2026-11-01 and asked for the
refactor to proceed without carrying old data forward.

## Decision

1. **A populated pre-Loop board is refused, not converted.** `0008_loops` raises when a board
   database already contains lists or cards. Startup marks such a board `migration_failed`, the
   other boards keep serving, and nothing is rewritten.
2. **The documented remedy is the development reset.** `python -m app.dev_reset --confirm` erases
   boards, backups and the registry after naming the data directory, and keeps the session secret.
   It is never run automatically.
3. **Old export archives are rejected.** `POST /boards/import` accepts only
   `format_version == 2`, so an archive written by the previous release cannot be imported as a
   back door into the new schema.
4. **The board page tells the operator what happened.** A `migration_failed` board shows the state,
   an explanation, a retry button (`POST /boards/{id}/migrate`) and a link to the export archive,
   so the first thing an operator sees is not a silent 409.

## Consequences

- Development and demo data written before this revision is erased by design. That is acceptable
  only while nobody else holds data.
- A board stuck at `migration_failed` cannot be repaired by retrying: the guard rejects the same
  database every time. The operator's only paths are the reset (development) or a fresh board.
- The failure reason lives in the server log (`board migration failed: <id>`) rather than in a
  response, so an operator needs access to the process output.

## Requirement before the first public release

The refusal above may not ship as the only path. Before the first release that anyone can install
over existing data, either

- accept `format_version == 1` in the importer and convert an archived board into one Loop with the
  old Lists and cards (with a test that the imported board arrives complete), or
- keep the refusal and state in the release notes that data written by earlier revisions is not
  supported, together with the exact reset command.

Whichever is chosen must be recorded here as an update, and the conversion option needs tests for a
fresh install, an upgrade and a failed conversion.

## Alternatives considered

- **Convert in place during migration.** Rejected for now: it needs a Loop identity for every
  legacy board plus a per-board naming decision that a migration cannot make, and a half-written
  conversion is worse than a refusal.
- **Nullable `loop_id` with a compatibility layer.** Rejected: it keeps two shapes alive and every
  service would need a branch forever.
- **Silently create a Loop per board on upgrade.** Rejected: it invents product data (name, key
  prefix) during an operation the user did not request, and it cannot be undone.
