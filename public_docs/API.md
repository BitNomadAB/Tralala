# REST API

Base path `/api/v1`. Interactive documentation: `/docs`, machine description: `/openapi.json`.
Both require a session by default (`TRALALA_DOCS_REQUIRE_AUTH`) and disappear entirely when
`TRALALA_ENABLE_DOCS=false`; bearer-token agents can fetch the schema with their token.

Two more entry points live at the origin rather than under `/api/v1`:

| Path | Auth | Purpose |
| --- | --- | --- |
| `/llms.txt` | public | Plain-text bootstrap: envelope, Loop lifecycle, rules and the worker tools. Contains no ids or data. |
| `/mcp` | Bearer | The curated worker catalogue over MCP (JSON-RPC 2.0, Streamable HTTP). The tool list is filtered to the scopes the token holds. |

## Envelope

Success:

```json
{ "success": true, "data": {}, "request_id": "…", "meta": { "total": 1, "limit": 50, "offset": 0, "has_more": false } }
```

Failure (same shape for every status):

```json
{
  "success": false,
  "error": { "code": "version_conflict", "message": "…", "retryable": false, "details": { "current_version": 3 } },
  "request_id": "…"
}
```

Error codes: `unauthorized`, `invalid_credentials`, `invalid_session`, `invalid_token`,
`token_revoked`, `token_expired`, `forbidden`, `csrf_failed`, `not_found`, `conflict`,
`version_conflict`, `board_archived`, `board_migration_failed`, `board_schema_outdated`,
`board_files_busy`, `board_import_invalid`, `board_backup_invalid`, `board_database_unreadable`,
`idempotency_key_reused`,
`creation_in_progress`, `creation_failed`,
`validation_failed`, `payload_too_large`, `rate_limited`, and the Loop workflow codes
`loop_not_found`,
`loop_required`, `loop_mismatch`, `loop_read_only`, `document_stale`, `approval_required`,
`human_action_required`, `invalid_dependency_graph`, `ticket_blocked`, `ticket_waiting`,
`ticket_completed`, `plan_change_required`,
`generation_input_changed`, `generation_unavailable`, `generation_in_progress`, `qa_incomplete`.

