# Database design

Two database kinds, both SQLite with `PRAGMA foreign_keys=ON`, WAL journaling, a 5 s busy timeout
and `synchronous=NORMAL`. Each database tracks its own schema in Alembic's `alembic_version` table;
the registry and board schemas are separate migration chains managed by the Migration Manager.

## registry.sqlite

| Table | Purpose |
| --- | --- |
| `boards` | Global board metadata: id, name, description, status (`active`, `archived`, `maintenance`, `error`, `migration_failed`), timestamps, `archived_at`, `schema_version`, `schema_revision` |
| `board_stats` | Last measured Loop, list and Ticket counters per board, with `measured_at`. A cache of numbers that live in the board database, not their source of truth: a row is dropped whenever the board is written to and re-measured after `TRALALA_BOARD_COUNTS_CACHE_SECONDS` |
| `actors` | Human, agent and service identities (`type`, `name`, `created_at`, `disabled_at`) |
| `user_credentials` | Password hashes (scrypt), role (`admin`, `member`) and the per-account appearance (`theme_mode`, `theme_kit`) |
| `sessions` | Server-side sessions: hash of the session id, actor, expiry, last seen and revocation |
| `api_credentials` | Hashed agent tokens with scopes, expiry, last use and revocation |
| `idempotency_records` | Replay protection for board-level creation |
| `board_templates` | Reusable board templates: id, name (unique, case-insensitive), description, `lists_json`, `labels_json`, timestamps |
| `role_templates` | Central AI role definitions: name (unique), description, `system_prompt`, `default_system_prompt` (factory copy), `built_in`, `builtin_key`, timestamps |
| `agents` | AI agent identities: name (unique), role reference, optional prompt override, connection type/URL/model, encrypted API key + hint, sampling limits, enabled flag, last test result |

Templates are global because they are chosen before a board (and therefore a board database)
exists. A template stores column names in order plus optional `{name, color}` labels. Creating a
board with `template_id` stores those column names as the board's Loop defaults
(`board_loop_defaults`) and writes the labels into the board database; it never creates ownerless
columns. Creating a Loop copies the defaults into Loop-owned columns, and template edits affect
future Loops only.

Indexes: `boards(status)`, `api_credentials(actor_id)`.

`board_stats` rows cascade from `boards`, so deleting a board removes its counters.

## boards/{uuid}/board.sqlite

| Table | Columns |
| --- | --- |
| `board_metadata` | id, description, created_at, updated_at, schema_version |
| `lists` | id, name, position, created_at, updated_at, archived_at |
| `cards` | id, list_id → lists, title, description, position, priority, due_at, completed_at, created_at, updated_at, archived_at, version, assignee_actor_id, assignee_type, assignee_name, assigned_at, assigned_by_actor_id |
| `attachments` | id, card_id → cards, discussion_id, message_id, original_filename, stored_filename (uuid), content_type, size_bytes, sha256, uploaded_by_actor_id, created_at, deleted_at |
| `labels` | id, name (unique), color |
| `card_labels` | card_id → cards, label_id → labels (PK pair) |
| `checklists` | id, card_id → cards, title, position |
| `checklist_items` | id, checklist_id → checklists, text, completed, position |
| `comments` | id, card_id → cards, actor_id, content, created_at, updated_at |
| `comment_mention_jobs` | id, card_id → cards, comment_id → comments, agent_id, agent_name, status (`queued`, `running`, `completed`, `failed`), attempts, error, response_comment_id → comments, role_snapshot_json, tokens_used, requested_by_*, created_at, started_at, finished_at |
| `card_events` | seq (autoincrement), id, card_id → cards, type, payload_json, actor_*, created_at |
| `activity_log` | id, actor_id, actor_type, action, entity_type, entity_id, request_id, timestamp, changes_json |
| `discussion_threads` | id, card_id → cards, title, goal, mode, status, run_state, round_count, tokens_used, elapsed_ms, created_by_*, max_rounds, origin_comment_id, escalation_depth, created_at, updated_at, last_activity_at |
| `discussion_participants` | id, discussion_id → discussion_threads, participant_id, participant_type, display_name, role_template_*, role_source, system_prompt, system_prompt_sha256, snapshot_at, joined_at |
| `discussion_messages` | id, discussion_id → discussion_threads, parent_message_id, author_*, content, status, model, round_number, content_sha256, created_at, deleted_at |
| `discussion_votes` | id, discussion_id → discussion_threads, participant_id, position, justification, round_number, created_at |
| `discussion_outcomes` | id, discussion_id → discussion_threads, summary, payload_json, created_at |
| `discussion_runs` | id, discussion_id → discussion_threads, status, autonomy, rounds_requested, rounds_completed, token_budget, tokens_used, time_budget_seconds, elapsed_ms, stop_reason, error, started_by_*, created_at, started_at, finished_at |
| `discussion_rounds` | id, discussion_id, run_id → discussion_runs, round_number, status, answers, failures, repeats, tokens_used, elapsed_ms, created_at, finished_at |
| `discussion_events` | seq (autoincrement), id, discussion_id → discussion_threads, type, payload_json, actor_*, created_at |
| `idempotency_records` | actor_id, idempotency_key, request_hash, response_json, created_at, expires_at |
| `cards_fts` | FTS5 external-content index over `cards.title`/`cards.description` (when supported) |

