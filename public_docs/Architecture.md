# Architecture

How Tralala is put together: one service layer, one database per board, one worker surface. Read this
after [Installation](Installation.md) and [Onboarding](Onboarding.md); the product rules themselves
live in [Loops.md](Loops.md) and the endpoint reference in [API.md](API.md).

| Question | Where |
| --- | --- |
| what a Loop is and in which order work happens | [Loops.md](Loops.md) |
| the exact request/response contract | [API.md](API.md) |
| tables, revisions and integrity rules | the *Storage model* section below |
| why something is built the way it is | the reasoning paragraph in the section that describes it |
| what an external agent may call | [Agent_usage.md](Agent_usage.md) and `GET /llms.txt` |

## Overview

```text
browser ── Caddy ──┬── React UI (built SPA)
                   │      │
                   │      ├── WebMCP adapter (in-page tools)
                   │      └── REST  /api/v1
                   │
external agent ────┴── /mcp (JSON-RPC)  ──┬── FastAPI ── Services ── storage
                                          │                  │
                            /llms.txt ────┘                  ├── registry.sqlite
                                                             └── boards/{uuid}/board.sqlite
                                                                 + attachments/
```

One modular Python monolith. Every interface (React UI, WebMCP adapter, external workers over REST
or MCP) reaches the same service functions; no business rule is duplicated in the frontend, in the
WebMCP tool definitions or in the MCP catalogue. Caddy in front is a web tier, not a second brain: it
serves the built bundle, proxies the API and terminates TLS.

The worker surface has one source: `backend/app/services/agent_tools.py` describes the tools an
external agent may call (name, description, JSON Schema, required scopes, handler). `/mcp` serves it
and `/llms.txt` summarises it; both end in the same service calls the REST routes use. The browser
WebMCP adapter stays a separate, UI-contextual surface for a person's own session.

### Authoritative hierarchy

```text
App (Tralala shell, Board overview)
  Board (a project, application or defined part of one)
    Loop (one feature or coherent change initiative)
      Kanban header: Info, Analysis, RoadMap, Loop status, approvals, QA status
      Kanban: Loop-owned columns containing Tickets
      Numbered delivery Phases, shown in the RoadMap and on Tickets
```

A Board contains Loops; a Loop owns its Kanban, columns, Tickets and planning documents. Two Loops
in one Board never share columns or ordering. The Board stays the storage boundary: `registry.sqlite`
holds global metadata, `boards/{uuid}/board.sqlite` holds every Loop of that board. Phases are
planning groups, not Kanban columns.

### Backend layers

| Layer | Location | Responsibility |
| --- | --- | --- |
| API | `backend/app/api` | HTTP routing, authentication dependency, envelopes, status codes |
| Services | `backend/app/services` | Business rules, transactions, activity logging, ordering |
| Repositories | `backend/app/repositories` | Typed interfaces a service reads and writes through, the units of work that open a reader or writer on a board or on the registry, and a board's files (its database and attachments) as boards are created, copied, exported, imported and deleted; `repositories/sql` implements them over SQL |
| Rows | `backend/app/db` | One typed row class per table, generated from the migrations by `python -m tools.dbgen` |
| Storage | `backend/app/storage` | SQLite engines, migrations, registry and per-board databases |
| Schemas | `backend/app/schemas` | Pydantic v2 request/response validation |
| Core | `backend/app/core` | Settings, errors, security primitives, actor context, rate limiting, host filesystem profile |
| Seeds | `backend/app/seeds` | Factory data seeded into a new registry, currently the role templates |
| Worker tools | `backend/app/services/agent_tools.py` | The curated catalogue an external worker may call, served by `/mcp` and summarised by `/llms.txt` |

### Frontend layers

