# AGENTS.md

Project-wide rules for every coding agent (human or AI) working in this repository.

## What this project is

An AI-native, self-hosted planning and delivery application: a React frontend for humans, a
FastAPI service layer for everyone, and one SQLite database per board. Work is organised as
App -> Boards -> Loops -> a Loop-owned Kanban of Tickets, with revisioned planning documents and
human approvals. There is no cloud dependency, no external AI provider and no Redis/Postgres/
message broker.

## Non-negotiable architecture rules

1. **One service layer.** Every interface (React UI, REST, WebMCP) calls the same functions in
   `backend/app/services/`. Business rules never live in routers, React components or WebMCP tools.
   A service reaches a database only through the repository Protocols and the units of work in
   `backend/app/repositories/` (`repositories/board.py` for a board, `repositories/registry.py` for
   the registry; implemented over SQL in `repositories/sql/`), never through
   `BoardDatabaseManager`, `Registry`, a connection or SQL text of its own. `services/lists.py` and
   `services/auth.py` are the references; services not converted yet still hold those handles until
   their conversion. The Loop workflow services reach the converted Loop and Ticket rules through
   the transitional `services/loop_bridge.py`, which is deleted when they are converted.
   `tests/unit/test_service_layer.py` holds the line: a service module that imports SQLAlchemy or
   `app.storage`, or calls `text`/`exec_driver_sql`, fails unless it is on that test's
   `NOT_YET_ON_REPOSITORIES` list, and the list only shrinks.
2. **Board isolation.** A board's data lives only in `data/boards/{uuid}/board.sqlite`. A board id
   is always a UUID resolved through `BoardDatabaseManager`; never build a path from user text.
2b. **A Loop owns its Kanban.** Boards contain Loops; loops contain lists, Tickets, documents,
   Phases and QA. There is no board-level Kanban and no ownerless column. Every list/Ticket path
   carries an explicit `loop_id` and the server rejects a mismatch (`409 loop_mismatch`). Phases
   are planning groups, never columns, and a column named `Done` never completes work.
3. **Registry is authoritative.** Board metadata, board templates, actors and credentials live in
   `data/registry.sqlite`. Board access is authorized through the registry before any board
   database is opened. Templates are registry data because they are chosen before a board (and its
   database) exists; instantiating one writes lists and labels into the new board database only.
4. **No direct SQLite access from the API/client.** Agents and the frontend only use `/api/v1`.
5. **Actor identity comes from authentication**, never from a request body. Audit entries record
   the authenticated actor id and type.
6. **Card mutations are version-checked.** `PATCH` and move require the expected `version`
   and return `409 version_conflict` on mismatch.
7. **Timestamps are ISO 8601.** Validate them at the schema boundary (`core/dates.py`); never
   accept free text for `due_at` or due-date filters.
8. **One backend process per data directory.** Per-board locks, the rate limiter and the session
   secret file are process-local. `storage/process_lock.py` takes an OS file lock at startup, so a
   second process on the same directory refuses to start. Do not scale out without a shared
   coordination store.