Indexes: `lists(position,id)`, `cards(list_id,position,id)`, `cards(updated_at)`,
`cards(archived_at)`, `cards(priority)`, `cards(due_at)`, `checklists(card_id,position)`,
`checklist_items(checklist_id,position)`, `comments(card_id,created_at)`,
`activity_log(timestamp)`, `activity_log(entity_type,entity_id)`,
`discussion_threads(card_id)`, `discussion_threads(status)`,
`discussion_participants(discussion_id)`, `discussion_messages(discussion_id,created_at)`,
`discussion_votes(discussion_id)`, `discussion_runs(discussion_id,created_at)`,
`discussion_runs(status)`, `discussion_rounds(run_id,round_number)` (unique),
`discussion_events(discussion_id,seq)`, `comment_mention_jobs(card_id,created_at)`,
`comment_mention_jobs(comment_id,agent_id)` (unique), `card_events(card_id,seq)`.

### Schema migrations (Alembic)

Two independent Alembic chains live under `backend/migrations`:

| Chain | Database | Version table | Head (current) |
| --- | --- | --- | --- |
| `registry` | `data/registry.sqlite` | `alembic_version` | `0015_registry_foreign_keys` |
| `board` | every `data/boards/{uuid}/board.sqlite` | `alembic_version` | `0011_board_foreign_keys` |

- The baseline revisions (`0001_registry_initial`, `0001_board_initial`) reproduce the schema that
  shipped before Alembic. A database that predates version tracking (no `alembic_version`) is
  detected by its tables and **stamped** at the baseline, then upgraded.