| Layer | Location | Responsibility |
| --- | --- | --- |
| App shell | `frontend/src/app` | Router, providers, layout |
| Features | `frontend/src/features` | Boards, Loops, Loop Kanban and planning dialogs, history, discussions, settings, auth |
| API client | `frontend/src/lib/api.ts` | Typed REST client, envelope unwrapping, CSRF header |
| WebMCP | `frontend/src/webmcp` | Capability detection, registry adapter, contextual tools |
| Theme | `frontend/src/themes` | Theme kits (`data-theme-kit`) x dark/light/system over semantic CSS variables |
| Web tier | `frontend/Caddyfile` | Static SPA, one security header policy, reverse proxy, TLS |

## Storage model

- `data/registry.sqlite` holds boards, board templates, role templates, agents, actors, sessions,
  credentials, the repositories a board is about (with their sealed read-only tokens), the
  `board_repositories` and `board_agents` links between a board and what works on it, and
  registry-level idempotency records. Secrets live here rather than in a board database, so a board
  export never carries one.
- `data/boards/{uuid}/board.sqlite` holds Loops, their documents, approvals, plans, QA cycles,
  history, Loop-owned lists, Tickets (cards), labels, checklists, comments, discussions, the per-Loop
  agent preference per purpose and activity.
- `data/boards/{uuid}/attachments/{attachment_id}.bin` holds the uploaded files of that board. The
  directory and the database are one unit: deleting a board removes both, duplicating it copies both,
  and an export carries both.
- `data/backups/{uuid}/backup-YYYYMMDDTHHMMSSZ.sqlite` holds consistent snapshots, each with an
  optional `backup-YYYYMMDDTHHMMSSZ-attachments.zip` partner that carries the board's files at that
  moment. Restoring and pruning treat the pair as one.
- `data/exports/` is reserved for generated exports; the export endpoint streams the archive instead.
- `data/.session-secret` holds the generated per-install session secret when `TRALALA_SECRET_KEY` is
  unset (owner-only permissions); `data/.bootstrap-password` holds a generated first-administrator
  password until it is deleted; `data/.process.lock` proves that one backend process owns the
  directory.

Board ids are UUIDs validated before any path is constructed, so user input never reaches the
filesystem. Each board engine is created with `NullPool`, `foreign_keys=ON`, WAL journaling and a
5 s busy timeout; engines idle longer than `TRALALA_BOARD_IDLE_CLOSE_SECONDS` are disposed, and the
cache is capped so a host with many boards cannot exhaust file handles.

## Request lifecycle

1. Caddy serves the shell or forwards `/api`, `/docs`, `/openapi.json`, `/mcp` and `/llms.txt`, with
   a streaming body ceiling one step above the backend's own.
2. Middleware assigns `X-Request-ID`, rejects a declared body over the limit and adds security
   headers; the endpoints that read raw bytes (`/mcp`, attachment upload, board import) count the
   bytes as they arrive, so a chunked body without a `Content-Length` header is bounded too.
3. `get_context` resolves the actor from a bearer token or a signed session cookie (validated
   against the `sessions` row), enforces CSRF for cookie-authenticated mutations, and applies the
   per-actor rate limiter. Session scopes come from the account role: `admin` has every scope,
   `member` every scope except `users:admin` and `credentials:admin`. Authentication happens before
   `/mcp` parses a body.
4. The router validates the payload with a strict Pydantic model and calls a service.
5. The service authorizes the scope, opens exactly one board transaction, mutates state, writes an
   activity entry and returns a plain dict.
6. The response is wrapped as `{success, data, request_id, meta}` and validated by the response
   model.

Board access is guarded by a re-entrant per-board lock shared by `open`, `session`, `reader` and
`restore`, so a restore is exclusive inside the process.

## Consistency across databases

SQLite has no cross-file transactions, so:

- A request mutates at most one board database.
- Board creation inserts a `maintenance` registry row, creates the database at the board chain
  head through Alembic, then flips the row to `active`. Failures set `error`;
  `BoardService.recover()` repairs rows left in `maintenance` during startup.
- Board import writes the archive's database into the new board's directory and has the Migration
  Manager judge it (read only, untrusted, `integrity_check` first) before a registry row exists, then
  adds the row, migrates, and activates. A refusal or any later failure removes the files, the
  pre-migration snapshot and the row, so a bad archive never becomes a board.