Human-only decisions (analysis approval, RoadMap approval, confirming a human-only Ticket,
clearing a Ticket's wait, accepting QA and finalizing a Loop) reject agent tokens with `403 human_action_required` even when
the token holds the scope. Info is the exception on purpose: a worker may write it while the Loop is
still `draft` or `analysis_review`, because that is the intent it agreed with its person; once
planning has started the edit is refused the same way.

## Authentication

| Method | Use case | Transport |
| --- | --- | --- |
| Session cookie | React UI | `tralala_session` (HttpOnly, SameSite=Lax) + `tralala_csrf` double-submit |
| Bearer token | Agents, scripts | `Authorization: Bearer trl_…` |

Cookie-authenticated `POST/PATCH/DELETE` require `X-CSRF-Token` equal to the `tralala_csrf` cookie.
Bearer clients are exempt (no ambient credentials).

Session cookies are signed with a per-install secret. When `TRALALA_SECRET_KEY` is unset, a random
secret is generated once at `<data>/.session-secret` (owner-only permissions); the published
default is never used.

```powershell
# login
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/auth/login `
  -ContentType application/json -Body '{"username":"admin","password":"…"}'

# agent call
Invoke-RestMethod http://localhost:8000/api/v1/boards -Headers @{ Authorization = "Bearer trl_…" }
```

Scopes: `boards:read`, `boards:write`, `boards:admin`, `cards:read`, `cards:write`,
`comments:write`, `agents:read`, `agents:write`, `agents:admin`, `discussions:read`,
`discussions:write`, `discussions:admin`, `discussions:vote`, `credentials:admin`, `users:admin`.

A session's scopes come from its account role and nothing is implicit. `admin` holds every scope;
`member` holds every scope except `users:admin` and `credentials:admin`, so everyone signed in works
with boards, agents and discussions, while only administrators manage accounts and the global API
keys. API tokens may hold every scope except `credentials:admin` and `users:admin`.

## Endpoints

### System

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | Liveness |
| GET | `/meta` | API version, `scopes`, `token_scopes` (the subset a token may hold), `member_token_scopes` and `member_token_limits` (what a person may grant themselves), feature flags, and for an administrator only `bootstrap_password_file_present` (authenticated) |

### Auth and credentials

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/auth/login` | public; throttled per username and client address |
| POST | `/auth/enrol` (`{"token","password"}`) | public; claims an invitation link, sets the password and starts a session |
| POST | `/auth/logout` | authenticated; revokes the stored session |
| POST | `/auth/password` | authenticated user; revokes every session. A wrong `current_password` is `422 invalid_credentials` and the session stays; a token gets `403 forbidden` |
| GET | `/auth/me` | authenticated; returns `role`, effective `scopes` and the account's `preferences` |
| GET | `/auth/scopes` | authenticated; the caller's effective scopes |
| GET | `/auth/preferences` | signed-in account; `theme_mode` and `theme_kit` (null when unset) |
| PUT | `/auth/preferences` | signed-in account; partial update of `theme_mode` / `theme_kit` |
| GET | `/users` | `users:admin`; includes `agent_access_count` and `agent_access_last_used_at` per account |
| POST | `/users` (`{"name","password","role"}`) | `users:admin` |
| PATCH | `/users/{id}` (`{"role","disabled"}`) | `users:admin`; the last administrator is protected. `disabled: true` also revokes every token that account issued |
| POST | `/users/{id}/password` (`{"new_password"}`) | `users:admin`; revokes the user's sessions |
| POST | `/users/{id}/invite` (`{"expires_in_hours"}` optional, default 72) | `users:admin`; returns a one-time enrolment token once |
| GET | `/credentials` | signed-in person; own access, or every token with `credentials:admin` (`?owner_id=` narrows it) |
| GET | `/credentials/mine` | signed-in person; their own access whatever their role |
| POST | `/credentials` | signed-in person, never a token (`403 human_action_required`); an admin may grant any grantable scope, a member only `member_token_scopes` |
| POST | `/credentials/{id}/rotate` | the owner or `credentials:admin`, as a signed-in person, never a token (`403 human_action_required`); issues a new token and revokes the old one |
| POST | `/credentials/{id}/revoke` | the owner or `credentials:admin` |

A token is a person's **interaction agent access**: it is created as its own `agent` actor, records
`owner_actor_id`, and is shown once. An administrator may grant any scope a token can hold. A member
may only grant `member_token_scopes` (published by `GET /meta`), is capped at
`TRALALA_MEMBER_TOKEN_LIMIT` live tokens, must give an expiry (default 30 days,
`TRALALA_MEMBER_TOKEN_DEFAULT_DAYS`, never beyond `TRALALA_MEMBER_TOKEN_MAX_DAYS`), and may rotate or
revoke only their own. Asking for a grantable but non-member scope is `422 forbidden_scope`; asking
for one no token may hold is `422 validation_failed`; the cap answers `409 agent_access_limit` and a
missing expiry `422 expiry_required`.

An invitation link is the recommended way to hand over an account: the administrator creates the
user, `POST /users/{id}/invite` returns a token that is stored only as a hash, and the link
(`/enrol?token=...`) sets the person's own password. It is single use, expires
(`TRALALA_INVITE_TTL_HOURS`), replaces any unused earlier link, and answers `invite_invalid`,
`invite_used` or `invite_expired` without revealing whether a token existed. Tralala sends no e-mail;
the operator delivers the link.

A `401` means the request is not authenticated: no session or token, or one that has expired or
been revoked. The web client takes it as the end of its session and shows the sign-in page, which is
why a mistyped current password on `POST /auth/password` answers `422`, not `401`.

Logins are rate limited per client address and backed off per username after repeated failures
(`429 rate_limited` with `details.retry_after_seconds`). Passwords must be at least
`TRALALA_PASSWORD_MIN_LENGTH` characters (default 8) and are never accepted when they equal the
username.

### Boards

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards?q=&status=&sort=&order=&limit=&offset=&with_counts=` | `boards:read` |
| POST | `/boards` (`Idempotency-Key` supported) | `boards:write` |
| GET | `/boards/{board_id}` | `boards:read` |
| PATCH | `/boards/{board_id}` | `boards:write` |
| POST | `/boards/{board_id}/archive` (also when the board's database cannot be opened, so it can be deleted) | `boards:write` |
| POST | `/boards/{board_id}/restore` | `boards:write` |
| POST | `/boards/{board_id}/duplicate` | `boards:write` |
| DELETE | `/boards/{board_id}` (body `{"confirm_name": "…"}`, board must be archived) | `boards:admin` |
| GET | `/boards/{board_id}/export` | `boards:write` — `application/zip` |
| POST | `/boards/import` (raw zip body) | `boards:admin` |
| GET | `/boards/{board_id}/validate` | `boards:read` |
| POST | `/boards/{board_id}/migrate` (retry a failed schema migration) | `boards:admin` |
| GET | `/boards/{board_id}/actors` (`people` to assign, `agents` to ask) | `boards:read` |
| GET/POST | `/boards/{board_id}/backups` | `boards:read` / `boards:write`; each item reports `has_attachments` and `attachments_size_bytes` |
| POST | `/boards/{board_id}/backups/{name}/restore` (verifies the backup, then restores the database **and** its files) | `boards:admin` |

A snapshot is a pair: `backup-<UTC>.sqlite` plus, when the board has uploaded files,
`backup-<UTC>-attachments.zip`. Restoring replaces both, and pruning removes the pair together. A
snapshot from before this existed has no sidecar: the database is restored, the board's current files
are kept, and the restore response says exactly that — `attachments.skipped` is `true`,
`attachments.reason` is `snapshot_has_no_file_archive`, and a top-level `warning` explains it.

Before a restore touches the board, the snapshot is read as a file of unknown origin (read only,
nothing written beside it) and must pass SQLite's `integrity_check` and then its `foreign_key_check`.
One that fails is refused with `422 board_backup_invalid` and the board keeps its database:
`details.name` is the snapshot, `details.reason` is `not_a_database`, `integrity_check_failed` or
`foreign_key_check_failed`, and `details.detail` carries SQLite's answer (the first 20 findings or
rows, and how many more there are). The restored board is checked once more, and that report is the
response's `verification`.

Deleting a board removes its database, its uploaded files and its backups before the registry row, so
an interrupted delete leaves a board that can be deleted again. When the host will not release a file
(Windows, or a share), the removal is retried briefly and then answered with
`409 board_files_busy`, naming the leftover directory in `details.leftover` together with `errno`,
`winerror` and `platform_profile`; the board and its data are untouched.

`POST /boards/import` judges the archive's `board.sqlite` before anything uses it. The file is opened
read only as a file of unknown origin, so nothing stored in it runs; SQLite's `integrity_check` runs
first, then the board's tables and its schema revision must be ones this release can migrate. A file
that fails is refused with `422 board_import_invalid`: `details.reason` is `not_a_database`,
`integrity_check_failed`, `not_a_board_database`, `unknown_schema_revision` (an archive from a newer
release) or `migration_failed` (the upgrade to the current schema failed), and `details.detail`
carries SQLite's answer. A refused or failed import leaves nothing behind: no board row, no files and
no pre-migration snapshot. An archive from an older release is migrated during the import.

A board whose database file SQLite cannot read (not a database, or damaged) never fails the board
list or startup. The list shows it with zero counters and its status, startup skips its interrupted
work, and each logs `board_database_unreadable` once with the board id. A request that opens the board
answers `503 board_database_unreadable` (not retryable), with `details.sqlite_error` naming SQLite's
code.

Snapshots are also taken automatically: `BackupScheduler` checks every active board and snapshots any
whose newest `backup-<UTC>.sqlite` is older than `TRALALA_BACKUP_INTERVAL_HOURS` (default 24, `0`
disables it), then prunes all but the newest `TRALALA_BACKUP_KEEP` (default 10). It runs in the
backend process (one process per data directory) and logs `backup_created` / `backup_failed` with the
board id; files that do not match the backup pattern are never deleted.
| POST | `/boards/{board_id}/templates` (`{"name","description"}`; snapshots the board's lists and labels) | `boards:write` |

`POST /boards` accepts an optional `template_id`. When present, the template's description, list
names and labels are applied; an explicit `description` or `lists` in the payload wins. A missing
template is rejected with `422 validation_failed` before any board row is written, so an
`Idempotency-Key` can be reused after correcting the request.

`POST` and `PATCH /boards` accept `repository_ids: [uuid]`: the set of repositories the board is
about. The list replaces the board's previous selection (an empty list detaches every repository);
an unknown id is rejected with `404 repository_not_found` before anything is written. A *Git over
HTTPS* repository that no board links any more loses its mirror (deleting a board counts too); the
next board that links it clones it again. Every `BoardOut` carries `repository_ids`, which is what
the create/edit dialogs show as checkboxes.

Beside it, `repository_paths` steers what a run's snapshot reads of each linked repository:
`{"<repository_id>": {"focus_paths": ["docs/**"], "exclude_paths": ["docs/archive/**"]}}`. With focus
paths only the files one of them matches are read; a file an exclude path matches is never read, even
when a focus path matches it too; a repository without an entry (or with both lists empty) is read
whole. The globs choose among the files the snapshot would read anyway (build output, dependencies,
lock files, binaries and images stay skipped) before the usual order and caps apply, so the 200 files
and the context budget go to what the board asked for. They are matched with Python's `fnmatchcase`
against the path below the repository root (`docs/guide.md`): case sensitive, and `*` also matches
`/`, so `docs/*` covers every file below `docs/` and `*.md` every Markdown file at any depth. Each list
holds at most 20 globs of at most 200 characters; an empty glob, an absolute path (a leading `/` or a
drive letter), a `..` segment or a backslash is refused with `422 validation_failed` and the `loc` of
the offending glob (`repository_paths.<repository_id>.focus_paths.<index>`). A key that is not among
the board's repositories answers `422 validation_failed` with `details.field: "repository_paths"`.
On `PATCH`, `repository_paths` replaces the globs of every linked repository; leaving it out keeps the
globs of each repository that stays linked, so a client that only sends `repository_ids` loses
nothing, and sending it without `repository_ids` keeps the selection. `BoardOut.repository_paths`
lists the repositories that have globs. A run's snapshot entry repeats the `focus_paths` and
`exclude_paths` it was read with, so the analysis knows it saw part of the repository.

The same pair applies to `agent_ids`: the agents that work on that board. An empty list means "any
enabled agent", a non-empty list is enforced at generation time — a run may only use an agent the
board lists (`422 agent_not_on_board`), and the default pick prefers a board agent. An unknown id is
rejected with `404 agent_not_found` before anything is written.

A Loop can narrow that further per purpose: `PUT …/loops/{loop_id}/agents` stores
`analysis_agent_id`, `roadmap_agent_id` and `qa_agent_id`, which seed the default of the next run
(`Default (<agent name>)` in the dialog). A run's explicit `agent_id` still wins, and a stored agent
that the board dropped or that was deleted falls back to the board default instead of failing.

### Loops

A Board is a container of Loops. A Loop owns its Kanban columns, Tickets and the five planning
document slots; there is no Board-level Kanban.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/boards/{board_id}/loops` | `include_completed`, `include_archived`, `stage` filters |
| POST | `/boards/{board_id}/loops` | Creates the Loop with its own columns and five empty documents; accepts `Idempotency-Key` |
| GET/PATCH | `/boards/{board_id}/loops/{loop_id}` | `PATCH` requires the Loop `version` |
| POST | `/boards/{board_id}/loops/{loop_id}/cancel` | Human-only; records `cancelled_at` |
| POST | `/boards/{board_id}/loops/{loop_id}/archive` | Hides the Loop from active views |
| GET | `/boards/{board_id}/loops/{loop_id}/documents` | Current and approved revisions per kind |
| GET | `/boards/{board_id}/loops/{loop_id}/documents/{kind}/revisions` | Revision history |
| PUT | `/boards/{board_id}/loops/{loop_id}/documents/info` | Human-only; new immutable revision |
| POST | `/boards/{board_id}/loops/{loop_id}/candidates` | Submits an analysis or RoadMap candidate; validation only, never approval. `expected_info_revision_id` / `expected_analysis_revision_id` answer `409 document_stale` when that document changed; a token gets `403 human_action_required` while the scope's approval is current. An optional `analysis_brief` or `roadmap_brief` is stored as the human view (`422 brief_rejected` when it breaks a rule); without one the answer adds `human_view`: the run that writes the brief for people, or `skipped` with the reason |
| POST | `/boards/{board_id}/loops/{loop_id}/briefs` | `{kind, brief, expected_revision_id?}`: the brief for people of the current `analysis_ai` or `roadmap_ai`, stored as the `analysis` or `roadmap` revision. It approves nothing; a token gets `403 human_action_required` while the scope's approval is current, a person never; `409 document_stale` when `expected_revision_id` is no longer current; `422 brief_rejected` names every problem |
| POST | `/boards/{board_id}/loops/{loop_id}/reviews/analysis` | Human-only decision bound to exact revision ids; `409 generation_in_progress` while the analysis's brief is being written for people (the RoadMap's review likewise) |
| POST | `/boards/{board_id}/loops/{loop_id}/reviews/roadmap` | Human-only; publishes the plan atomically |
| POST | `/boards/{board_id}/loops/{loop_id}/reviews/{scope}/reset` | Human-only; clears the scope's documents and supersedes any approval behind them |
| GET | `/boards/{board_id}/loops/{loop_id}/plan` | Active plan with phases and readiness |
| GET | `/boards/{board_id}/loops/{loop_id}/agents` | The agent this Loop prefers per purpose |
| PUT | `/boards/{board_id}/loops/{loop_id}/agents` | Sets that preference (`boards:write`; omitted field keeps its value, `null` clears) |
| GET | `/boards/{board_id}/loops/{loop_id}/readiness` | Machine-readable blockers and human gates |
| GET/POST | `/boards/{board_id}/loops/{loop_id}/notes` | The Loop's notes, oldest first (`limit` 1..200, `before` a note id); add one (`loops:write`, at most 20 000 characters, the same note from the same actor within five minutes answers the first) |
| GET | `/boards/{board_id}/loops/{loop_id}/context` | Bounded, versioned context plus output schemas |
| POST | `/boards/{board_id}/loops/{loop_id}/generation-runs` | Starts an analysis, RoadMap or QA run (`202`), or `analysis_human` / `roadmap_human`: the brief for people from the current `analysis_ai` or `roadmap_ai` (`409 approval_exists` while that scope is approved); `Idempotency-Key` supported |
| GET | `/boards/{board_id}/loops/{loop_id}/generation-runs[/{run_id}]` | Durable run state and failures |
| POST | `/boards/{board_id}/loops/{loop_id}/generation-runs/{run_id}/cancel` | Cancels a queued or running run |
| POST | `/boards/{board_id}/loops/{loop_id}/generation-runs/{run_id}/retry` | Starts a new run with the same inputs |
| POST | `/boards/{board_id}/loops/{loop_id}/completion` | Human-only implementation acceptance and QA outcome |
| GET | `/boards/{board_id}/loops/{loop_id}/qa` | Active or latest QA cycle with both instruction views |
| PUT | `/boards/{board_id}/loops/{loop_id}/qa/instructions` | Supplies a scenario set (human or agent) |
| POST | `/boards/{board_id}/loops/{loop_id}/qa/results` | Records scenario outcomes; agents may submit |
| POST | `/boards/{board_id}/loops/{loop_id}/qa/decision` | Human-only acceptance; finalizes atomically |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/confirm` | Human-only confirmation of a human Ticket |
| GET | `/boards/{board_id}/tickets` | Explicit Board-level aggregate read; each row names its Loop |
| GET | `/boards/{board_id}/history` | History search (`q`, `source_kind`, `loop_key`, `qa_status`, dates) |
| GET | `/boards/{board_id}/history/{history_id}` | Immutable record with its envelope and artifacts |
| POST | `/boards/{board_id}/history/import` | Legacy envelope ingestion; never creates Tickets |

Ticket keys look like `AC004-DA02-003`: Loop prefix and Board-local Loop sequence, Phase prefix and
number, then the Ticket sequence within that Phase. They are allocated by the server, frozen after
allocation and unique within the Board.

#### Generation run steps

Every generation run answers `trace`, its process tree: one step per event, written to the run as it
happens (best effort, like `phase`), so a caller that polls `GET …/generation-runs/{run_id}` sees it
grow. The run list and every other answer that carries a run include it; a run recorded before the
trace existed answers `[]`. Each step is an object:

| Field | Value |
| --- | --- |
| `stage` | `documents`, `repository`, `writing`, `checking` or `saving`, in the order a run reaches them; a QA run has no `repository` stage |
| `kind` | `step`, `tool` (a tool call), `note` (the model's own words beside a call), `repair` (an answer sent back), `limit` (a limit the run reached) or `error` |
| `text` | One plain-language sentence, at most 500 characters (a `note` at most 1 000) |
| `at` | When the step happened, ISO 8601 UTC |
| `tool` | A tool call only: `list_files`, `read_file` or `search` |
| `arguments` | A tool call only: its scalar arguments, text cut to 200 characters |
| `answer` | A tool call only: `summary` (one sentence), `chars` (the answer's size), `files_read`, `lines` (`[first, last]` or `null`), `entries`, `matches`, `truncated` and `error` (a code such as `not_found`, or `null`) |

No step holds a file's content or the model's answer, and a run records at most 1 000 steps. The
`generation_run_finished` log line carries `tool_calls` and `files_read` (the distinct files
`read_file` returned) from the same steps. How a run reads the repositories, and so which steps it
takes, is described under [Role templates](#role-templates) and in
[Repositories.md](Repositories.md#how-a-run-reads-the-code).

### Board templates

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/templates` | `boards:read` |
| POST | `/templates` (`{"name","description","lists",["labels"]}`) | `boards:write` |
| GET | `/templates/{template_id}` | `boards:read` |
| PATCH | `/templates/{template_id}` | `boards:write` |
| DELETE | `/templates/{template_id}` | `boards:admin` |

Templates live in `registry.sqlite`, not in a board database: they are selected before the board
exists. Names are unique (case-insensitive); duplicates return `409 template_name_taken`. Empty
`lists` fall back to the configured default lists when a board is created.

### Role templates

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/role-templates` | `agents:read` |
| POST | `/role-templates` (`{"name","description","system_prompt"}`) | `agents:write` |
| GET | `/role-templates/{id}` | `agents:read` |
| PATCH | `/role-templates/{id}` | `agents:write` |
| POST | `/role-templates/{id}/duplicate` (`{"name"}` optional) | `agents:write` |
| POST | `/role-templates/{id}/restore-defaults` (built-in only) | `agents:admin` |
| DELETE | `/role-templates/{id}` (custom only) | `agents:admin` |

Twelve built-in roles are seeded on startup from `backend/app/seeds/role_seeds.json`
(`lead_developer`, `project_manager`, `product_owner`, `backend_developer`, `frontend_developer`,
`qa_engineer`, `security_engineer`, `ux_designer`, `customer`, `analytics_agent`, `coordinator`,
`architect`). Built-ins carry `built_in: true` and a factory copy of their prompt, so edits are
reversible. `customized` is true while `system_prompt` differs from the factory text. On startup an
unedited built-in follows a rewritten factory prompt, so prompt improvements reach an existing
installation; a customized built-in keeps its own text and only its factory copy moves, which is what
`restore-defaults` restores.

A role prompt describes a job, never one particular board, Loop or installation: the identifiers an
agent works on (the Loop name and key, the ticket title and id, the board, the readable repositories)
are supplied in the request that asks it to work. Prompts must therefore not hard-code a product or
subject name.
The agent's role prompt is the first part of every Loop generation prompt, followed by the purpose
contract and the JSON schema, and the whole composed text is what a run snapshots.

An analysis or RoadMap run also reads the board's repositories: for every enabled repository linked
to the board, Tralala resolves the commit at the configured branch and reads the tarball for that
commit. A `github` repository is downloaded from `api.github.com`/`codeload.github.com` (15 s
timeout); a `git_https` repository is fetched into its Tralala-managed mirror first and archived
there (see [Repositories.md](Repositories.md)). Either archive is at most
`TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES` (default 128 MiB); a larger one is `too_large`. How the model
sees the code depends on the agent: an OpenAI-compatible agent whose last connection test found tool
calling (`supports_tools`) reads it itself through read-only tools (below); every other agent, A2A
included, gets a **repository snapshot**.

The snapshot places a bounded, filtered set of files in the prompt as data — never as instructions.
The documents come first; the repositories share what remains of `TRALALA_GENERATION_CONTEXT_CHARS`
(default 400 000 characters), in link order with carry-over, and each snapshot is cut to its share.
The fixed caps still apply: at most 200 files and 200 KB of text per repository; a file that does
not fit is left out and the next one is read. Each entry also carries `manifest`, every file the
snapshot considered in the order it read them as `{path, bytes, sent}` (at most 5 000, with
`manifest_omitted` counting the rest), so the model knows that a file it was not sent exists; the
manifest takes its room of the repository's share before the files do. Build output, dependencies,
lock files, binaries and images are skipped.

A run whose agent reads with tools gets the Loop's documents, each repository's name, commit and file
count, the list of files it can read, and three tools: `list_files(path?, glob?)`,
`read_file(path, start_line?, end_line?)` and `search(pattern, glob?, regex?)`, answered from an
in-memory index of the commit's archive with the same filters. Every path starts with the repository
name. The model calls them as often as it needs, and the run ends when it answers without a tool
call; that answer gets the same schema check and up to two repair rounds. `response_format` is not
sent beside the tools, because a provider that holds the answer to a schema can no longer call a
tool; the prompt and the repair rounds hold the answer to it instead. Three settings bound the
conversation: `TRALALA_GENERATION_TOOL_STEPS` (default 60) tool calls per run, after which the model
is asked for its answer with `tool_choice: "none"`; `TRALALA_GENERATION_TOOL_RESULT_CHARS` (default
60 000) characters per tool answer, so a long file comes in parts; and
`TRALALA_GENERATION_CONTEXT_CHARS` for the whole conversation, which sets the oldest tool answers
aside first. A provider that refuses the tools on the first call (an error starting
`tools_refused`) gets the snapshot of the archives the run already fetched instead, and so does a
run in which no repository could be read. [Repositories.md](Repositories.md#how-a-run-reads-the-code)
describes the tools, the workspace's bounds and the fallbacks.

A repository that cannot be read does not fail the run: it appears in the snapshot as
`{id, name, error}` with a class such as `unauthorized`, `not_found`, `rate_limited`, `too_large` or
`timeout`, and the analysis is expected to say which part of the code it did not see. The run record
keeps the commit and the file paths (`source_revisions.repositories`); the file contents stay in the
run's own input, and `GET …/generation-runs/{run_id}` returns only the name, branch, commit,
file count and `truncated` flag, plus `budget_chars` (the repository's share),
`snapshot_chars_included` (what its manifest and files took) and `content_omitted` (not even one
file fitted); the manifest stays in the run's own input as well. A
`git_https` entry also carries `provider`, `fetched_at` (when its mirror was last brought up to date)
and `stale_mirror`: `true` when this run's fetch failed and it read the last good mirror from
`fetched_at`. An entry of a run whose model read through tools carries `reading: "tools"`,
`file_count` (the files the model could read), `left_out` (the files past the workspace's bounds:
too large, or beyond its 20 000 files or 64 MiB of text) and `truncated` (`left_out` above 0), and no
budget fields; a snapshot entry has no `reading`. No token, path or content ever appears in a log
line or an error.

Every run also reports `phase` — `reading_info`, `analysing_repository` or `generating` — the step it
last reached, so a caller can show progress instead of one opaque wait. When a run fails, `phase`
names the step that failed alongside `error_code` and `error_message`; the dialogue shows that step
with the error as JSON rather than a toast that scrolls away. `source_revisions.repositories` is
written as soon as the repository step finishes, so a caller can tell "nothing is linked" (`[]`) from
"the step has not run yet" (no key) — a fast run is then never mistaken for one that read the code.
Beside `phase`, every run answers `trace`, the steps it took (see
[Generation run steps](#generation-run-steps)).

Resetting a scope (`POST …/reviews/{scope}/reset`, `{version}`) is the counterpart of approving and
equally human-only. It clears the scope's documents — writing an empty draft revision chained to its
real inputs — and supersedes any approval behind them, keeping the row as history. It works on a
draft that was never approved as well as on an approved one, and returns
`{scope, approval_id, cleared, version}` with `approval_id: null` when there was nothing approved.
`409 nothing_to_reset` means the scope is already empty; `409 document_empty` refuses to approve a
blank document, which is what a reset leaves behind.

`scope` says where a profile works. `board` profiles answer inside one board; `organisation`
profiles (`coordinator`, `architect`) work across the whole installation and cannot be selected as
board agents — `agent_ids` on a board rejects them with `422 agent_scope_organisation`. Their input
is the registry itself: `GET /boards`, `GET /repositories` and the Loop overview endpoints, and the
Architect expects one read-only token that reaches every repository. Custom templates copy the scope
of the template they came from.

### Repository credentials

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/repositories?board_id=&unassigned=` | `boards:read` |
| POST | `/repositories` | `boards:admin` |
| GET | `/repositories/{id}` | `boards:read` |
| PATCH | `/repositories/{id}` | `boards:admin` |
| POST | `/repositories/{id}/check` | `boards:admin` |
| POST | `/repositories/{id}/mirror/rebuild` (`git_https`) | `boards:admin` |
| POST | `/repositories/{id}/mirror/remove` (`git_https`) | `boards:admin` |
| DELETE | `/repositories/{id}` | `boards:admin` |

Repositories are a registry-level list, managed from **Settings -> Repositories**
(`/settings/repositories`). A repository is never owned by a board: boards select the ones they are
about with `repository_ids`, so one repository can serve several boards and a board can list several
(it resolves to `board_repositories`). The token is a read-only access token for that repository
(for GitHub, a fine-grained personal access token with `Contents: read`); it is sealed with the same
mechanism as provider keys, returned only as `has_token`/`token_hint`, never logged, and re-sealed
when the session secret rotates. For a `github` repository `check` reports `ok`, `unauthorized`,
`not_found`, `forbidden`, `branch_missing` or `unreachable` and stores the last outcome on the record.

`POST /repositories` takes `provider`: `github` (the default) reads a `github.com` repository through
the GitHub API; `git_https` keeps a Tralala-managed mirror of any `https` URL on a host listed in
`TRALALA_REPOSITORY_HOSTS` and fetches its main branch before every run. A `git_https` URL on another
host is refused with `422 host_not_allowed`, at create, on a URL change and before every fetch; a URL
with credentials, a query or a fragment with `422 validation_failed`. The provider cannot be changed
later. For a `git_https` repository:

- `check` runs `git ls-remote` only (no clone) and stores the remote's main branch as
  `default_branch`; it reports `ok`, `branch_missing`, or a mirror code such as `auth_failed`,
  `not_found`, `timeout` or `git_missing`.
- The entry carries `default_branch`, and for an administrator the mirror's last good fetch
  (`last_sha`, `fetched_at`, `mirror_bytes`) and `mirror_error`: why the last fetch failed, or
  `mirror_cleanup_failed`.
- `DELETE` removes the mirror in the same operation. When the host still holds a file in it, the
  repository is kept, `mirror_error` becomes `mirror_cleanup_failed` and the answer is
  `409 mirror_cleanup_failed` (with `details.leftover`, e.g. `repos/<id>`).
- `mirror/rebuild` removes the mirror so the next run clones it again; `mirror/remove` is the same
  removal, the retry after `mirror_cleanup_failed`. Both answer the repository with its mirror fields
  cleared, `409 mirror_cleanup_failed` when the removal fails again and
  `409 repository_not_mirrored` for a `github` repository.

[Repositories.md](Repositories.md) is the operator's guide: the procedure, the layout under
`<data>/repos/`, the settings, stale mirrors, tokens for other hosts and troubleshooting.

`GET /repositories` and `GET /repositories/{id}` are readable with `boards:read`, but a caller without
`boards:admin` gets the entry without `token_hint`, `last_checked_at`, `last_check_status`,
`last_check_detail`, `last_sha`, `fetched_at`, `mirror_bytes` and `mirror_error`: the list stays
usable for board dialogs while credential hints, access-check history and the mirror's state remain
administration detail.

The dialog carries the same recipe for an operator, and it can be followed before the repository
exists: GitHub -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens,
*Only select repositories* (this one), *Repository permissions* -> **Contents: Read-only**, short
expiry. A token is issued by GitHub, never generated locally. Verify it on the machine before pasting:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/<owner>/<repository>
```

`200` means it works, `401` that it is wrong or expired, `404` that it cannot see the repository. An
SSH deploy key (`ssh-keygen`) grants a *git client* read access over SSH; Tralala reads GitHub's REST
API, and a `git_https` mirror fetches over HTTPS only, so a deploy key is not an alternative for this
field.

### Agents

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/agents?q=&enabled=` | `agents:read` |
| GET | `/agents/directory` (enabled agents: id, name, role only) | `agents:read` |
| POST | `/agents` | `agents:write` |
| GET | `/agents/{id}` | `agents:read` |
| PATCH | `/agents/{id}` (`clear_api_key: true` removes the stored key) | `agents:write` |
| POST | `/agents/{id}/duplicate` | `agents:write` |
| POST | `/agents/{id}/test` (optional unsaved overrides) | `agents:write` |
| POST | `/agents/test` (test a configuration that is not saved; nothing is written) | `agents:write` |
| DELETE | `/agents/{id}` | `agents:admin` |

An agent needs either `role_template_id` or `role_prompt_override`. `connection_type` is
`openai_compatible` or `a2a`. Base URLs are validated: `http`/`https` only, no embedded
credentials, no cloud-metadata or link-local targets (a host name is judged by every address it
resolves to), no redirect following; private/loopback targets, `[::1]` included, are allowed because
local model servers are the primary use case (`TRALALA_AGENTS_ALLOW_PRIVATE_ENDPOINTS`). The same
rule is checked again when a call or a connection test connects, and the connection goes to the
checked address only; a refused address is reported as `ForbiddenAddressError`.

`timeout_seconds` defaults to 180 and may be at most 900: a reasoning or local model can need minutes
for a structured answer, and a call that runs out of time fails with "No answer within N s (the
agent's timeout setting)". A connection test waits at most 30 s per call whatever the agent's
timeout, and says so when the model does not answer in time. `max_output_tokens` (at most 2 000 000)
and `temperature` are sent only when set; empty leaves both to the provider's default, which avoids
the providers that refuse an answer length above their own cap or any temperature at all.

API keys are sealed with Fernet (HKDF-derived from the install secret). Responses expose only
`has_api_key` and a `••••ab12` hint — never the key itself. `/agents/directory` is the autocomplete
projection: enabled agents with `id`, `name` and role only, no endpoint, model or credential hint.

`POST /agents/test` takes the same body and does the same work without an agent row, so a form can
prove a connection before it saves one. Nothing is written on success or failure: `last_test_*` stays
untouched because there is nothing to touch.

Both test endpoints accept `no_api_key: true`, which means "call this endpoint without a credential".
That is different from omitting `api_key`, which means "use the one already stored on this agent": a
model on your own network usually wants no key at all, and the stored one must not silently travel
with the request. With no key there is no `Authorization` header in any call, probe or generation.

`POST /agents/{id}/test` probes `GET {base_url}/models` for OpenAI-compatible endpoints and the A2A
agent card (`/.well-known/agent.json`) for `a2a`, then records `last_test_status`,
`last_test_message` and `last_tested_at`. When an OpenAI-compatible agent has a model, the probe
also sends **one real chat completion** (`max_tokens: 16`, no `temperature`) and reports it as
`completion`. The model list proves the endpoint answers; only the completion proves that the model
name exists and that the parameters a generation sends are accepted, which is the difference between
a green test and a run that fails with `400`. A refused completion fails the test and carries the
provider's own sentence, while `models` still comes back so the form can offer the names the
endpoint knows.

That completion first asks for a JSON schema as the answer's format (`response_format` with
`type: json_schema`). When the model answers it, the result says `supports_json_schema: true` (on
the outcome and on `completion`), and testing a saved agent records it on the agent
(`supports_json_schema` in `GET /agents/{id}`). A provider that refuses the request (any `4xx`) is
asked once more without it, so the test still says whether the model itself works, and the agent is
recorded without it. Every test writes the flag afresh; a test without a model call, or one that
fails, leaves it `false`. Analysis, RoadMap and QA generations send the purpose's schema only to an
agent with the flag set, so the provider keeps the answer to the schema instead of the repair round
catching it afterwards; a provider that refuses it after all (a `400` that names `response_format`)
is asked once more without it, and the generation goes on as before.

When that completion answers, the test makes **one more small call** to find out whether the model
calls tools. It offers a single dummy tool, `report_ok` (no arguments), with `tool_choice: "auto"`
and a message that asks the model to call it, within the same 30 s limit per call and with room for
a model that reasons first (`max_tokens: 512`). Only an answer that calls `report_ok` counts: the
result then says `supports_tools: true` (on the outcome and on `completion`), and testing a saved
agent records it on the agent (`supports_tools` in `GET /agents/{id}`; Settings lists such an agent
as "reads repositories with tools", a tested agent without it as "no tool calling"). A text answer,
a refusal, an answer that is not a completion or no answer in time records `false` and never fails
the test. Like `supports_json_schema`, every test writes the flag afresh, a duplicate starts
without it, and an A2A agent never has it. Tools are only ever offered to a model whose agent has
the flag set; a provider that refuses them after all (a `400` or `422` that names the tools) is not
asked again, and the call's error starts with `tools_refused`. An analysis or RoadMap run on an
agent with the flag lets the model read the board's repositories itself instead of sending a
snapshot (see [Role templates](#role-templates)). Editing an agent leaves the flag as it is, so test
again after changing its model or endpoint.

Both endpoints write a pair of structured log events per attempt — `agent_probe_started` and then
`agent_probe_finished` or `agent_probe_failed` (a warning) — carrying the endpoint, the model, whether
a key was used, the status, the latency, how many models were reported, whether the model calls
tools and, on failure, the reason cut to 200 characters. The key itself and the request body never
appear.

**Role snapshot rule:** `role_templates` and `agents` are separate resources. Editing a template
changes *future* work; every discussion persists `AgentService.role_snapshot(...)` (template id and
name, template `updated_at`, effective prompt, SHA-256, timestamp) so history stays explainable.
Editing a template therefore changes future work and never rewrites a past discussion.

### Discussions

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/discussions/overview` (one entrance per board, newest discussion activity first) | `boards:read` + `discussions:read` |
| GET | `/boards/{board_id}/discussions?status=&limit=` | `discussions:read` |
| POST | `/boards/{board_id}/discussions` | `discussions:write` |
| GET | `/boards/{board_id}/discussions/{id}` (participants, messages with their answers, positions, synthesis, votes, runs) | `discussions:read` |
| POST | `/boards/{board_id}/discussions/{id}/messages` | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/start` (runs one round inline by default) | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/runs` (`202`, always background) | `discussions:write` |
| GET | `/boards/{board_id}/discussions/{id}/runs` / `.../runs/{run_id}` | `discussions:read` |
| POST | `.../runs/{run_id}/pause` / `.../resume` / `.../stop` | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/review` | `discussions:admin`, human only |
| GET | `/boards/{board_id}/discussions/{id}/events` (`text/event-stream`) | `discussions:read` |
| GET | `/boards/{board_id}/discussions/{id}/events/history?after=&limit=` | `discussions:read` |

A discussion references exactly one existing ticket and resolves its Loop through that ticket: every
thread carries `loop_id`, `loop_key`, `loop_name` and `ticket_key`, so the client shows the owning
Loop and deep-links the Ticket as `/boards/{board_id}/loops/{loop_id}?card={card_id}`. Participants
keep an immutable role snapshot, so later template edits never rewrite what an agent was told.

`GET /discussions/overview` is the Discussions page's first level: one entry per board with
`discussion_count`, `open_count`, `ticket_count` and the board's newest `last_activity_at`, ordered
newest activity first (boards without threads come last, by name). `ticket_count` is what lets the
new-discussion dialog offer a board first and still say which boards cannot host a thread yet, since
a discussion must reference a Ticket. It discloses board metadata, so it requires both
`boards:read` and `discussions:read`. The client then loads threads for the selected board only, so
the page never ships every thread of every board to the browser.

`start` and `runs` take the same body:

```json
{ "rounds": 3, "autonomous": true, "token_budget": 20000, "time_budget_seconds": 120 }
```

`rounds` defaults to the thread's `max_rounds` in autonomous mode and to `1` otherwise. A thread's
`max_rounds` defaults to `3` and is capped at `4`: a discussion either converges within two rounds or
starts repeating itself, and the duplicate guard stops it anyway. The cap also applies to a value
stored before it existed, so an older thread can never run longer than four rounds. A request
that resolves to a single interactive round runs inline and returns the round summary
(`status`, `answers`, `votes`, `failures`, `rounds_completed`, `tokens_used`, `elapsed_ms`,
`run_status`, `stop_reason`); anything longer returns `pending: true` and finishes in the
background, and the client polls the run. `pause`, `resume` and `stop` answer with the same summary
and `409` when the transition is not possible (for example pausing a finished run). Only one run
per thread can be active, and review is rejected (`409`) while a run is running or paused.

The round cap bounds how many calls a question makes; the budgets bound how large each call may be,
which is what protects the bill. When a caller sends no budget, the run takes
`TRALALA_DISCUSSION_TOKEN_BUDGET` (default 200 000) and `TRALALA_DISCUSSION_TIME_BUDGET_SECONDS`
(default 900). An operator disables a default by setting it to `0`; an explicit `0` from a caller
still means "exhaust immediately".

Run statuses: `running`, `paused`, `stopped`, `completed`, `failed`, `budget_exhausted`,
`no_progress`. A run stops at consensus, when the requested rounds are used up, when every
participant fails, when answers repeat (duplicate guard), or when a budget is exhausted. Thread
`run_state` mirrors `idle`/`running`/`paused`/`stopped` for the UI.

A round in which every agent repeated its previous text produced no new argument, so it is reported
as `no_progress` with `duplicate_answers` and cannot be read as agreement, whatever the recorded
votes say.

#### The answer standard

Every participant answers a round with one JSON object, and the thread stores its structure beside
its prose:

| Field | Bound | Meaning |
| --- | --- | --- |
| `position` | `yes`, `yes_with_conditions`, `no`, `unclear` | should the person go ahead with what the goal proposes |
| `recommendation` | 300 characters | one sentence: what the person should do |
| `pros` / `cons` | 5 items of 200 characters | for going ahead / against, and the risks |
| `conditions` | 5 items of 200 characters | what must hold; at least one with `yes_with_conditions` |
| `open_questions` | 5 items of 200 characters | what the participant cannot settle; at least one with `unclear` |
| `confidence` | `high`, `medium`, `low` | how sure the participant is |
| `reasoning` | 8 000 characters | the analysis in Markdown; it becomes the message's `content` |

The round prompt states the standard, and an agent whose provider takes a JSON schema gets it as
`response_format`. An answer that does not follow it is asked once more with what was wrong; one
that still does not is kept as prose with the position `unclear`, never dropped. A message's
`answer` is `{version, format, position, recommendation, pros, cons, conditions, open_questions,
confidence, problem}` with `format` `structured`, `repaired` or `prose` (then `problem` says what
was wrong), or `null` for a person's message and an answer written before the standard.

A vote is recorded when a participant's position changes, with its recommendation as the
justification; votes from before the standard read `agree` as `yes`, `disagree` as `no` and
`abstain` as `unclear`. The thread's `positions` lists each participant's current position,
recommendation, confidence and round. Consensus is every participant at `yes` or
`yes_with_conditions`. Participants answer one after another within a round and each one is shown
the answers already given in that round; in a `roundtable` thread consensus additionally requires
that an earlier round produced answers, because whoever opens a thread has read nobody.

After every round Tralala computes a `synthesis` from each participant's latest answer and stores it
on the round; the thread answers the newest one, each run's rounds their own. It is decision
support (`kind: decision_support`, `written_by: tralala`), never a decision: `suggestion`
(`verdict` in the position set and `reason`), `counts`, the participants `go` (for going ahead),
`stop` (against) and `unclear` with each one's recommendation, the `conditions` and
`open_questions` with who named them, and who is `missing`. The suggestion is `yes` when every
participant says `yes`, `yes_with_conditions` when every participant is for going ahead and some
name conditions, `no` when every participant is against, and `unclear` otherwise, with the reason
naming the split, the unclear participants or the missing answers.

Posting a human message answers it automatically in `roundtable` and `autonomous` threads: the
message starts one background round (one pass over the participants). In a `manual` thread nothing
runs unless the message opts in with `@agents` (or a participant's display name), which starts the
same single background round; otherwise use `start`/`runs` explicitly. A thread that is already
running or closed keeps the message without starting a second run, and the post never fails for
that reason. The message response carries `auto_run`: `started`, `already_running`, `thread_closed`,
`no_participants`, or `null` when no automatic reply was requested, so the client can explain a
skipped answer.

Interrupted work is reconciled at startup: runs left `running`/`paused` become `failed` with
`stop_reason=process_restart`, the thread's `run_state` returns to `idle`, `running` mention jobs
become `failed` (retryable) and `queued` mention jobs are submitted again.

**Nothing executes automatically:** approving a discussion records a decision and an
`discussion_outcomes` row, but it never changes the ticket.

#### Event stream

`GET .../events` streams server-sent events for one thread. Each event carries an `id` (its durable
sequence number), an `event` name and a JSON `data` payload; a `: keep-alive` comment arrives every
15 seconds. Reconnect with `Last-Event-ID` (sent automatically by `EventSource`) or `?after=<seq>` and
the server replays everything newer from `discussion_events` before continuing live, so a dropped
connection never loses messages. `GET .../events/history` exposes the same log as JSON for clients
without `EventSource`.

Event types: `message_created`, `agent_started`, `agent_completed`, `agent_failed`, `vote_recorded`,
`consensus_proposed`, `discussion_status_changed`, `human_review_completed`, `run_started`,
`run_finished` and `round_completed`. Every event is committed in the same transaction as the change
it describes, so the log is always ahead of (never behind) the stream. `message_created` carries a
participant's `answer`, `agent_completed` its `position` and `format`, and `round_completed` the
round's `synthesis`.

### Attachments

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards/{board_id}/attachments?card_id=` | `cards:read` |
| POST | `/boards/{board_id}/attachments?card_id=&filename=` (raw body, file `Content-Type` header) | `cards:write` |
| GET | `/boards/{board_id}/attachments/{id}` | `cards:read` |
| GET | `/boards/{board_id}/attachments/{id}/download` | `cards:read` — `Content-Disposition: attachment` |
| DELETE | `/boards/{board_id}/attachments/{id}` (soft delete + file removal) | `cards:write` |

Allowlist: `.docx .ppt .pptx .xlsx .pdf .txt .md .json .jpg .jpeg .png .gif`. The extension and the
first bytes must agree (ZIP for OOXML, `%PDF`, PNG/JPEG/GIF signatures, UTF-8 for text). Size limits:
`TRALALA_ATTACHMENT_MAX_BYTES` (default 8 MiB per file, the same as the request ceiling) and
`TRALALA_BOARD_ATTACHMENT_MAX_BYTES`
(default 200 MiB per board). Bytes are stored as `data/boards/{uuid}/attachments/{attachment_id}.bin`;
the original filename is metadata only and is sanitized (no separators, no leading dots).

The file is written to a staging name and moved into place before the row that names it is inserted,
so a crash can only leave an unreferenced file (invisible and harmless), never a row whose bytes are
missing; a rejected upload removes what it staged. A board's directory is the unit of deletion and
duplication: deleting a board removes `board.sqlite` and `attachments/` together, and duplicating it
copies both.

### Ticket summaries

A Ticket carries `summary`: what it is about in one or two plain sentences, at most 400 characters
(whitespace, line breaks included, becomes single spaces). `POST .../cards` and
`PATCH .../cards/{card_id}` (with `version`) accept it, and an empty string removes it. A planned
Ticket's summary comes from its RoadMap (`PlanTicket.summary`) and may be edited like any other,
because it is not part of the approved work definition; a re-registered plan with a summary replaces
it, one without keeps it. The card answers `summary`, `summary_source` (`plan`, `person` or `agent`;
empty without one) and `summary_stale`, which is `true` once the title or description changed after
the summary was written. A summary is part of a Ticket's content: `read_ticket` shows it, and
`list_tickets` never does.

### Where a Ticket's work is done and what it waits for

A person owns every Ticket; nothing here names who does it. A Ticket answers:

- `workplace`: `codebase` (the work is done in a repository, so it can be taken in a coding
  session), `outside` (another system or the world outside) or `unknown` (every Ticket created
  before the field existed). It describes the work and assigns nothing.
- `waiting_for`: `nothing`, `decision`, `information`, `access` (a system, key, account, setting or
  machine) or `third_party` (a supplier, a customer, a lawyer, ...), with `waiting_reason` (at most
  500 characters), `waiting_set_by` and `waiting_set_at`.
- `state`, computed on every read and never stored: `needs_input` when it waits for a decision,
  information or access; `blocked` when the plan's `blockers` are not empty or it waits for a third
  party; `ready` otherwise; `null` once it is completed. `needs_input` wins over `blocked`. `ready`
  (no blocker in the plan) and `blockers` stay as they were.
- `needs_person`: `state` `needs_input`, or `ready` with `human_action_required`.

| Method | Path | Scope |
| --- | --- | --- |
| PATCH | `.../cards/{card_id}/workplace` (`version`, `workplace`) | `cards:write` |
| PATCH | `.../cards/{card_id}/wait` (`version`, `waiting_for` other than `nothing`, `reason`) | `cards:write`; replacing another wait is a person's act (`403 human_action_required` for a token) |
| POST | `.../cards/{card_id}/wait/clear` (`version`) | `cards:write`, as a signed-in person, never a token (`403 human_action_required`) |

Each is version-checked (`409 version_conflict`), refused on a read-only Loop (`409 loop_read_only`)
and on a completed Ticket (`409 ticket_completed`); writing what the Ticket already says keeps the
version. `POST .../cards` takes `workplace`, `waiting_for` and `waiting_reason` (required with a
wait). Completing a Ticket, or confirming a human-only one, while it waits answers
`409 ticket_waiting` naming the wait: a person clears it first. A RoadMap's planned Ticket may give
`workplace`, `waiting_for`, `waiting_reason` and `labels` (names the board has); the card it
publishes starts with them, and an unknown label in a handed-in RoadMap is refused with the names
there are. A board created without a template starts with the area labels of
`TRALALA_DEFAULT_LABELS` (Development, Architecture, UX, QA, Security, Operations, Documentation,
Data, Product, Business, Economy, Legal, Support, Communication, Research); existing boards keep
theirs.

### Ticket assignment

`PATCH /boards/{board_id}/cards/{card_id}` accepts `assignee_actor_id` (a human actor id or an
enabled registry agent id) or `clear_assignee: true`. The card stores the display name and type so
lists render without a cross-database join; every change is written to the activity log. Filter with
`GET /cards?assignee=me|<actor-or-agent-id>|unassigned`.

### Lists (Loop-scoped: `/boards/{board_id}/loops/{loop_id}/lists`)

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards/{board_id}/lists?include_archived=` | `boards:read` |
| POST | `/boards/{board_id}/lists` | `cards:write` |
| GET | `/boards/{board_id}/lists/{list_id}` | `boards:read` |
| PATCH | `/boards/{board_id}/lists/{list_id}` | `cards:write` |
| POST | `/boards/{board_id}/lists/{list_id}/move` (`{"position": n}`) | `cards:write` |
| POST | `/boards/{board_id}/lists/{list_id}/archive` | `cards:write` |
| POST | `/boards/{board_id}/lists/{list_id}/restore` | `cards:write` |
| DELETE | `/boards/{board_id}/lists/{list_id}` (archived and empty) | `cards:write` |

### Cards (Loop-scoped: `/boards/{board_id}/loops/{loop_id}/cards`)

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards/{board_id}/cards` with `list_id\|q\|label\|priority\|due_before\|overdue\|completed\|include_archived\|sort\|order\|limit\|offset` | `cards:read` |
| POST | `/boards/{board_id}/cards` (`Idempotency-Key`) | `cards:write` |
| POST | `/boards/{board_id}/cards/bulk` (`{"cards": [...]}`, max 100, partial failures, `Idempotency-Key`) | `cards:write` |
| GET | `/boards/{board_id}/cards/{card_id}?include=checklists,comments` | `cards:read` |
| PATCH | `/boards/{board_id}/cards/{card_id}` (requires `version`) | `cards:write` |
| POST | `/boards/{board_id}/cards/{card_id}/move` (`version`, `list_id`, `position`) | `cards:write` |
| POST | `/boards/{board_id}/cards/{card_id}/archive` | `cards:write` |
| POST | `/boards/{board_id}/cards/{card_id}/restore` | `cards:write` |

### Labels, checklists, comments

| Method | Path | Scope |
| --- | --- | --- |
| GET/POST | `/boards/{board_id}/labels` | `cards:read` / `cards:write` |
| PATCH/DELETE | `/boards/{board_id}/labels/{label_id}` | `cards:write` |
| GET/POST | `/boards/{board_id}/cards/{card_id}/checklists` | `cards:read` / `cards:write` |
| PATCH/DELETE | `/boards/{board_id}/checklists/{checklist_id}` | `cards:write` |
| POST | `/boards/{board_id}/checklists/{checklist_id}/items` | `cards:write` |
| PATCH/DELETE | `/boards/{board_id}/checklist-items/{item_id}` | `cards:write` |
| GET/POST | `/boards/{board_id}/cards/{card_id}/comments` | `cards:read` / `comments:write` |
| PATCH/DELETE | `/boards/{board_id}/comments/{comment_id}` | `comments:write` (agents: own comments only) |
| GET | `/boards/{board_id}/cards/{card_id}/mentions` | `cards:read` |
| POST | `/boards/{board_id}/cards/{card_id}/mentions/{job_id}/retry` (`202`) | `comments:write` |
| GET | `/boards/{board_id}/cards/{card_id}/events` (`text/event-stream`) | `cards:read` |
| GET | `/boards/{board_id}/cards/{card_id}/events/history?after=&limit=` | `cards:read` |

A label name is unique on its board, compared exactly (`Bug` and `bug` are two labels). Creating a
label, or renaming one, to a name another label has answers `409 label_name_taken` with
`details.name`.

Mention an enabled agent in a comment with `@[Agent Name]` (the composer inserts this form; a bare
`@Name` also matches an enabled agent whose name is an exact prefix). Saving the comment queues one
job per mentioned agent and returns immediately; each job answers as a normal agent-authored comment
in the same thread. `mentions` exposes the jobs (`queued`, `running`, `completed`, `failed`) with
`error` and `can_retry`; a failed job can be retried with the retry endpoint, which never duplicates
the comment. The ticket event stream carries `agent_started`, `agent_completed` and `agent_failed`
with the same `Last-Event-ID` replay semantics as the discussion stream; payloads carry ids,
counters and the error text only, so clients refetch the comment instead of reading duplicated text.

### Search and activity

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards/{board_id}/loops/{loop_id}/search?q=&label=&priority=&overdue=&completed=&list_id=&include_archived=` | `cards:read` |
| GET | `/search?q=` (all active boards) | `cards:read` |
| GET | `/boards/{board_id}/activity?entity_type=&entity_id=&actor_type=&action=` | `boards:read` |

`q` is matched without the spaces around it. In a Loop's search a blank `q` (empty or only
whitespace) is no text filter, so the other filters alone decide; `meta.engine` says whether the
text was matched by the board's FTS5 index (`fts5`) or by `LIKE` (`like`). The App-wide search needs
text and answers a blank `q` with `422 validation_failed`.

## Worker tools (MCP and `/llms.txt`)

`backend/app/services/agent_tools.py` holds one catalogue: a name, a description, a JSON Schema, the
scope it needs and a handler that calls the same services as the routes above. `/mcp` serves it as
MCP tools (`initialize`, `tools/list`, `tools/call`, `ping`; notifications answer `202`), and
`/llms.txt` summarises it. The browser WebMCP adapter is a separate surface for a person's own
session and is not generated from this catalogue yet. A tool is listed only when the
calling token holds its scope, and `tools/call` re-checks it before the handler runs.

| Tool | Scope | What it does |
| --- | --- | --- |
| `whoami` | `boards:read` | The calling key: its name, who issued it, when it expires (`days_left`, `expires_soon` under 7 days), the scopes it holds and the tools they open, each member scope it lacks with the tools that scope alone would open, and the rule-11a decisions only a person makes; never the token or its hash |
| `list_boards` | `boards:read` | The boards the token may read, by name, with status and Loop count; a board id comes from here |
| `loop_summaries` | `loops:read` | One row per Loop of a board (open ones unless `include_completed`; `stage` narrows them): its goal cut to 280 characters, its stage, `next` (what has to happen now, in one sentence) and `waiting_on` (`person`, `agent` for a document, `anyone` or `nobody`; a Ticket never waits on an agent), `execution_allowed`, its Tickets by state (`ready`, `needs_input`, `blocked`, `completed`, `total`, `needs_person`) and by column, and each document's state and revision. Computed from what the Loop records, never written by anyone |
| `read_board` | `boards:read`, `loops:read` | The board's Loops by id, key, name and stage, the people you may assign, the agents you may ask |
| `read_loop` | `loops:read` | The Loop's overview, by its id or its key: goal and stage, `execution_allowed`, each document's state, revision, provenance and size (never its text), the Phases and the columns with their Ticket counts, the work outside the plan and the newest five notes cut to 500 characters; the Tickets themselves are `list_tickets`' answer |
| `read_document` | `loops:read` | One document of a Loop named by its id or its key, by `kind` (`info`, `analysis`, `analysis_ai`, `roadmap`, `roadmap_ai`): as numbered lines, at most 60 000 characters, with `continue_from` for the rest; `analysis_ai` and `roadmap_ai` also as `view: structured`, an outline of the findings or the Phases and Tickets, and one of them in full with `item` |
| `read_ticket` | `cards:read` | The Ticket's summary (with `summary_source` and `summary_stale`), description, acceptance criteria, evidence, checklist, comments, column, version, `state`, `workplace`, `wait` (what it waits for, the reason, who set it and when; `null` without one), the plan's `blockers`, `needs_person` and `allowed_actions` |
| `search_tickets` | `cards:read` | Tickets by words in one Loop, a board's open Loops or every active board, each with board, Loop key, key and column |
| `list_tickets` | `cards:read`, `loops:read` | Which Tickets there are and where each stands, never what one says: id, key, title, Loop key, column, Phase, `state`, `workplace`, `human_action_required`, assignee and `completed` (`fields: brief` keeps id, key and title). Column by column, then by Phase and key. Filters: `loop_id` (an id or a key), `column` (names), `assignee` (`me`, `none` or an id), `phase`, `state` (one or more of `ready`, `needs_input`, `blocked`), `workplace`, `waiting_for`, `needs_person`, `human_action_required`, `label`, `priority`, `due_before`, `overdue`, `summary` (`missing` or `stale`), `query`; completed Tickets and Loops only with `include_completed`. The answer repeats the filters, maps each Loop key to its id and pages with `limit` (at most 200) and `continue_from`; an unknown column is refused with the column names there are. Work for a coding session: `workplace: codebase`, `state: ready`, `human_action_required: false`; what needs a person: `needs_person: true` |
| `set_ticket_wait` | `cards:write` | Say what an open Ticket that waits for nothing now waits for (`decision`, `information`, `access` or `third_party`) and why (`reason`); the version is read for the caller. Clearing or replacing a wait is a person's act and never a tool |
| `write_ticket_summaries` | `cards:write` | Write up to 100 Ticket summaries; each is a versioned edit that reads the version itself and retries once on a race, and each Ticket answers `written` or its refusal |
| `create_loop` | `loops:write` | Start a Loop on a board for one coherent change |
| `write_info` | `loops:write` | Write the agreed intent; allowed while the Loop is `draft` or `analysis_review` |
| `run_analysis` | `loops:generate` | Ask a board agent for the Analysis candidate and report the run and the document state |
| `run_roadmap` | `loops:generate` | Ask for the RoadMap candidate once the analysis is approved |
| `write_analysis` | `loops:generate` | Hand in the worker's own analysis through the candidate route; schema errors answer one `loc: message` line each |
| `write_roadmap` | `loops:generate` | Hand in the worker's own RoadMap; Phase and Ticket ids that are not UUIDs become `uuid5` of the Loop and the id, returned as `id_map`. Both take an optional `brief`, stored as the human view instead of asking a board agent |
| `write_brief` | `loops:generate` | Write the brief for people (`kind`: `analysis` or `roadmap`) of the current technical revision; refused over a current approval |
| `assign_ticket` | `cards:write` | Set or clear the owner; the current version is read for the caller |
| `move_ticket` | `cards:write` | Move to another column by id or name; the version is read and one retry absorbs a race |
| `comment_ticket` | `comments:write` | Add a progress note, finding or blocker, on an open or a completed Ticket; only a read-only Loop or board refuses it |
| `write_note` | `loops:write` | Add a note to the Loop's log: what belongs to the Loop and to no single Ticket; refused on a completed Loop |
| `read_notes` | `loops:read` | The Loop's notes, oldest first, a page at a time (`older` is the next `before`) |
| `create_ticket` | `cards:write`, `comments:write` | Add a Ticket outside the plan while the Loop executes, in its first column, keyed `<LoopKey>-UNP-<nnn>`, with an optional `summary`, `workplace`, `waiting_for` with `waiting_reason`, and `labels` the board has (an unknown one is refused with the names there are, never created); `follow_up_of` prefixes the description and comments on the origin Ticket; the same request again answers the first Ticket |
| `complete_ticket` | `cards:write`, `comments:write` | Complete a Ticket (`completed: true`, the version read for the caller, one retry on a race), then comment the summary and the evidence as a list; answers the key, version, comment id and the Loop's stage and progress. The summary is kept as a comment even on a Ticket that is already done or whose completion is refused; the refusal carries its `comment_id` |
| `ask_agents` | `discussions:write` | Create a discussion on the Ticket and run one round; returns the synthesis, the positions and the structured answers |
| `read_discussion` | `discussions:read` | Read a thread: the newest round's synthesis, each agent's position and the messages (prose with `include_prose`) |
| `reply_discussion` | `discussions:write` | Post a follow-up and, unless `run=false`, let the agents answer it in the same thread |

The flow a person and their worker use to start work is `create_loop` → `write_info` →
`run_analysis` → the person approves the analysis → `list_tickets`/`read_ticket` to work the Tickets it
produces. Every step stays inside the same gates: the analysis and the RoadMap are candidates until a
signed-in person approves them, and a cancelled or completed Loop is read-only.

Deliberately absent: board and list structure changes, planned Ticket creation or archiving, RoadMap and QA
writes, provider configuration and the approval decisions themselves.

A tool lists **every** scope it needs, and `tools/list` hides a tool unless the token holds all of
them — advertising a call that would fail is worse than not advertising it. Calling a tool the token
may not use is a JSON-RPC error (`-32602`) rather than a silent downgrade, and so is a `tools/call`
whose `params` or `arguments` is not a JSON object. A tool that fails returns
`isError: true` with the API error code in the text content, so a client sees `version_conflict` or
`human_action_required` instead of a broken transport.

Retries are safe where they matter. `create_loop` accepts an `idempotency_key` and replays the first
answer for the same key; `write_info` returns the current revision unchanged when the content is
identical; `comment_ticket` and `ask_agents` recognise the same actor repeating the same content or
question within five minutes and return the existing comment or thread (`deduplicated: true`) instead
of writing a second one, and `complete_ticket` does the same for the same summary and evidence. A
Ticket that is already completed answers `already_completed: true` and keeps a new summary as a
comment. A comment holds up to 20 000 characters.

## Example: create a card

```http
POST /api/v1/boards/{board_id}/cards
Authorization: Bearer trl_…
Idempotency-Key: 5f2c1b0a
Content-Type: application/json

{"list_id": "…", "title": "Implement authentication", "description": "Create API authentication", "priority": "high", "labels": ["backend", "security"]}
```

```json
{
  "success": true,
  "data": {
    "id": "…", "board_id": "…", "list_id": "…", "title": "Implement authentication",
    "description": "Create API authentication", "position": 1024, "priority": "high",
    "due_at": null, "completed_at": null, "created_at": "2026-10-30T12:00:00Z",
    "updated_at": "2026-10-30T12:00:00Z", "archived_at": null, "version": 1,
    "labels": [{ "id": "…", "name": "backend", "color": "#64748b" }],
    "checklist_total": 0, "checklist_completed": 0, "comment_count": 0
  },
  "request_id": "…"
}
```

## Status codes

`200` ok · `201` created · `204` no content · `401` unauthenticated · `403` scope/CSRF/ownership ·
`404` not found (also used when disclosure is not allowed) · `409` conflict, version or state ·
`413` payload too large · `422` validation failure · `429` rate limited · `503` temporarily
unavailable.

## Cost of the board list

`loop_count`, `list_count` and `card_count` live inside each board's own database, so measuring them
for the whole list means opening every board file. The registry therefore remembers the last
measurement (`board_stats`) and drops it whenever the board is written to, so a page of boards costs
one registry read instead of one open per row. `TRALALA_BOARD_COUNTS_CACHE_SECONDS` (default 60) is
the backstop for a board file changed outside the app; `0` measures on every list. A caller that
only needs names can pass `with_counts=false`, which opens no board at all and reports zeros.

With 100 boards a page of 100 rows costs 15 ms once the counters are known, against 1337 ms when
each board has to be opened.

## Timestamps and sizes

- `due_at` and `due_before` accept an ISO 8601 date (`2027-01-15`) or timestamp
  (`2027-01-15T09:30:00Z`). Dates are normalized to midnight UTC; free text is rejected with
  `422 validation_failed` so due-date filters stay correct.
- Request bodies are limited by `TRALALA_MAX_REQUEST_BYTES` (default 8 MiB), and the bundled Caddy
  sits one step above it (`request_body max_size 9MB`) so the backend's answer is the one a client
  normally sees. The backend counts the bytes as they arrive, so a chunked request without a
  `Content-Length` header is refused with `413 payload_too_large` like any other. A chunked body past
  the proxy ceiling is cut off at the proxy instead: the connection closes, so a client should never
  send more than it declared.
- A board archive is accepted up to 8 MiB compressed, but each member is also bounded after
  decompression: `manifest.json` to 1 MiB and `board.sqlite` to `TRALALA_BOARD_IMPORT_MAX_BYTES`
  (default 256 MiB). An archive that expands past either limit is refused with
  `422 validation_failed` and its member named in `details`.

## No cross-Loop or cross-board transfer

There is no transfer endpoint. Moving a Ticket between Loops or Boards would bypass the approved
plan it belongs to, so the operation is refused rather than implemented: a caller that reaches the
service directly gets `409 plan_change_required` with the reason. The supported path is a new Loop
with its own Info, analysis and RoadMap — or a person recreating the Ticket deliberately.

## Board schema state

Each board tracks its schema with an Alembic revision in its own database. Board responses include
`schema_revision` (the applied revision) next to `schema_version` (the number of revisions in the
chain). Boards are migrated eagerly at startup; if a migration fails the board status becomes
`migration_failed`, mutations return `409 board_migration_failed` and reads return
`503 board_schema_outdated` until an administrator retries `POST /boards/{id}/migrate` or restores
a pre-migration backup.