9. **Schema changes only through Alembic revisions.** Add a revision under
   `backend/migrations/registry` or `backend/migrations/board`; never edit a released revision and
   never write DDL anywhere else. Use `batch_alter_table` for SQLite table reconstruction; the
   runner applies revisions with foreign keys off and runs `foreign_key_check` before the COMMIT
   (SQLite's table-rebuild procedure), so any table may be rebuilt, and a column's `COLLATE`, which
   reflection drops, goes back through `reflect_args`. The Migration Manager
   (`storage/migration_manager.py`) applies revisions; it takes a verified pre-migration backup,
   validates integrity before the COMMIT and marks a failed board `migration_failed`. The
   migrations are the only description of the schema: `python -m tools.dbgen` validates both
   chains, generates the typed rows in `app/db/generated` from them and compiles every SQL
   statement in `app/` against the result, so nothing hand-written mirrors a table. Every column
   named `*_id` or `*_by` has a foreign key, an index that starts with it and an explicit
   `ON DELETE` (RESTRICT by default, CASCADE or SET NULL with a comment saying why), or an entry
   with its reason in `tools/dbgen/rules.py`; dbgen stops the build otherwise. Every table a new
   revision creates is `STRICT` (`op.create_table(..., sqlite_strict=True)`, with the column types
   `docs/database.md` names); dbgen stops the build on one that is not.
10. **No new infrastructure** without a documented decision in `docs/decisions/` (a local, untracked
    working document) that proves a requirement.
11a. **Planning decisions are human decisions.** Approving analysis or a RoadMap, resetting a scope,
    editing Info, confirming a human-only Ticket, accepting implementation or QA, and finalizing a
    Loop reject agent tokens (`403 human_action_required`) regardless of scope, and are never
    registered as WebMCP tools. Approvals bind to exact document revision ids; a changed input
    invalidates them. A reset supersedes the approval and replaces the scope's documents with an empty
    draft, so nothing downstream executes against text nobody stands behind.
11b. **Completed Loops are read-only.** Finalization writes an immutable, hashed snapshot to
    `loop_history` in the same transaction and blocks every mutation path afterwards.
11. **Role templates and agents are separate resources.** `role_templates` holds the shared,
    editable role prompt; `agents` holds identity, connection and credentials plus a *reference* to
    a template (or an override). Never join live templates into historical output: any discussion or
    run persists `AgentService.role_snapshot(...)` so later template edits cannot rewrite what an
    agent was told. Factory templates are data, not code: edit
    `backend/app/seeds/role_seeds.json`, validate via `services/role_defaults.py`, and keep the
    `scope` rule — `board` profiles may be selected for a board, `organisation` profiles
    (Coordinator, Architect) may not.
12. **Provider credentials are sealed, never echoed.** API keys are encrypted with
    `core/secrets.py`; responses and logs expose only `has_api_key` and a short hint. Endpoints are
    validated by `services/connections.validate_endpoint` (no metadata/link-local targets, no
    embedded credentials, no redirects; a host name is judged by every address it resolves to), and
    every call to an agent endpoint goes through `connections.endpoint_client`, which checks the
    same rule when it connects and connects only to the checked address. Never open another HTTP
    client to an agent endpoint.
13. **The worker surface is one catalogue.** `services/agent_tools.py` is the only description of
    what an external worker token may call; `/mcp` and `/llms.txt` are generated from it and every
    handler calls a service. Adding a capability is a catalogue entry plus a handler — never a new
    transport with its own rules — and a tool may be narrower than a scope, never wider.
    `tests/unit/test_worker_catalogue.py` holds every entry to this: a handler it can read, a
    section in `/llms.txt` and an entry in the MCP tool list, declared scopes that the opening
    `actor.require` checks of the handler (or of what it hands the actor to) cover and do not
    exceed, no rule-11a decision, and a unit test that names the tool. The local role agents stay
    readers: a run invokes them, they never authenticate, and they never change a Ticket.

## Repository layout

```text
backend/app/{api,core,db,models,repositories,schemas,services,storage,security,seeds}
backend/app/db/generated   typed rows written by tools/dbgen from the migrations (git-ignored)
backend/app/repositories/sql   the SQL implementations of the repository Protocols
backend/migrations/{registry,board}
backend/tools/dbgen   the first build step: migrations, generated rows, static SQL check
backend/tools/deps    the dependency checks: licence inventory and vulnerability audit
backend/tests/{unit,infrastructure}   unit tests and guards (the default); the minimal SQLite suite
frontend/src/{app,components,features,lib,webmcp,themes,tests}
frontend/e2e/    the Playwright journeys
public_docs/     everything a user or operator follows: installation, onboarding, commands,
                 architecture, troubleshooting, security, agent usage, the API and the Loop workflow
docs/            maintainer notes that stay in the repository: the database and schema reference
scripts/         run-playwright.mjs, the isolated Playwright runner

# Untracked working documents, ignored by git and never linked from a public document:
#   docs/decisions/   why the code looks the way it does
#   analysis/         the review reports
#   .ralph/           progress.txt (the running log) and the Loop implementation specification
```

`repositories/` holds the repository Protocols, shaped by what the services need, and `db/` the
generated rows and their checked value converters. `models/` and `security/` are reserved for code
that is promoted out of `storage/` and `core/` when it grows; do not duplicate logic into them.

`tests/unit/test_instruction_files.py` holds this file to the tree: the layout block above, the commands
below and every file path it names must exist, every relative link in a shipped document must
resolve, and no shipped document or source may describe the licence as anything but
source-available. Move a directory and its line here in the same change.

## Commands

Backend (run from `backend/`):

```powershell
..\.venv\Scripts\python.exe -m tools.dbgen                            # first: migrations, rows, SQL
..\.venv\Scripts\python.exe -m ruff check app tests migrations tools  # lint, what CI runs
..\.venv\Scripts\python.exe -m pyright                                # types: pyrightconfig.json
..\.venv\Scripts\python.exe -m pytest                                 # unit tests (primary gate)
..\.venv\Scripts\python.exe -m pytest tests/infrastructure            # the minimal SQLite suite
..\.venv\Scripts\python.exe -m tools.deps licences                    # every dependency's licence
..\.venv\Scripts\python.exe -m tools.deps audit                       # pip-audit + pnpm audit
..\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload
```

Frontend (run from `frontend/`):

```powershell
pnpm test           # vitest unit/component tests
pnpm typecheck      # tsc --noEmit
pnpm lint           # Prettier --check, then ESLint (eslint.config.js), every rule an error
pnpm format         # Prettier rewrites what pnpm lint would reject for formatting
pnpm build          # production build (includes typecheck and ESLint)
pnpm dev            # dev server on :5173, proxies /api to :8000
pnpm test:e2e       # Playwright journeys against an isolated stack (:8077 + :5273)
pnpm lint:md        # markdownlint on README.md, AGENTS.md, docs/ and public_docs/
```

Use pnpm for frontend work. `pnpm test:e2e` reuses a locally installed Playwright (no vendored
copy) and starts each run from an empty `frontend/e2e/.data` so one run cannot affect the next
(`E2E_KEEP_DATA=1` keeps the directory); see `scripts/run-playwright.mjs`.

## Conventions

- Python: **3.13 is the version of record** — the container image, CI's primary job and your
  virtual environment all run it, so a local run means what CI means. CI also runs 3.14, and
  `requires-python` allows it; anything newer is untested and needs a CI leg before it is claimed.
  Typed, ruff-clean (line length 100), no blocking work in async paths. The Ruff rule set and its
  few ignores live in `backend/pyproject.toml`, each ignore with its reason; an inline `# noqa`
  names its rule and says why. No `print` in `app/`: use a logger.
- Routes and FastAPI dependencies are plain `def`, which FastAPI runs in a worker thread, so a
  slow request never holds up another. `async def` is only for a route that awaits (today the
  three that read a raw request body), and such a route calls `get_context` and every service
  through `run_in_threadpool`; `backend/tests/unit/test_async_routes.py` enforces both. The pool
  size is `THREADPOOL_TOKENS` in `backend/app/main.py`, and event streams wait on a limiter of
  their own. Requests run in parallel, so in-memory state shared between them takes a lock.
- SQL text is literal and values are bind parameters (a list is an expanding parameter,
  `IN :ids`). The only things formatted into a statement are identifiers and fragments taken from
  a module-level tuple of string literals through `app/core/sql.py`; such a line carries
  `# noqa: S608 - from <TUPLE>`.
- A transaction that writes opens with `write_transaction(engine)` from
  `backend/app/storage/sqlite.py` and starts with `BEGIN IMMEDIATE`, so a second writer waits at its
  `BEGIN` instead of failing halfway; `Registry.connect`, `BoardDatabaseManager.session` and the
  migration runner use it. A reader uses `engine.connect()` and starts a deferred `BEGIN`.
  SQLAlchemy sends every `BEGIN` (`backend/app/core/transactions.py`), so DDL is transactional, and
  `backend/tests/unit/test_transactions.py` refuses an `engine.begin()` anywhere else in `app/`.
- Text files are UTF-8 without a byte-order mark and use LF line endings (`.gitattributes`,
  `.editorconfig`). Backend code writes text with `newline=""` or writes bytes, so a file written on
  Windows is byte-identical to one written on Linux; `tests/unit/test_text_files.py` enforces both.
- Database rows are the generated `<Table>Row` dataclasses (`app/db/generated`, never edited by
  hand; rerun `python -m tools.dbgen` after a migration). A repository selects exactly a row's
  columns (`sql.column_list(<TABLE>_COLUMNS)`) and maps each result through the row's checked
  `from_mapping`. A join returns the rows side by side in a small frozen value: each table is
  selected through its alias, every joined one also under a prefix
  (`sql.column_list(ACTORS_COLUMNS, 'a', 'actor__')`), and read back with `values.prefixed`, so two
  tables' `id` never share a result key. A service returns typed values (a row, a `TypedDict` of
  its JSON shape), and a unit test changes a row with `row.__replace__(...)`, which pyright checks,
  not `dataclasses.replace`. A partial update takes a `TypedDict(total=False)` of its columns; the
  literal tuple its SQL formats them from sits beside it in the Protocol module, and
  `tests/unit/test_sql.py` holds the two equal. A write SQLite may refuse for a constraint a request
  can break (a taken unique name) raises `ConstraintViolationError` from the SQL repository, and the
  service answers it, so no service imports a driver error.