- Schema upgrades are owned by `MigrationManager`: the registry chain runs first, then every board
  is migrated eagerly and sequentially before requests are served, with a verified pre-migration
  snapshot and post-migration integrity checks. A failed board is marked `migration_failed` and
  blocks mutations until `POST /boards/{id}/migrate` succeeds.
- Deleting a board removes the board directory and its backups **before** the registry row, so an
  interrupted delete leaves a board that can be deleted again rather than a row pointing at nothing.
- Card transfer between Loops or Boards is not supported: it would bypass the approved plan. The
  endpoint is removed and the service answers `409 plan_change_required` so a caller gets an
  actionable error instead of a silent shortcut.
- Board templates are registry rows because they are selected before a board exists. Creating a
  board with `template_id` stores the template's column names as the board's Loop defaults and its
  labels in the new board database; it never creates ownerless columns. Creating a Loop copies
  those defaults into Loop-owned columns.
- AI roles are split in two on purpose: `role_templates` (shared, editable) and `agents` (identity,
  connection, sealed credential, template reference or override). Discussions, mentions and
  generation runs persist `AgentService.role_snapshot(...)`, so later template edits cannot rewrite
  what an agent was told.

## Loop workflow

The Loop workflow is the only place where planning rules live, and every interface reaches it
through `services/loops.py`, `loop_documents.py`, `loop_plans.py`, `loop_generation.py`,
`loop_qa.py` and `loop_history.py`.

- **Documents.** Five slots per Loop: `info` (human intent), `analysis_ai`/`analysis` and
  `roadmap_ai`/`roadmap`. Revisions are immutable, current and approved pointers are separate, and
  the human views are rendered by the server from the validated structure, so a model cannot
  invent or omit work only in the summary.
- **Approvals.** `loop_approvals` stores human decisions bound to exact revision ids and source
  hashes. Any change to an input revision makes the dependent approvals stale; the Loop stage
  becomes `replanning` and execution transitions are frozen until a replacement plan is approved.
- **Plans.** The structured RoadMap revision is authoritative. Phases and planned Tickets carry
  stable UUIDs and keys; the relational rows are a validated projection. Validation rejects
  unknown references, self-dependencies and cycles, including the implicit normal-Ticket-to-Phase
  edge. RoadMap approval publishes every Ticket in one transaction and is idempotent.
- **Readiness.** Phase completion is derived from Ticket dispositions; a Phase is entered when its
  prerequisite Phases, prerequisite Tickets and its own pre-phase gates are satisfied. A gate
  never depends on its own Phase, so it cannot deadlock. `GET /readiness` and every completion
  transition use the same evaluation.
- **QA.** Accepting implementation and accepting QA are separate human decisions. One QA Task
  carries an agent view and a human view built from the same scenario ids. Agent-submitted results
  are recorded, never accepted on the agent's behalf.
- **History.** Completion writes an immutable, hashed snapshot into `loop_history` (plus
  `loop_history_artifacts` for bounded evidence bytes) inside the same transaction, and marks the
  Loop read-only. Repeated finalization returns the existing record. The FTS index is compared with
  the table at startup and rebuilt when a restore or copy left it behind.
- **Reading a board's Loops.** `GET /boards/{id}/loops` serializes every Loop with a constant number
  of statements (documents, approvals, plans, QA cycles and progress are loaded per board rather
  than per Loop); keep it that way, because one query set per Loop is what makes the overview slow.
  Legacy imports use the same envelope with `source_kind = imported_legacy` and never create
  Tickets or approvals.

