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
6. **Card mutations are version-checked.** `PATCH`/move/transfer require the expected `version`
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
10. **No new infrastructure** without a documented decision in `docs/decisions/` that proves a
    requirement.
11a. **Planning decisions are human decisions.** Approving analysis or a RoadMap, editing Info,
    confirming a human-only Ticket, accepting implementation or QA, and finalizing a Loop reject
    agent tokens (`403 human_action_required`) regardless of scope, and are never registered as
    WebMCP tools. Approvals bind to exact document revision ids; a changed input invalidates them.
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

```
backend/app/{api,core,models,repositories,schemas,services,storage,security,migrations}
frontend/src/{app,components,features,api,webmcp,hooks,themes,tests}
public_docs/     what a user or operator follows: installation, onboarding, commands, architecture,
                 troubleshooting, security, agent usage
docs/            API, database notes, the Loop workflow and decisions
.ralph/          prd.json, progress.txt, prompt.md (Ralph Loop state)
scripts/ralph/   loop harness
```

`models/`, `repositories/` and `security/` are reserved for code that is promoted out of
`storage/` and `core/` when it grows; do not duplicate logic into them.

## Commands

Backend (run from `backend/`):

```powershell
..\.venv\Scripts\python.exe -m pytest          # tests (primary gate)
..\.venv\Scripts\python.exe -m ruff check app  # lint
..\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload
```

Frontend (run from `frontend/`):

```powershell
pnpm test           # vitest unit/component tests
pnpm typecheck      # tsc --noEmit
pnpm build          # production build (includes typecheck)
pnpm dev            # dev server on :5173, proxies /api to :8000
pnpm test:e2e       # Playwright journeys against an isolated stack (:8077 + :5273)
```

Use pnpm for frontend work. `pnpm test:e2e` reuses a locally installed Playwright (no vendored
copy) and starts each run from an empty `frontend/e2e/.data` so one run cannot affect the next
(`E2E_KEEP_DATA=1` keeps the directory); see `scripts/run-playwright.mjs`.

## Conventions

- Python: 3.13+, typed, ruff-clean (line length 100), no blocking work in async paths.
- TypeScript: strict, no `any` unless justified, semantic CSS variables from `src/index.css`.
- API: JSON envelope `{success, data, request_id, meta}`; errors `{success:false, error, request_id}`.
  Unknown request fields are rejected (`extra="forbid"`). Timestamps are ISO 8601 UTC.
- Frontend state: TanStack Query for server state; no global store for board data.
- Card content is untrusted: Markdown is rendered by `src/lib/markdown.tsx`, which never injects HTML.

## Verification contract

A story is complete only when:

- schema changes include an Alembic revision plus tests for fresh install, upgrade from an empty
  database at the previous revision, the explicit development reset and failure recovery
  (pre-Loop data is deliberately not migrated),
- the smallest relevant test command passes,
- `ruff check` (backend) and `tsc --noEmit` (frontend) pass,
- the production frontend build succeeds for UI changes,
- API-level tests exist for behavioural changes,
- user-journey changes extend `frontend/e2e/*.spec.ts`,
- no existing test regressed.

Never mark a story complete because code was written. Record failures in `.ralph/progress.txt`
and leave the story pending.

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
the company. See `docs/decisions/0009-source-available-licensing-and-contributions.md`.

- Never describe the project as open source — not in code, docs, UI copy, commit messages or release
  notes.
- Never paste code from another project into this repository. If a snippet is genuinely needed, name
  its source and licence in the pull request, and never import GPL, AGPL, SSPL or
  proprietary-licensed code.
- Do not remove or edit `LICENSE`, `NOTICE`, `CLA.md` or `CONTRIBUTING.md` without an explicit
  request; the licence and its `Required Notice:` line must survive in every redistribution.
- A contribution that cannot be covered by a signed CLA must not be merged — under this licence a
  merged pull request can make the code unsellable.
- A dependency under a copyleft licence is a decision, not a detail: record it in `docs/decisions/`.
  The current set is MIT, ISC, BSD, Apache-2.0, PSF, MIT-0 and MPL-2.0 only.
- Never publish signed contributor agreements in the repository.

