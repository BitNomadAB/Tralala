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
   never write DDL anywhere else. Use `batch_alter_table` for SQLite table reconstruction. The
   Migration Manager (`storage/migration_manager.py`) applies revisions; it takes a verified
   pre-migration backup, validates integrity and marks a failed board `migration_failed`.
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
    embedded credentials, no redirects).
13. **The worker surface is one catalogue.** `services/agent_tools.py` is the only description of
    what an external worker token may call; `/mcp` and `/llms.txt` are generated from it and every
    handler calls a service. Adding a capability is a catalogue entry plus a handler — never a new
    transport with its own rules — and a tool may be narrower than a scope, never wider. The local
    role agents stay readers: a run invokes them, they never authenticate, and they never change a
    Ticket.

## Repository layout

```text
backend/app/{api,core,models,repositories,schemas,services,storage,security,seeds}
backend/migrations/{registry,board}
backend/tests/   pytest unit tests, including the guard tests that hold the code to these rules
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

`models/`, `repositories/` and `security/` are reserved for code that is promoted out of
`storage/` and `core/` when it grows; do not duplicate logic into them.

`tests/test_instruction_files.py` holds this file to the tree: the layout block above, the commands
below and every file path it names must exist, every relative link in a shipped document must
resolve, and no shipped document or source may describe the licence as anything but
source-available. Move a directory and its line here in the same change.

## Commands

Backend (run from `backend/`):

```powershell
..\.venv\Scripts\python.exe -m pytest                            # unit tests (primary gate)
..\.venv\Scripts\python.exe -m ruff check app tests migrations  # lint, what CI runs
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
  Typed, ruff-clean (line length 100), no blocking work in async paths.
- Text files are UTF-8 without a byte-order mark and use LF line endings (`.gitattributes`,
  `.editorconfig`). Backend code writes text with `newline=""` or writes bytes, so a file written on
  Windows is byte-identical to one written on Linux; `tests/test_text_files.py` enforces both.
- TypeScript: strict, plus `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
  `noImplicitOverride` and `verbatimModuleSyntax` (`frontend/tsconfig.json`). An index or regex
  result is narrowed, never asserted with `!`; an optional property that may be passed `undefined`
  says so (`?: T | undefined`); type-only imports say `import type`. No `any` unless justified,
  semantic CSS variables from `src/index.css`.
- ESLint (`frontend/eslint.config.js`): typed typescript-eslint, React hooks, jsx-a11y and import
  rules, every one an error. A rule is switched off or configured only in that file, with its reason
  on the line above; there is no inline `eslint-disable`.
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
- Every level of the route tree in `src/app/App.tsx` renders inside `RouteErrorBoundary`
  (`src/app/RouteErrorBoundary.tsx`): a page that throws shows a fallback inside the layout, with the
  request id of an `ApiError`, "Try again" and "Reload page". Add a route inside the existing levels,
  never beside them. A query that wants its error on that fallback sets `throwOnError`; "Try again"
  resets it so it fetches again. Only the root's `onCaughtError` (`src/app/errorReporting.ts`)
  writes to the console, once per caught error; ESLint's `no-console` holds the rest of `src/`.
- Card content is untrusted: Markdown is rendered by `src/lib/markdown.tsx`, which never injects HTML.

## Verification contract

Backend tests are unit tests. A test gives a function a fixed input and asserts what comes back,
and the same input always gives the same result. A backend test never builds the application
(`create_app`, `TestClient`), never opens SQLite (engines, sessions, `BoardDatabaseManager`,
migrations), never reaches the network and never sleeps or starts a thread; anything expensive and
shared is a session-scoped fixture built once, so the whole suite runs in seconds.
`tests/test_unit_only.py` enforces this. When a rule sits inside a request or database path, extract
the pure part and test that, as `csrf_satisfied` in `core/security.py` and `canonical_board_id` in
`core/identifiers.py` are. The running stack (HTTP, authentication, the databases, migrations) is
exercised only by the Playwright journeys in `frontend/e2e/`; no backend test covers it.

A story is complete only when:

- schema changes include an Alembic revision (there are no migration tests; the Migration Manager's
  verified backup, integrity check and `migration_failed` marking guard an upgrade),
- behavioural changes include unit tests of the functions that carry the behaviour,
- the smallest relevant test command passes,
- `ruff check` (backend), `tsc --noEmit` and `pnpm lint` (frontend) pass,
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
- Never publish signed contributor agreements in the repository.