The human-facing order of a Loop is in [Onboarding](Onboarding.md#the-order-of-work-inside-a-loop).

## Ordering strategy

Lists and cards use integer `position` values spaced by 1024. Inserts target the midpoint between
neighbours; when no integer gap remains the scope is normalized to `1024, 2048, …`. This keeps
reorders O(1) writes in the common case and bounds normalization to rare, list-scoped rewrites.

## Cost of listing boards

Board counters (`loop_count`, `list_count`, `card_count`) live in each board's own database, so a
naive list would open one file per row. The registry keeps the last measurement in `board_stats`,
drops it when that board is written to, and re-measures after `TRALALA_BOARD_COUNTS_CACHE_SECONDS`:
the numbers still come from the board, but the dashboard pays for one registry read. `GET /boards`
accepts `with_counts=false` for a caller that only needs names. Measured with 100 boards: 1337 ms
with no cache, 15 ms once the counters are known, 13 ms with the flag.

## Concurrency and idempotency

- Cards carry an integer `version`. Update and move require the expected version and return
  `409 version_conflict` with the current version otherwise.
- `Idempotency-Key` on board/card creation stores a SHA-256 fingerprint plus the response. A replay
  with the same payload returns the stored response; a different payload returns `409
  idempotency_key_reused`. The worker tools reuse the same idea per tool (identical content within
  five minutes is a retry, not a second write).

## Discussion runs

A discussion is steered through *runs*. `RunService` writes a `discussion_runs` row, then either
executes one round inline (a single interactive round) or hands the loop to an in-process
`ThreadPoolExecutor` (multiple rounds or autonomous mode). The executor holds no state of its own:
the run row is the control channel, so `pause`, `resume` and `stop` are plain updates that the loop
observes between participant calls and between rounds. Nothing is queued in a broker, which keeps
the "one backend process per data directory" rule intact.

- Each round is one pass over the participants and is recorded in `discussion_rounds` with answers,
  failures, repeats, tokens and wall time. `discussion_threads.round_count` is the monotonic round
  counter for the whole thread; `discussion_runs.rounds_completed` counts rounds inside one run.
  A thread's `max_rounds` defaults to 3 and is capped at 4 — the point where a discussion either
  converged or started repeating itself — and the cap also applies to a value stored before it
  existed.
- Participants answer one after another inside a round, and each prompt carries the answers already
  given in that round. A `roundtable` thread only reaches consensus once an earlier round produced
  answers, because whoever opens a thread has read nobody.
- A position is read only from an explicit verdict: a JSON `verdict`/`position` field, a `Verdict:`
  line, or a line that holds nothing else. "I do not AGREE" therefore counts as no vote, and an
  unreadable answer abstains.
- Budgets are enforced before a round starts (accumulated time) and after every answer (tokens), so
  a runaway loop stops instead of spending the whole budget in one round. A run always has both: when
  the caller sends none, it takes `TRALALA_DISCUSSION_TOKEN_BUDGET` (default 200 000) and
  `TRALALA_DISCUSSION_TIME_BUDGET_SECONDS` (default 900), and an operator sets either to `0` to
  disable that default. The round cap bounds how many calls a question makes; the budgets bound how
  large each call may be, which is what protects the bill.
- Duplicate guard: each agent message stores `content_sha256`. When an agent repeats its previous
  answer the message and vote are not inserted again; a round with only repeats ends the run as
  `no_progress` and is never read as agreement.
- Termination is explicit: `completed` (rounds used up), `completed` with `stop_reason=consensus`,
  `stopped`, `failed` (every participant errored), `budget_exhausted` or `no_progress`. A run whose
  round was interrupted by pause/stop still records that partial round, which is why
  `rounds_completed` can advance once after a pause.
- Only one run per thread can be active; review decisions are rejected while a run is running or
  paused.
- A human message is answered automatically in `roundtable`/`autonomous` threads (one background
  round per message). A `manual` thread requires an explicit `@agents` (or participant name)
  mention or an explicit run. The message insert publishes first and the run is requested after it
  commits; a running or closed thread simply keeps the message.
- Startup reconciliation: runs left
  `running`/`paused` fail with `process_restart`, their thread `run_state` returns to `idle`,
  interrupted mention jobs fail as retryable and queued ones resume. A crash therefore never leaves
  a thread that refuses new runs, review or retry.

### Event stream

Every state change also appends a `discussion_events` row with an autoincrementing `seq` in the same
transaction, and only then fans out to in-process subscriber queues (one per open SSE connection).
Because the log is written first, a client that reconnects with `Last-Event-ID` replays what it
missed instead of trusting the socket; the endpoint subscribes *before* it replays and drops
already-seen sequence numbers, which closes the race between the two steps. Subscriber queues are
bounded and drop their oldest entry rather than blocking a worker, so a slow reader cannot stall a
run. Events are hints for the frontend: they invalidate the discussion queries, which refetch the
authoritative state, and polling remains as a fallback when `EventSource` is unavailable.

The same machinery serves ticket comments through a second scope (`card_events`, streamed by
`GET /boards/{id}/cards/{card_id}/events`). `EventService` derives the scope from the event row, so
one publish path covers both streams.

## Discussion navigation

The Discussions page loads one lightweight entry per board (`GET /discussions/overview`) and only
then the threads of the selected board. The overview aggregates `MAX(last_activity_at)`, the thread
count and the open count per board database, so ordering follows the newest post or LLM round
without shipping every thread to the browser. Boards without threads stay reachable, sorted last.
The overview is refreshed when the page opens, after a discussion is created and when the user
returns to the board list (plus a 30 s interval while the list is visible), and thread events
invalidate it.

A thread belongs to one Ticket and therefore to one Loop, so every thread records `loop_id`,
`loop_key`, `loop_name` and `ticket_key`. The thread view shows that Loop and links to
`/boards/{board_id}/loops/{loop_id}?card={card_id}`, which the Loop page opens with the Ticket
dialog already showing; closing the dialog drops the `card` parameter. Nothing infers a default
Loop from a board.

## Ticket mentions

An `@` mention in a ticket comment starts an asynchronous agent reply. `CommentService` saves the
comment first, `MentionService` resolves the mentioned names against the *enabled* registry agents
(`@[Agent Name]` is the unambiguous form the composer inserts; a bare `@Name` matches an enabled
name exactly), and queues one `comment_mention_jobs` row per agent. The job row is the status
channel (`queued` → `running` → `completed`/`failed`) and work runs on an in-process
`ThreadPoolExecutor`; no broker is introduced, exactly like discussion runs.

- The job stores a role snapshot at enqueue time, so later role-template edits cannot rewrite what
  the agent was asked.
- Context is assembled from the ticket (title, description, list, priority, due date, labels), its
  checklists and items, attachment metadata, the most recent comments and a bounded excerpt of up to
  three text-like attachments (2 000 characters each, 200 KB maximum). Binary formats stay
  metadata-only: extracting them would need a parser per format.
- A successful answer is written as a normal agent-authored comment in the same thread, and the job
  records `response_comment_id`. `uq_comment_mentions_once` (one job per comment and agent) plus the
  guarded answer insert make retry idempotent: a retry can only run a job that failed and never
  produced an answer, and a completed job refuses a retry with `409`.
- Each step publishes `agent_started`, `agent_completed` or `agent_failed` on the ticket's event
  stream; the card dialog refreshes comments and jobs from those hints. Payloads carry ids and
  counters only, so no comment text is duplicated in the event log.
- The mention autocomplete reads `GET /agents/directory`, which returns enabled agents with id,
  name and role only — connection details stay in the Settings view that needs them.

## Search

`cards_fts` (FTS5, external content over `cards`) is created when the runtime supports it; the
migration layer degrades gracefully and search falls back to `LIKE`. The search response reports
which engine answered so agents can reason about result quality.

## WebMCP and the worker surface

`getModelContext()` feature-detects `document.modelContext` / `navigator.modelContext`. Each UI
context registers only its tools through `createRegistry`, which uses an `AbortController` and
`unregisterTool` (when available) for cleanup. Tools are filtered by the authenticated actor's
scopes before registration, and every tool calls the typed REST client — never the database.

An agent outside the browser cannot see WebMCP at all, so the same capability idea has a second
transport: `POST /mcp` speaks MCP over JSON-RPC 2.0 with a bearer token and `GET /llms.txt` is the
public plain-text bootstrap that explains the product, the Loop lifecycle and the rules. Both come
from `services/agent_tools.py`, which is the one description of what a worker token may call:
thirteen tools covering reading a board, a Loop and a Ticket, assigning and moving a Ticket,
commenting, creating a Loop, writing Info, running the analysis and the RoadMap, and the three
discussion tools. The local role agents are not part of that surface: a run invokes them, they never
authenticate, and they never change a Ticket. [Agent_usage.md](Agent_usage.md) lists what each
tool may do.

## Operational notes

- Connecting an agent writes two JSON log events per attempt: `agent_probe_started`, then
  `agent_probe_finished` (info) or `agent_probe_failed` (warning) with the endpoint, model, status,
  latency, how many models the endpoint reported and the provider's reason. The key and the request
  body never appear.

- Structured JSON logs (request id, method, path, status, duration, actor, replay flag).
- `GET /api/v1/boards/{id}/validate` runs `PRAGMA integrity_check` and `foreign_key_check` and
  reports the board's `alembic_version` revision.
- `POST /api/v1/boards/{id}/migrate` retries a failed board migration (admin only) and returns
  the structured migration report.
- Backups use SQLite's online-backup API; restore snapshots the backup into the live database file,
  puts the file sidecar back under the same board lock and re-validates. A snapshot without a
  sidecar restores the database and keeps the current files, and says so in the response.
- `BackupScheduler` snapshots every active board whose newest snapshot is older than
  `TRALALA_BACKUP_INTERVAL_HOURS` (default 24, `0` disables it) and keeps the newest
  `TRALALA_BACKUP_KEEP` (default 10) per board. It runs inside the backend process and logs
  `backup_created` / `backup_failed`; files outside the snapshot pattern are never deleted.
- Docker Compose mounts a single data volume; the web container (Caddy) serves the built SPA and
  proxies `/api`, `/docs`, `/openapi.json`, `/mcp` and `/llms.txt` to the backend, adding one security
  header policy for the whole origin. TLS is configuration there rather than a second service:
  `TRALALA_SITE_ADDRESS` selects plain HTTP or automatic HTTPS, and certificates live in their own
  volume so a redeploy does not re-issue them.
- Run exactly one backend process per data directory. SQLite writes, the in-memory rate limiter and
  the per-board locks assume a single writer; horizontal scaling needs a shared coordination store.
  Startup takes an operating-system file lock on `data/.process.lock`, so an overlapping restart or
  a second container fails with an actionable message instead of racing a schema rebuild. The kernel
  releases the lock when the process exits, so no stale lock is left behind.
- Host differences live in one place: `core/platform.py` plus `TRALALA_PLATFORM_PROFILE`
  (`auto` | `windows` | `posix` | `network`). The profile decides *retry policy* — which file errors
  can clear on their own — while the mechanism that talks to the host (the lock primitive, `chmod`)
  always follows the real operating system. Windows refuses to delete a file another process holds
  open, so a board deletion or an attachment replace is retried briefly there; POSIX removes the name
  and leaves an open file alive, so it is not. Nothing outside `core/platform.py` inspects the
  operating system for file behaviour.
- A board database must stay on local disk, or on a share that implements POSIX byte-range locking.
  SQLite's WAL mode keeps a `-shm` file that assumes shared memory between processes, so a board
  directory on NFS/SMB can answer `disk I/O error` even with `TRALALA_PLATFORM_PROFILE=network`.
  That profile fixes transient removals, not WAL: a network share is for exports and backups, not for
  a live board.
- Uploads are written to a staging name and moved into place before the row that names them is
  inserted, so a crash can leave an unreferenced file but never a row whose bytes are missing.
- End-to-end tests (`frontend/e2e`) run through `scripts/run-playwright.mjs`, which reuses a local
  Playwright install and boots an isolated stack (backend `:8077`, Vite `:5273`). The commands are in
  [practical_commands.md](practical_commands.md).