- Revision `0008_loops` is a structural redesign, not a data migration. A board database that still
  contains lists or cards refuses to upgrade and reports the development reset command; an empty
  database from an earlier revision upgrades normally. There is no preservation path for
  pre-Loop development data (see [Loops.md](../public_docs/Loops.md#clean-schema-transition)).
- New boards are created by upgrading an empty file to the chain head (`runner.create_schema`), so
  they always start at the latest schema.
- Existing boards are migrated **eagerly at startup**, sequentially, before the app accepts
  requests (`MigrationManager.migrate_all_boards`). Each board is handled inside its per-board lock
  with no open connections.
- Before a board's schema changes, a consistent snapshot is written to
  `data/backups/{board}/backup-<UTC>-pre-migration.sqlite` with SQLite's online backup API and
  integrity-checked. The snapshot is kept on success and on failure.
- `registry` revision `0002` rebuilds the `boards` table with `batch_alter_table` to extend the
  status `CHECK` with `migration_failed` and to add `schema_revision` — SQLite cannot alter a
  `CHECK` constraint in place.
- After upgrading, the manager runs `PRAGMA integrity_check` and `PRAGMA foreign_key_check`; any
  failure (or any exception) rolls back the schema transaction and marks the board
  `migration_failed`, which blocks mutations (`409 board_migration_failed`) and leaves reads
  unavailable until it is repaired. The retry endpoint is `POST /boards/{id}/migrate`.
- No downgrades exist: every revision's `downgrade()` raises. Rollback means restoring a
  pre-migration backup.
- Orchestration is idempotent: a database already at head is skipped and only its registry row is
  reconciled; a failed migration can be re-run after the cause is fixed; an interrupted run leaves
  the schema at its previous revision and resumes on the next start.
- Writes to schemas are only allowed through revisions. `tests/unit/test_migrations.py` scans the
  application package and fails if DDL appears outside the migration chain (the optional FTS5
  index bootstrap in `storage/schema/fts.py` is the single documented exception).
- The migrations are also the build's source of truth. `python -m tools.dbgen` (run from
  `backend/`, first in every build) refuses a chain with more than one head, a merge or a branch,
  migrates both chains into an in-memory database one revision at a time, applies the schema
  rules in `tools/dbgen/rules.py`, writes one frozen dataclass per table to `app/db/generated/`
  (git-ignored; Alembic's table and the FTS5 tables are excluded by name) and compiles every SQL
  statement in `app/` against that schema with SQLite's `EXPLAIN`. A table name the two chains share
  (`idempotency_records`) must have the same columns in both, because a statement passes when
  either database accepts it.

Runtime control: `app/storage/schema/runner.py` (programmatic Alembic), orchestration:
`app/storage/migration_manager.py`. Structured events: `migration_completed`,
`migration_adopted_legacy_schema`, `migration_failed`, `board_migration_batch_started/completed`.

### Integrity rules

- Foreign keys are enabled on every connection; deleting a card cascades to labels links,
  checklists, items and comments.
- Every column named `*_id` or `*_by` has a foreign key, unless `tools/dbgen/rules.py` lists it
  with its reason: `CROSS_DATABASE` (board columns that name an actor, agent, role template or
  board in the registry, which no constraint can reach), `NOT_REFERENCES` (polymorphic ids and
  correlation ids) or `UNENFORCED` (same-database references still without a key, each with what
  blocks it). Every foreign key starts an index and declares `ON DELETE`: RESTRICT by default;
  CASCADE or SET NULL only with a comment in the revision. Between two rows a Loop deletes
  together, RESTRICT would make deleting the Loop depend on the order SQLite visits the tables, so
  those keys CASCADE (the row is part of what it names) or SET NULL (an optional link).
  `python -m tools.dbgen` enforces all of this and keeps the lists exact.
- A revision adds a foreign key by rebuilding the table with `batch_alter_table`. The runner
  enforces foreign keys inside its transaction, and dropping the old copy fires the `ON DELETE`
  action of every row that references it, so a revision only rebuilds tables nothing references
  and adds no self-reference; the rest of `UNENFORCED` waits for migrations that run with foreign
  keys off and check them before commit (SQLite's documented table-rebuild procedure). Before a
  key is added, a reference whose row is gone is settled by meaning: an optional one becomes NULL,
  a NOT NULL one that the application cannot orphan stops the upgrade and names the rows. A
  revision starts with that DML, because Python's `sqlite3` runs DDL before the first
  INSERT/UPDATE/DELETE outside the transaction.
- Lists require archiving before deletion and must be empty of active cards.
- Boards require archiving and a name confirmation before physical deletion.
- All timestamps are ISO 8601 UTC strings with second precision (`2026-10-30T12:00:00Z`).
- `version` increments on every card mutation and is the optimistic-concurrency token.

### STRICT tables

- Every table a revision creates is `STRICT`: `op.create_table(..., sqlite_strict=True)`.
  SQLAlchemy renders the option itself, so no helper is needed. SQLite then refuses a value that
  does not fit the column's declared type instead of storing it under the looser type affinity, so
  a generated row's checked converter never meets a stray value.
- A STRICT column takes only the type names `INT`, `INTEGER`, `REAL`, `TEXT`, `BLOB` and `ANY`.
  In a revision that means `sa.Text()` for text, ids and timestamps, `sa.Integer()` for integers
  and flags, `sa.REAL()` for floating point and `sa.LargeBinary()` for bytes. `sa.String()`
  (VARCHAR), `sa.Boolean()`, `sa.DateTime()`, `sa.Float()` (FLOAT), `sa.BigInteger()`,
  `sa.Numeric()`, `sa.JSON()` and `sa.Uuid()` render names STRICT refuses, and the build stops at
  that revision with SQLite's message. `ANY` keeps whatever it is given, so it has no single
  Python type and the rows refuse it.
- A flag is `sa.Integer()` with `server_default="0"` or `"1"` and a named
  `CHECK (<column> IN (0, 1))`, as the flags of the older tables are stored (`enabled`,
  `is_current`); its generated field is `int`. A timestamp is `sa.Text()` holding an ISO 8601 UTC
  string, validated at the schema boundary; its field is `str`. A length limit that matters is a
  `CHECK (length(<column>) <= n)`: SQLite never enforced the `n` of `VARCHAR(n)`.
- `python -m tools.dbgen` applies each chain one revision at a time and takes the revision after
  which a table's name first appears as the one that created it; a rename counts as a creation. A
  table that is not STRICT stops the build with its chain, name and revision, unless that revision
  is on `NON_STRICT_REVISIONS` in `tools/dbgen/rules.py`: the revisions up to
  `0015_registry_foreign_keys` and `0011_board_foreign_keys`, from before the rule. The list stays
  exact: an entry with no table left without STRICT stops the build too.
- The older tables stay as they are. A `batch_alter_table` rebuild keeps a table's name and its
  mode (Alembic copies the reflected `STRICT` option, which SQLAlchemy 2.0.53 and later read back),
  so a rebuild neither converts an older table nor loses STRICT on a newer one. Converting an older
  table is not required and would be a revision of its own: every column needs a STRICT type name,
  and copying the rows into the STRICT table fails on any stored value that does not fit (a
  non-STRICT `INTEGER` column can hold text), so the upgrade of a real database would depend on its
  data.
- STRICT tables need SQLite 3.37.0 or newer, and an older SQLite cannot read the schema of a
  database that has one. The build refuses an older SQLite and names the version it migrated with.
  It runs on the interpreter that later runs the application (the container image runs it while it
  is built), so an older runtime never gets as far as a migration.

### FTS5

```sql
CREATE VIRTUAL TABLE cards_fts USING fts5(title, description, content='cards', content_rowid='rowid');
```

Insert/update/delete triggers keep the index in sync. If the runtime lacks FTS5 the migration
layer skips the index and search falls back to `LIKE`; `/search` reports `meta.engine`.

### Backups and restore

Backups use SQLite's online backup API (`sqlite3.Connection.backup`) so WAL state is captured
consistently. Backups live in `data/backups/{board_uuid}/backup-YYYYMMDDTHHMMSSZ.sqlite`, are
integrity-checked on creation, and can be restored by name (validated against
`^backup-\d{8}T\d{6}Z\.sqlite$`). Restore disposes the board engine, snapshots the backup into the
live file, then re-runs `integrity_check` and `foreign_key_check`.

### Export format (v1)

ZIP containing:

- `manifest.json` — `format_version: 1`, `exported_at`, board metadata;
- `board.sqlite` — consistent snapshot.

Import validates the manifest version, runs `PRAGMA quick_check`, rewrites `board_metadata.id` to
the new board UUID and registers the board as `active`.