- Pyright runs strict on the scope in `backend/pyrightconfig.json`: `app/core`, `app/schemas`, the
  generated rows, the repositories, every converted service, the unit tests and the build tools.
  In that scope there is no `Any`, no `cast` and no `# type: ignore`. Each converted service joins
  the scope. `app/api`, `app/main.py` and `app/dev_reset.py` are checked in pyright's `standard`
  mode while the services they call return untyped values; `app/storage` and the unconverted
  services are not checked yet. `tests/unit/test_strict_scope.py` enforces all of it, so the
  scope can only grow.
- TypeScript: strict, plus `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
  `noImplicitOverride` and `verbatimModuleSyntax` (`frontend/tsconfig.json`). An index or regex
  result is narrowed, never asserted with `!`; an optional property that may be passed `undefined`
  says so (`?: T | undefined`); type-only imports say `import type`. No `any` unless justified,
  semantic CSS variables from `src/index.css`.
- ESLint (`frontend/eslint.config.js`): typed typescript-eslint, React hooks, jsx-a11y and import
  rules, every one an error. A rule is switched off or configured only in that file, with its reason
  on the line above; there is no inline `eslint-disable`.
- A frontend file holds at most 300 lines of code (ESLint `max-lines`; blank lines and comments do
  not count), tests and the API client included. Split a component by what it shows: each section
  becomes a component with explicit props, and state stays with the component that owned it, carried
  by a hook in a `.ts` file when that keeps the owner small. The REST client and the response types
  are one module per domain, re-exported by `src/lib/api/index.ts` and `src/lib/types/index.ts`, so
  callers keep importing `@/lib/api` and `@/lib/types`.
- Formatting is Prettier's, not a reviewer's: `frontend/.prettierrc.json` (100 columns, double
  quotes, trailing commas everywhere; the rest is Prettier's defaults, which match `.editorconfig`)
  covers the frontend's TypeScript, JavaScript, JSON, CSS and HTML. Run `pnpm format` before a
  commit; `pnpm lint` fails on any file it would change. `eslint-config-prettier` comes last in the
  ESLint config so no lint rule argues about layout. Markdown is markdownlint's alone, so Prettier
  does not touch it. Commits that only reformat are listed in `.git-blame-ignore-revs`; run
  `git config blame.ignoreRevsFile .git-blame-ignore-revs` once so `git blame` skips them.
- API: JSON envelope `{success, data, request_id, meta}`; errors `{success:false, error, request_id}`.
  Unknown request fields are rejected (`extra="forbid"`). Timestamps are ISO 8601 UTC.
- Frontend state: TanStack Query for server state; no global store for board data.
- Signing out has one path, `signOutLocally()` from `useAuth()`
  (`src/features/auth/AuthProvider.tsx`): logout, a password change and every 401
  (`tralala:unauthorized`) end there. It sets `me` to null while AuthProvider observes it, so
  `RequireAuth` redirects to the login page, then removes every other query; once `me` is null it does
  nothing, so a burst of 401s signs out once. ESLint's `no-restricted-syntax` forbids clearing the
  query cache anywhere in `src/`: `clear()` drops `me` from under its observer and leaves a dead
  session on screen.
- Every level of the route tree in `src/app/App.tsx` renders inside `RouteErrorBoundary`
  (`src/app/RouteErrorBoundary.tsx`): a page that throws shows a fallback inside the layout, with the
  request id of an `ApiError`, "Try again" and "Reload page". Add a route inside the existing levels,
  never beside them. A query that wants its error on that fallback sets `throwOnError`; "Try again"
  resets it so it fetches again. Only the root's `onCaughtError` (`src/app/errorReporting.ts`)
  writes to the console, once per caught error; ESLint's `no-console` holds the rest of `src/`.
- A page is declared in `src/app/App.tsx` with `lazyPage` (`src/app/chunkLoading.ts`), so it is
  its own chunk; layouts stay eager, so a URL renders one lazy page. A page chunk that cannot be
  loaded (a tab left open across an upgrade) reloads the tab once; a sessionStorage flag set before
  the reload and cleared by the next page that loads makes a reload loop impossible.
- Frontend tests answer the API through MSW (`src/tests/msw/`), never by replacing the client:
  `src/tests/setup.ts` starts one server per test file, a request no handler answers fails, and the
  handlers return the real envelope, so the JSON body, the CSRF header, the envelope check and the
  401 → `tralala:unauthorized` path run in every test that sends a request. ESLint's
  `no-restricted-syntax` forbids `vi.mock` of the API client, `vi.spyOn(api, …)` and stubbing
  `fetch`. The journey `frontend/e2e/accessibility.spec.ts` runs axe-core on the dashboard, a Loop
  page and Settings: a serious or critical violation fails it, moderate and minor ones are
  annotations on the test.
- Card content is untrusted: Markdown is rendered by `src/lib/markdown.tsx`, which never injects HTML.

## Verification contract

The backend build is a pipeline, run in this order locally and in CI, stopping at the first
failure: `python -m tools.dbgen` -> `ruff` -> `pyright` -> `pytest` (unit) -> `pytest
tests/infrastructure`.

- **`python -m tools.dbgen`** proves the schema side without a test: each Alembic chain is linear
  and migrates from empty to head (in memory), the schema rules hold, the typed rows are generated,
  and every SQL statement in `app/` compiles (SQLite `EXPLAIN`) against that schema. It caches by
  hash, so an unchanged schema and unchanged statements cost almost nothing; `--check` only
  compares.
- **`pyright`** proves the types: a schema change that renames or adds a column breaks every row
  consumer (repository, fake, service) before a test runs.
- **Unit tests** (`tests/unit/`, the default `pytest`) give a function a fixed input and assert what
  comes back, and the same input always gives the same result. A service runs its real code
  against the typed in-memory fakes in `tests/unit/fakes/`, which implement the repository
  Protocols over the generated rows. A unit test never builds the application (`create_app`,
  `TestClient`), never opens SQLite or imports `app.storage`, `app.repositories.sql` or
  `tools.dbgen`, never reaches the network and never sleeps or starts a thread; anything expensive
  and shared is a session-scoped fixture built once, and the suite runs in parallel
  (`pytest -n auto`) as well as in order. `tests/unit/test_unit_only.py` enforces this, and the
  suite refuses to start on rows generated from an older schema. When a rule sits inside a request
  path, extract the pure part and test that, as `csrf_satisfied` in `core/security.py` is.
- **The infrastructure suite** (`tests/infrastructure/`) is the only backend test that opens SQLite,
  and it stays minimal: connection set-up, migrations to completion, each unit of work's commit and
  rollback, a board releasing its file, availability. One real database per session, never per
  test; no test per table, column, constraint or repository, and no business rule against a real
  database.
- The running stack (HTTP, authentication, the databases together) is exercised by the Playwright
  journeys in `frontend/e2e/`.

A story is complete only when:

- schema changes include an Alembic revision and `python -m tools.dbgen` passes on it (there are no
  migration tests; the Migration Manager's verified backup, integrity check and `migration_failed`
  marking guard an upgrade),
- behavioural changes include unit tests of the functions that carry the behaviour,
- the smallest relevant test command passes,
- `ruff check` and `pyright` (backend), `tsc --noEmit` and `pnpm lint` (frontend) pass,
- the production frontend build succeeds for UI changes,
- user-journey changes extend `frontend/e2e/*.spec.ts`,
- no existing test regressed.

Never mark work complete because code was written. Append what you did and anything still open to
`.ralph/progress.txt` (untracked, local); an open item stays open until a test proves it closed.

A public document must never link into `docs/decisions/`, `analysis/` or `.ralph/`: those folders are
not shipped, so a link from `public_docs/`, `README.md` or `CONTRIBUTING.md` is broken for everyone
else. State the rule instead of pointing at where it was decided.

## Security invariants

- API tokens and passwords are stored hashed only. Tokens are returned once.
- Every token records the account that issued it (`owner_actor_id`). A member may only grant
  `MEMBER_TOKEN_SCOPES`, and disabling an account revokes the access it issued.
- Cookie-authenticated mutations require the CSRF double-submit header.
- Scopes are enforced server-side on every request; WebMCP only registers tools the actor may use.
- Card text is never interpreted as instructions or executed; only `http(s)` links are rendered.
- Path inputs are validated (UUID board ids, backup filename pattern) before filesystem access.
- A known vulnerability in a dependency fails CI: `python -m tools.deps audit` runs pip-audit over
  both requirements files (any advisory fails) and pnpm audit over the lockfile (high and critical
  fail). Fix it by a bump; only an advisory without a usable fix goes into
  `backend/tools/deps/audit_allowlist.toml`, with a reason and an expiry at most 90 days ahead.
  Dependabot (`.github/dependabot.yml`) proposes the weekly updates.

## Licensing invariants

This project is **source-available, not open source**: it ships under the PolyForm Noncommercial
License 1.0.0 and BitNomad AB sells commercial licences alongside it, so every line must be owned by
the company. The licence analysis and the open legal questions are recorded in the local decision
log (`docs/decisions/0009`, untracked).

- Never describe the project as open source — not in code, docs, UI copy, commit messages or release
  notes.
- Never paste code from another project into this repository. If a snippet is genuinely needed, name
  its source and licence in the pull request, and never import GPL, AGPL, SSPL or
  proprietary-licensed code.
- Do not remove or edit `LICENSE`, `NOTICE`, `CLA.md` or `CONTRIBUTING.md` without an explicit
  request; the licence and its `Required Notice:` line must survive in every redistribution.
- A contribution that cannot be covered by a signed CLA must not be merged — under this licence a
  merged pull request can make the code unsellable.
- A dependency under a copyleft licence is a decision, not a detail: record it in the decision log.
  The current set is MIT, ISC, BSD, 0BSD, Apache-2.0, PSF, MIT-0, MPL-2.0, BlueOak-1.0.0 (only
  `minimatch`, used by the lint tooling) and two data licences: CC-BY-4.0 (only `caniuse-lite`, data
  with an attribution notice and no code) and CC0-1.0 (only `language-subtag-registry`, the IANA
  language list the accessibility linter reads). Nothing copyleft.
- `python -m tools.deps licences` holds every installed dependency to that set, Python and npm,
  runtime and development alike, and runs in CI. `backend/tools/deps/licences.toml` is the set as
  SPDX ids (change it and the sentence above together; a test compares them), plus an override
  with a reason for a package whose metadata names no readable licence.
- Never publish signed contributor agreements in the repository.
