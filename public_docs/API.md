# REST API

Base path `/api/v1`. Interactive documentation: `/docs`, machine description: `/openapi.json`.
Both require a session by default (`TRALALA_DOCS_REQUIRE_AUTH`) and disappear entirely when
`TRALALA_ENABLE_DOCS=false`; bearer-token agents can fetch the schema with their token.

Two more entry points live at the origin rather than under `/api/v1`:

| Path | Auth | Purpose |
| --- | --- | --- |
| `/llms.txt` | public | Plain-text bootstrap: envelope, Loop lifecycle, rules and the worker tools. Contains no ids or data. |
| `/mcp` | Bearer | The curated worker catalogue over MCP revisions 2026-07-28 and 2025-06-18 on the one address (JSON-RPC 2.0 over Streamable HTTP, one JSON answer per POST): `server/discover`, `tools/list` and `tools/call` with `_meta` and the MCP headers in 2026-07-28, `initialize`, `ping`, `tools/list` and `tools/call` in 2025-06-18; no session in either ([The MCP endpoint](#the-mcp-endpoint)). The tool list is filtered to the scopes the token holds. |

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
`ticket_completed`, `report_required`, `plan_change_required`, `instructions_required`,
`instructions_changed`, `generation_input_changed`, `generation_unavailable`,
`generation_in_progress`, `qa_incomplete`.

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

Every scope, what it allows, and who may hold it. A session's scopes come from its account role and
nothing is implicit: `admin` holds every scope but `loops:decide`, `member` every scope but
`loops:decide`, `users:admin` and `credentials:admin`. A token holds only what it was granted: a
member may grant the scopes in `member_token_scopes`, an administrator also those marked
*admin-issued*, and the rest no token can hold (`GET /meta` publishes both lists as
`member_token_scopes` and `token_scopes`). `loops:decide` lives only on a key.

| Scope | Allows | A token |
| --- | --- | --- |
| `boards:read` | read boards, their columns and activity | member-issued |
| `boards:write` | create, change, duplicate, archive and restore boards, templates and a Loop's agent choice; take a backup | admin-issued |
| `boards:admin` | delete boards and templates, manage repositories, restore a backup, retry a migration | never |
| `cards:read` | read Tickets, labels, checklists, comments, attachments and search | member-issued |
| `cards:write` | create, change, move, assign and archive Tickets; labels, checklists and attachments; a Ticket's workplace and wait | member-issued |
| `comments:write` | comment on a Ticket, edit or delete a comment, retry a mention | member-issued |
| `loops:read` | read Loops: their documents, plan, readiness, notes and context | member-issued |
| `loops:write` | create, change, cancel and archive a Loop; write its Info and notes; record QA results | member-issued |
| `loops:generate` | start and cancel generation runs; hand in a candidate, a brief or QA instructions | member-issued |
| `loops:review` | approve or reset an analysis or a RoadMap, accept the implementation, decide QA (a person only) | never |
| `loops:decide` | the right to decide in the editor; given by the key's owner only while `editor_decisions` is on, and never alone. It opens no tool today | member-issued |
| `history:read` | search and read the history of completed Loops | member-issued |
| `agents:read` | read agents and role templates | never |
| `agents:write` | create, change, duplicate and test agents and role templates | never |
| `agents:admin` | delete agents and role templates, restore the factory roles | never |
| `discussions:read` | read discussions and mark them read | member-issued |
| `discussions:write` | open, continue, run, close and reopen discussions | member-issued |
| `discussions:admin` | record the decision on a discussion (a person only) | never |
| `discussions:vote` | reserved; no route requires it today | admin-issued |
| `credentials:admin` | manage the installation-wide API keys | never |
| `users:admin` | manage accounts, invitations and passwords | never |

A key never issues a key: `POST /credentials` and a rotation refuse every token with
`403 human_action_required`, whatever its scopes. The human-only decisions above refuse a token the
same way even when it could hold the scope.

## Endpoints

### System

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | Liveness |
| GET | `/meta` | API version, `scopes`, `token_scopes` (the subset a token may hold), `member_token_scopes` and `member_token_limits` (what a person may grant themselves), `editor_decisions` (whether `TRALALA_EDITOR_DECISIONS` is on, so a person may give their own key `loops:decide`), feature flags, and for an administrator only `bootstrap_password_file_present` (authenticated) |

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

`loops:decide`, the right to decide in the editor, has rules of its own. It is given only while
`TRALALA_EDITOR_DECISIONS` is on (`422 editor_decisions_off` otherwise) and only beside another
scope (`422 decide_needs_access`). The person who issues a key owns it, so the right only ever goes
to one's own key, and a request that came through a key never issues or rotates one
(`403 human_action_required`). A rotation by the owner keeps the right; one by an administrator of
somebody else's key, or of a key nobody owns, issues the successor without it.

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
| GET | `/boards/{board_id}/loop-summaries` | One row a Loop, as `loop_summaries` gives it: stage, `without_plan`, the next step, who it waits for (`person`, `agent`, `anyone`, `nobody`), `decision_link` (where a person takes the next decision, see Worker tools), Tickets by state and column, each document's state; open Loops unless `include_completed=true`. The dashboard and the board page read it, one request a board |
| POST | `/boards/{board_id}/loops/{loop_id}/cancel` | Human-only; records `cancelled_at` |
| POST | `/boards/{board_id}/loops/{loop_id}/archive` | Hides the Loop from active views |
| GET | `/boards/{board_id}/loops/{loop_id}/documents` | Current and approved revisions per kind |
| GET | `/boards/{board_id}/loops/{loop_id}/documents/{kind}/revisions` | Revision history |
| PUT | `/boards/{board_id}/loops/{loop_id}/documents/info` | New immutable revision. A person while the Loop is open; a token (`write_info`) only while the Loop is `draft` or `analysis_review`, then `403 human_action_required` |
| POST | `/boards/{board_id}/loops/{loop_id}/candidates` | Submits an analysis or RoadMap candidate; validation only, never approval. `expected_info_revision_id` / `expected_analysis_revision_id` answer `409 document_stale` when that document changed; a token gets `403 human_action_required` while the scope's approval is current. An optional `analysis_brief` or `roadmap_brief` is stored as the human view (`422 brief_invalid` when an analysis brief breaks the sign, `422 brief_rejected` when a brief breaks another rule); without one the answer adds `human_view`: the run that writes the brief for people, or `skipped` with the reason. A RoadMap whose Tickets' faces break the template answers `422 face_invalid` and stores nothing |
| POST | `/boards/{board_id}/loops/{loop_id}/briefs` | `{kind, brief, expected_revision_id?}`: the brief for people of the current `analysis_ai` or `roadmap_ai`, stored as the `analysis` or `roadmap` revision. It approves nothing; a token gets `403 human_action_required` while the scope's approval is current, a person never; `409 document_stale` when `expected_revision_id` is no longer current; `422 brief_invalid` names every way an analysis brief breaks the sign, `422 brief_rejected` every other problem |
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
| POST | `/boards/{board_id}/loops/{loop_id}/completion` | Human-only implementation acceptance and QA outcome; `accept_unfinished: true` accepts although delivery Tickets are not completed. In a Loop without a plan it is the one decision that closes the Loop, with no QA ([A Loop without a plan](#a-loop-without-a-plan)) |
| GET | `/boards/{board_id}/loops/{loop_id}/qa` | Active or latest QA cycle with both instruction views |
| PUT | `/boards/{board_id}/loops/{loop_id}/qa/instructions` | Supplies a scenario set (human or agent) |
| POST | `/boards/{board_id}/loops/{loop_id}/qa/results` | Records scenario outcomes; agents may submit |
| POST | `/boards/{board_id}/loops/{loop_id}/qa/decision` | Human-only acceptance; finalizes atomically |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/confirm` | Human-only confirmation of a human Ticket |
| GET | `/boards/{board_id}/loops/{loop_id}/poc-decisions` | The Loop's POC decisions and what is missing from a person, in review order, with `counts`; `card_id` and `status` (`open`, `ok`, `feedback`) narrow the list, never the counts ([POC decisions and the stop list](#poc-decisions-and-the-stop-list)) |
| POST | `/boards/{board_id}/loops/{loop_id}/poc-decisions` | Records one (`cards:write`, a key as much as a person; `201`); `422 poc_decision_invalid`, the same open record again answers the first with `deduplicated: true` |
| POST | `/boards/{board_id}/loops/{loop_id}/poc-decisions/{decision_id}/answer` | Human-only: `ok`, or `feedback` that becomes a Ticket; `409 poc_decision_answered`, `404 poc_decision_not_found` |
| GET | `/boards/{board_id}/loops/{loop_id}/stops` | The Loop's stop list (`loops:read`) |
| PUT | `/boards/{board_id}/loops/{loop_id}/stops` | Human-only: replaces the stop list (`loops:write`); `422 stops_invalid` |
| GET | `/boards/{board_id}/tickets` | Explicit Board-level aggregate read; each row names its Loop |
| GET | `/boards/{board_id}/history` | History search (`q`, `source_kind`, `loop_key`, `qa_status`, dates); each record says `without_plan`, and a Loop closed without a plan has `qa_status` `not_run` |
| GET | `/boards/{board_id}/history/{history_id}` | Immutable record with its envelope and artifacts |
| POST | `/boards/{board_id}/history/import` | Legacy envelope ingestion; never creates Tickets |

Ticket keys look like `AC004-DA02-003`: Loop prefix and Board-local Loop sequence, Phase prefix and
number, then the Ticket sequence within that Phase. They are allocated by the server, frozen after
allocation and unique within the Board. A Ticket added by hand (`POST .../cards`, `create_ticket`)
is keyed `<LoopKey>-UNP-<nnn>` instead, such as `AC004-UNP-001`, whether it is work outside a plan
or a Ticket of a Loop without a plan; the number is never used again in that Loop.

#### POC decisions and the stop list

What stands in the way of work is one of three kinds, and only the last stops it: a POC decision
(a choice that can be changed afterwards, taken and recorded while the work goes on), something
missing from a person (recorded while the work goes around it), and a real stop, which only the
Loop's stop list names and which is a wait on a Ticket (below, under the wait). Neither record ever
blocks anything.

`POST .../poc-decisions` takes `kind` (`decision` or `missing`), an optional `card_id` (a Ticket
of this Loop, else `409 loop_mismatch`), and the text fields: `title`, `chosen`, `reason`,
`alternative`, `change_path`, `missing`, `builds_on` and `details`. A `decision` needs `title`,
`chosen`, `reason`, `alternative` and `change_path`; a `missing` one needs `title`, `missing` (what
a person has to provide), `reason` (why it is needed), `chosen` (how the work goes around it) and
`change_path` (what is done once it is there). `builds_on` says what other work builds on it,
empty when nothing does. Every field but `details` is text for a person: the title at most 120
characters, every other field at most 3 sentences and 400 characters, and none holds a code fence
or span, a file path or file name, an id or a code symbol. `details` is the text for the AI, at
most 20 000 characters. A breach is `422 poc_decision_invalid` with `details.errors` (one sentence
each, at most 20), `details.error_count` and `details.fields`, each `{field, rule}` with the rule
`missing`, `chars`, `sentences`, `code_fence`, `code_span`, `file_path`, `id`, `finding_id` or
`code_symbol`; nothing is stored. Recording works in every stage of a Loop that still takes
writes (`409 loop_read_only` otherwise) and never looks at a Ticket's wait, state or completion.

A record answers `id`, `key` (`<LoopKey>-POC-<nnn>`, never reused in the Loop), `loop_id`,
`card_id`, `ticket_key`, `ticket_title`, `phase_number` and `phase_complete` of its Ticket's Phase,
`kind`, the text fields, `built_on` (`builds_on` is not empty), `status` (`open`, `ok`,
`feedback`), `feedback`, `feedback_ticket` (`{id, key}` of the Ticket feedback became, else
`null`), `due`, `created_at`, `created_by` (`{name, type}`), `answered_at` and
`answered_by_name`; the record route adds `deduplicated`. An open record is `due` once every
Ticket of the Loop is completed, or, when other work builds on it, once the Phase of its Ticket is
complete. The list orders them for review: open ones other work builds on first, then the open
`missing` ones, then the other open ones, then the answered ones, by key within each group.
`counts` is `{open, built_on_open, missing_open, due, answered}` over the whole Loop.

`POST .../poc-decisions/{decision_id}/answer` takes `answer` (`ok` or `feedback`) and, with
`feedback` only, `feedback` (1 to 2 000 characters). It is a signed-in person's (`403
human_action_required` for a key, even one that may decide in the editor). `ok` answers an open
record (an OK one again changes nothing); `feedback` answers an open or OK one and creates a Ticket
in the Loop's first column, titled `Feedback on <key>: <title>`, with the feedback and the record
as its description, in the same transaction: a Loop whose stage takes no new Ticket refuses the
answer with that Ticket's error and stores nothing. A record answered with feedback is
`409 poc_decision_answered`. Every record and answer is an activity entry on the Loop.

`GET .../stops` answers `{stops, is_default}`: the Loop's lines, and `is_default: true` while no
person has written a list, when the lines are the default ones ("Deployment to production",
"Deleting data", "Money", "Something sent to people outside", "A new kind of personal data").
`PUT .../stops` with `{stops: [...]}` replaces the list: 0 to 12 lines, each one line of 1 to 140
characters once trimmed and none twice (case-insensitive), else `422 stops_invalid` naming each
line and rule; an empty list means nothing stops the Loop's work. It is a signed-in person's at
every stage of a Loop that still takes writes (`403 human_action_required` for a key).

A Loop summary row (`GET .../loop-summaries`, `loop_summaries`) carries `poc_decisions` with the
same five counts, and its `tickets` count `awaiting_confirmation`: the completed Tickets that are
done while a human-only Ticket before them waits for a person's confirmation (they count in
`completed` too).

#### A Loop without a plan

A Loop that has no plan, no analysis and no RoadMap is under way as soon as it holds a Ticket that
is not archived: the fast track for a small change. Nothing is chosen when the Loop is created, and
Info does not count. Its stage is `ready`, then `in_progress` once one of its Tickets is completed;
the Loop (`GET .../loops/{loop_id}` and the list) and its `loop-summaries` row say
`without_plan: true`, and its `progress` counts its Tickets. Readiness answers
`execution_allowed: true` with no Phases, lists the Tickets under `unplanned` and the open ones
under `open_delivery`, and the Loop's warnings leave out the missing analysis. An analysis or a
RoadMap written for it puts it on the planned path, and archiving every Ticket it holds takes it
back to `draft`; either way `without_plan` is false again. From its first Ticket on, the Info is a
person's: a token's `PUT .../documents/info` answers `403 human_action_required`.

`POST .../completion` closes such a Loop in one decision of a signed-in person (a token gets
`403 human_action_required`): no QA cycle, QA Task or QA decision, and the payload's `qa_status`
and `attestation` are not read. A Ticket that is neither completed nor archived refuses it
(`409 ticket_blocked`, the Tickets under `details.open`) unless `accept_unfinished: true`; it then
stays as it is and reads `state: not_done`. The decision records `without_plan: true` and the keys
it left (`unfinished`). The answer is the completed history record: `qa_status` `not_run`,
`without_plan: true`, the envelope's `loop.without_plan` `true`, and a Ticket left open with the
disposition `not_done`. Once every Ticket is done, the Loop's `loop-summaries` row says "Every
Ticket is done: a person closes the Loop with one decision; no QA." with `waiting_on: person`.

#### Generation run steps

Every generation run answers `trace`, its process tree: one step per event, written to the run as it
happens (best effort, like `phase`), so a caller that polls `GET …/generation-runs/{run_id}` sees it
grow. The run list and every other answer that carries a run include it; a run recorded before the
trace existed answers `[]`. Each step is an object:

| Field | Value |
| --- | --- |
| `stage` | `documents`, `repository`, `writing`, `checking` or `saving`, in the order a run reaches them; a QA run has no `repository` stage |
| `kind` | `step`, `tool` (a tool call), `note` (the model's own words beside a call), `repair` (an answer sent back), `limit` (a limit the run reached, or a repository of several not read) or `error` (a failure, a repository that could not be read among them) |
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
`{id, name, error, problem}` with a class such as `unauthorized`, `not_found`, `rate_limited`,
`too_large`, `timeout` or, for a commit that gave nothing to read, `empty_archive`,
`nothing_readable` or `paths_match_nothing`; `problem` is the same in one sentence that says what to
do, the sentence the repository check answers as `detail`. The run's repository stage then holds an
`error` step with that sentence, the model is told that it has none of that code, and a saved
analysis opens its `open_questions` with a notice that it was written without it (with
`repository_revision` `none: the code was not read` when no repository could be read). The run record
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
Resetting the RoadMap also withdraws the plan in force: the plan is superseded, the Loop has no
current plan, every card a plan published that nobody touched is deleted and every other one is
archived; the `loop.roadmap_reset` activity lists both by key (`removed`, `archived`). A card
added outside the plan stays. `409 nothing_to_reset` means the scope is already empty and, for the
RoadMap, no plan is in force; `409 document_empty` refuses to approve a blank document, which is
what a reset leaves behind.

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
| GET | `/discussions/inbox` (the threads that are not cancelled on every board that is not archived, by who they wait for) | `boards:read` + `discussions:read` |
| GET | `/boards/{board_id}/discussions?status=&card_id=&scope=&state=&limit=` | `discussions:read` |
| POST | `/boards/{board_id}/discussions` (on a Ticket with `card_id`, on the board with a `title` and no `card_id`) | `discussions:write` |
| GET | `/boards/{board_id}/discussions/{id}` (participants, messages with their answers, positions, synthesis, votes, runs) | `discussions:read` |
| POST | `/boards/{board_id}/discussions/{id}/read` (sets the caller's read marker to now) | `discussions:read` |
| POST | `/boards/{board_id}/discussions/{id}/messages` | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/close` (the opener only) | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/reopen` (the opener or a signed-in person) | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/start` (runs one round inline by default) | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/runs` (`202`, always background) | `discussions:write` |
| GET | `/boards/{board_id}/discussions/{id}/runs` / `.../runs/{run_id}` | `discussions:read` |
| POST | `.../runs/{run_id}/pause` / `.../resume` / `.../stop` | `discussions:write` |
| POST | `/boards/{board_id}/discussions/{id}/review` | `discussions:admin`, human only |
| GET | `/boards/{board_id}/discussions/{id}/events` (`text/event-stream`) | `discussions:read` |
| GET | `/boards/{board_id}/discussions/{id}/events/history?after=&limit=` | `discussions:read` |

A discussion lives on one existing Ticket or on the board itself. One on a Ticket resolves its Loop
through that Ticket: the thread carries `card_id`, `loop_id`, `loop_key`, `loop_name` and
`ticket_key`, so the client shows the owning Loop and deep-links the Ticket as
`/boards/{board_id}/loops/{loop_id}?card={card_id}`. One on the board is created without `card_id`
and needs a `title` (`422 validation_failed` without one); those fields are `null`, and a round
briefs its agents with the board's name, its description and the title in place of a Ticket.
Opening a thread on a Ticket of a completed, archived or cancelled Loop answers
`409 loop_read_only`.
Participants keep an immutable role snapshot, so later template edits never rewrite what an agent
was told.

A message's body is `{content, parent_message_id, ticket}`: `ticket` is the Ticket it points at, by
its id or its key on the same board (`422 validation_failed` when it is not there), and the message
answers it as `ref_ticket` (`{card_id, ticket_key, title, loop_id}`, or `null`). Every message
carries `after_closed`, true for one written while the thread was closed.

**Closing.** `POST .../close` is for the one who opened the thread, a person or a key alike;
anyone else, a signed-in person included, is refused with `403 not_opener`. A thread already
closed or cancelled answers `409`, and so does one with a run running or paused and one a person
has approved or vetoed, which is finished by that decision. A closed thread
has `status: closed` and `closed_at`; it stays readable, still takes messages (each
`after_closed: true`, the thread stays closed, and `auto_run` reads `thread_closed`), never starts a
round (`start` and `runs` answer `409`) and takes no review (`409`). `POST .../reopen` is for the
opener or a signed-in person (`403 not_opener` for another key) and only for a closed thread
(`409` otherwise); the thread is `discussing` again and `closed_at` is `null`. Both answer the
thread, need an active board (`409 board_archived`) and, on a Ticket, a Loop that takes writes
(`409 loop_read_only`). Nothing deletes a thread or a message.

**Read markers.** Every thread in the board's list, its detail and every inbox row carry two fields
for the caller: `unread`, true when someone else wrote a message after the caller's read marker,
or wrote one at all when the caller has none, and `opened_by_me`. Reading with `GET` never moves a
marker. `POST .../read` sets it to now and answers `{discussion_id, actor_id, last_read_at}`; it is
the reader's own bookkeeping, so it needs only `discussions:read` and works on an archived board
too. The worker tool `read_discussion` sets it as it reads.

`GET /discussions/inbox` is the Discussions page: every thread that is not cancelled, on every
board that is not archived, as `{items, total}`. An archived board refuses a decision
(`409 board_archived`), so none of its threads waits for anyone; they are read on its Tickets. A row is `{discussion_id, board_id, board_name, loop_id, loop_key,
loop_name, card_id, ticket_key, card_title, question, status, run_state, verdict, counts,
participant_count, round_count, max_rounds, asked_by_name, last_activity_at, decided_by_name,
waits_for, unread, opened_by_me}`: `question` is the thread's goal, `verdict` the newest round's
suggested verdict (`null` before a round), `counts` how its answers stand (`go`, `stop`, `unclear`,
`missing`), and `waits_for` is `nobody` (closed by its opener, without any of the board's agents,
or approved, vetoed or rework requested), `agents` (a run is running or paused) or
`your_decision` (otherwise, a thread without a round included). A thread on the board has `null`
for its Loop and Ticket fields. The rows come `your_decision` first, then `agents`, then `nobody`,
in each group the unread ones first and then newest activity first, at most 200 of them with
`total` counting all; a board whose database cannot be opened is left out. It discloses board metadata, so it
requires both `boards:read` and `discussions:read`. It replaces `GET /discussions/overview`, which
is gone, as is the per-board summary it answered.

`card_id` on the board's list narrows it to one Ticket's threads (the Ticket's Discussions tab),
`scope` to the threads on the board itself (`board`) or on a Ticket (`ticket`), and `state` to the
`closed` ones or the `open` ones (every other status). Every thread carries `decided_by_name`, the
person who recorded its newest decision, or `null`, and `closed_at`.

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
| `recommendation` | one sentence of at most 20 words (200 characters), plain text | what the person should do |
| `pros` / `cons` | 3 items of 140 characters, plain text | for going ahead / against, and the risks |
| `conditions` | 3 items of 140 characters, plain text | what must hold; at least one with `yes_with_conditions` |
| `open_questions` | 3 items of 140 characters, plain text | what the participant cannot settle; at least one with `unclear` |
| `confidence` | `high`, `medium`, `low` | how sure the participant is |
| `reasoning` | 8 000 characters, no rule on its content | the analysis in Markdown; it becomes the message's `content` |

The recommendation and the four lists are the answer's sign, what a person reads by default.
"Plain text" is the rule a Ticket's face follows: no file path or file name, no code span or fence,
no code symbol, no UUID or other id. The server counts and matches it, never a model. The
reasoning is read by the other agents and shown to the person as raw text, so it may be as long
and technical as it needs to be.

The round prompt states the standard and says who reads which part, and an agent whose provider
takes a JSON schema gets it as `response_format` (with `maxItems` and `maxLength`). An answer that
does not follow it is asked once more with every finding, one line each that names the field (a
list item by its 0-based index), the rule and the text:

```text
recommendation: 27 words; at most 20
conditions[1]: looks like a file path (Banner.tsx)
pros: 5 items; at most 3
```

One that still does not follow it is kept as prose with the position `unclear`, never dropped, and
its `problem` holds those lines (cut at 300 characters). An answer stored under the earlier, looser
limits is read as it was written. A message's
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
name conditions, `no` when every participant is against, and `unclear` otherwise. The `reason` is
one sentence of at most 20 words that counts each side and names nobody ("The participants differ:
1 for going ahead, 1 against and 1 cannot tell."); who cannot tell and who is missing are in
`unclear` and `missing`.

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
round's `synthesis`. `message_created` also carries `after_closed` and `ref_ticket`, and closing or
reopening a thread records `discussion_status_changed` with its `status` and `closed_at`.

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

A worker over `/mcp` reads a Ticket's files with the same `cards:read` scope: `read_ticket` names
the newest 50, `list_attachments` all of them, and `read_attachment` answers a `.txt`, `.md` or
`.json` file as text, a page of numbered lines at a time. Any other file is downloaded with the route
above; a tool never answers a binary file's bytes. No worker tool attaches a file.

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

### A Ticket's face for people

The face is what a person reads of a Ticket by default: the `summary` above and five fields beside
it, held to one template for every writer.

| Field | Limit |
| --- | --- |
| `summary` | at most 20 words |
| `why` | at most 3 sentences |
| `if_skipped` | at most 3 sentences |
| `pros` | at most 3 points |
| `cons` | at most 3 points |
| `steps` | 1 to 5 steps |

Every field is plain text: no code fence, code span, file path, file name, UUID, id or code symbol
(`snake_case`, `camelCase`, `()`, `::`, `->`, `=>`, `${`), and a step says what changes for the
person, never where in the code. A Ticket that needs more than five steps is split into two when
the RoadMap is written. The words and sentences are counted on the server
(`services/ticket_face.py`), never judged by a model.

- **The plan.** Each Ticket of a RoadMap (`PlanTicket`, the `roadmap_ai` payload) ends with
  `summary`, `why`, `if_skipped`, `pros`, `cons` and `steps`, and every Ticket must carry them: a
  candidate, `write_roadmap` and a generated RoadMap are checked whole, and approving the RoadMap
  publishes each card with its face. A plan stored before the face existed still parses and
  publishes cards without one.
- **The card.** `CardOut`, the search hits and `read_ticket` carry `face`: an object with
  `summary`, `why`, `if_skipped`, `pros`, `cons` and `steps`, or `null` for a Ticket written without
  one.
- **Writing it.** `POST .../cards` and `PATCH .../cards/{card_id}` take `why`, `if_skipped`,
  `pros`, `cons` and `steps`, each optional (at the boundary a text holds at most 400 characters, a
  point or step 140, a list 20 items). When a request gives any of them, the whole face is checked
  with the summary the request leaves; a request with every field empty removes the face. A
  person's `PATCH` is version-checked (`409 version_conflict`) and recorded in the activity log; a
  token's `PATCH` that gives a face field answers `403 human_action_required`, because a token
  changes a face through a new RoadMap revision. `create_ticket` takes the same optional fields.

A face that breaks the template answers `422 face_invalid` with one message per Ticket, field and
rule, the first five in the message: `details.errors` holds the messages ("Ticket PLN-023, steps:
7 items, at most 5. Split the Ticket into two."), `details.error_count` how many there were, and
`details.faces` one `{ticket_id, field, rule}` each. A RoadMap names its Tickets by the ids its
writer gave them, a card by its key, else by its quoted title; a list item is named from 0
(`steps[2]`). The rules are `missing`, `words`, `sentences`, `too_many`, `empty_item`,
`code_fence`, `code_span`, `file_path`, `id`, `finding_id` and `code_symbol`.

### A person's notes on a Ticket

A note is a person's own words on a Ticket, beside the plan: the Ticket view shows it under **Your
notes**, and `read_ticket` hands every note to a worker as `person_notes` (`author`, `written_at`,
`text`), apart from the description and the comments. A note holds 1 to 4 000 characters.

| Method | Path | Rule |
| --- | --- | --- |
| GET | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/notes` | `cards:read`; oldest first |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/notes` (`{text}`, `201`) | `cards:write`, a signed-in person only |
| PATCH | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/notes/{note_id}` (`{text, version}`) | `cards:write`, its author only |
| DELETE | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/notes/{note_id}` | `cards:write`, its author only |

A note answers `id`, `card_id`, `author` (the name when it was written), `author_actor_id`,
`written_at`, `updated_at`, `text` and `version`. The codes:

| Code | When |
| --- | --- |
| `403 human_action_required` | a token writes, edits or deletes a note, whatever its scopes |
| `403 note_author_only` | someone other than its author edits or deletes it |
| `404 note_not_found` | the note does not exist on that Ticket |
| `409 version_conflict` | the edit names a version that is no longer current |
| `409 loop_read_only` | the Loop is completed, cancelled or archived: a note is content, not a comment |
| `409 board_archived` | the board is archived |
| `409 loop_mismatch` | the Loop in the path does not own the Ticket |

Every write adds an activity entry on the card (the note's id and size, never its text) and a
`note_added`, `note_edited` or `note_deleted` event on the Ticket's event stream.

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
  (no blocker in the plan) and `blockers` stay as they were. In a Loop that was completed or
  cancelled, a Ticket that was never completed is `not_done`, whatever it waited for: the Loop is
  read-only, so nobody starts it, it waits for nobody and it never counts as done.
- `waiting_stop`: the line of the Loop's stop list the wait is for, as the list holds it, or
  `null` when the wait names none.
- `needs_person`: `state` `needs_input`, or `ready` with `human_action_required`.
- `awaiting_confirmation` and `confirmations`: a Ticket held up only by human-only Tickets a person
  has not confirmed is `ready` and may be completed; `awaiting_confirmation` is true while that
  holds, and `confirmations` names those Tickets (`id`, `key`, `title`). Completed, it is done,
  awaiting confirmation, until the person confirms them.
- `unreported_since`, computed on every read and never stored: when a key (an API token) took the
  Ticket and has not reported on it since, the time of that key's first move (the earliest, when
  several keys have); `null` otherwise, and always once the Ticket is completed. Taken and reported
  mean what they mean for `409 report_required` (under Cards below): the key moved the open Ticket
  and left it outside its Loop's first column in an open Loop, and its own comment or wait, at or
  after its first move, is its report. A person's move never sets it, and a Ticket a revoked key
  took stays marked until a person completes it, archives it or puts it back in the first column.
  The Loop's card list, a card read and every card write answer it, read once for all the Tickets
  of an answer; the board-wide Ticket list and the search answer `null`. The Kanban card shows it as
  *No report*, the Ticket view as "No report since" the date and time.

| Method | Path | Scope |
| --- | --- | --- |
| PATCH | `.../cards/{card_id}/workplace` (`version`, `workplace`) | `cards:write` |
| PATCH | `.../cards/{card_id}/wait` (`version`, `waiting_for` other than `nothing`, `reason`, optional `stop`) | `cards:write`; replacing another wait is a person's act (`403 human_action_required` for a token) |
| POST | `.../cards/{card_id}/wait/clear` (`version`) | `cards:write`, as a signed-in person, never a token (`403 human_action_required`) |

Each is version-checked (`409 version_conflict`), refused on a read-only Loop (`409 loop_read_only`)
and on a completed Ticket (`409 ticket_completed`); writing what the Ticket already says keeps the
version. A wait is for a real stop: `stop` names the line of the Loop's stop list it falls under,
by its text (trimmed, case-insensitive) or by its 1-based number, and is stored as `waiting_stop`;
a `stop` the list does not name is `422 not_a_stop` with the Loop's list in `details.stops`. A
wait without `stop` works as it always did, and the same wait again without it keeps the stop it
has. `POST .../cards` takes `workplace`, `waiting_for` and `waiting_reason` (required with a
wait). Completing a Ticket, or confirming a human-only one, while it waits answers
`409 ticket_waiting` naming the wait: a person clears it first. A RoadMap's planned Ticket may give
`workplace`, `waiting_for`, `waiting_reason` and `labels` (names the board has); the card it
publishes starts with them, and an unknown label in a handed-in RoadMap is refused with the names
there are. A board created without a template starts with the area labels of
`TRALALA_DEFAULT_LABELS` (Development, Architecture, UX, QA, Security, Operations, Documentation,
Data, Product, Business, Economy, Legal, Support, Communication, Research); existing boards keep
theirs.

### Ticket assignment

`PATCH /boards/{board_id}/loops/{loop_id}/cards/{card_id}` accepts `assignee_actor_id` (a human actor id or an
enabled registry agent id) or `clear_assignee: true`. The card stores the display name and type so
lists render without a cross-database join; every change is written to the activity log. Filter with
`GET .../cards?assignee=me|<actor-or-agent-id>|unassigned`.

### Lists (Loop-scoped: `/boards/{board_id}/loops/{loop_id}/lists`)

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards/{board_id}/loops/{loop_id}/lists?include_archived=` | `boards:read` |
| POST | `/boards/{board_id}/loops/{loop_id}/lists` | `cards:write` |
| GET | `/boards/{board_id}/loops/{loop_id}/lists/{list_id}` | `boards:read` |
| PATCH | `/boards/{board_id}/loops/{loop_id}/lists/{list_id}` | `cards:write` |
| POST | `/boards/{board_id}/loops/{loop_id}/lists/{list_id}/move` (`{"position": n}`) | `cards:write` |
| POST | `/boards/{board_id}/loops/{loop_id}/lists/{list_id}/archive` | `cards:write` |
| POST | `/boards/{board_id}/loops/{loop_id}/lists/{list_id}/restore` | `cards:write` |
| DELETE | `/boards/{board_id}/loops/{loop_id}/lists/{list_id}` (archived and empty) | `cards:write` |

### Cards (Loop-scoped: `/boards/{board_id}/loops/{loop_id}/cards`)

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards/{board_id}/loops/{loop_id}/cards` with `list_id\|q\|label\|priority\|due_before\|overdue\|completed\|include_archived\|sort\|order\|limit\|offset` | `cards:read` |
| POST | `/boards/{board_id}/loops/{loop_id}/cards` (`Idempotency-Key`) | `cards:write` |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/bulk` (`{"cards": [...]}`, max 100, partial failures, `Idempotency-Key`) | `cards:write` |
| GET | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}?include=checklists,comments` | `cards:read` |
| PATCH | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}` (requires `version`) | `cards:write` |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/move` (`version`, `list_id`, `position`) | `cards:write`; a key that has not reported on a Ticket it took is refused another one (`409 report_required`, below) |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/archive` | `cards:write` |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/restore` | `cards:write` |

A key (an API token) reports on a Ticket before it takes another one. A key has taken a Ticket when
it has moved it and the Ticket is still open (neither completed nor archived), in an open Loop and
outside its Loop's first column. Its report is a comment it wrote on the Ticket or a wait it set on
it, at or after its first move; a completed Ticket needs none. While such a Ticket on the board has
no report, the key's move of any other Ticket answers `409 report_required` and changes nothing:

```json
{
  "success": false,
  "error": {
    "code": "report_required",
    "message": "Report on the Tickets you took before you take another one",
    "retryable": false,
    "details": {
      "tickets": [
        { "id": "…", "key": "AC004-DA02-003", "title": "…", "loop_id": "…", "loop_key": "AC004", "taken_at": "2026-11-25T20:35:03Z" }
      ],
      "report": "A comment, a wait or a completion on the Ticket since you took it"
    }
  },
  "request_id": "…"
}
```

`taken_at` is when the key first moved that Ticket. Moving the same Ticket again, to any column, is
never refused, and neither is a move to the Loop's first column, which puts work back. A signed-in
person is never refused, and Tralala's own agents never move a Ticket. Each key is its own: another
key's Tickets never hold it back, and sessions that share one key share its Tickets.

### Labels, checklists, comments

| Method | Path | Scope |
| --- | --- | --- |
| GET/POST | `/boards/{board_id}/labels` | `cards:read` / `cards:write` |
| PATCH/DELETE | `/boards/{board_id}/labels/{label_id}` | `cards:write` |
| GET/POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/checklists` | `cards:read` / `cards:write` |
| PATCH/DELETE | `/boards/{board_id}/checklists/{checklist_id}` | `cards:write` |
| POST | `/boards/{board_id}/checklists/{checklist_id}/items` | `cards:write` |
| PATCH/DELETE | `/boards/{board_id}/checklist-items/{item_id}` | `cards:write` |
| GET/POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/comments` | `cards:read` / `comments:write` |
| PATCH/DELETE | `/boards/{board_id}/comments/{comment_id}` | `comments:write` (agents: own comments only) |
| GET | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/mentions` | `cards:read` |
| POST | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/mentions/{job_id}/retry` (`202`) | `comments:write` |
| GET | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/events` (`text/event-stream`) | `cards:read` |
| GET | `/boards/{board_id}/loops/{loop_id}/cards/{card_id}/events/history?after=&limit=` | `cards:read` |

Checklists follow the Ticket's Loop: a completed, archived or cancelled Loop refuses them
(`409 loop_read_only`). Comments do not: a Ticket of such a Loop still takes a comment, and its
comments may be edited and deleted, so a later Loop can point back at the work it replaced; only an
archived board refuses them (`409 board_archived`). A comment carries `after_loop_completed`, true
when it was written or last edited after its Loop was completed; the Loop's history snapshot, which
a later comment never changes, holds the comments as they were at completion.

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
MCP tools in revisions 2026-07-28 and 2025-06-18 (`tools/list` and `tools/call` in both; see
[The MCP endpoint](#the-mcp-endpoint)), and `/llms.txt` summarises it. The browser WebMCP adapter
is a separate surface for a person's own session and is not generated from this catalogue yet. A
tool is listed only when the calling token holds its scope, and `tools/call` re-checks it before
the handler runs.

| Tool | Scope | What it does |
| --- | --- | --- |
| `whoami` | `boards:read` | The calling key: its name, who issued it, when it expires (`days_left`, `expires_soon` under 7 days), the scopes it holds and the tools they open, each member scope it lacks with the tools that scope alone would open, the rule-11a decisions only a person makes, and `editor_decisions` (`installation_allows`, `key_has_right`); never the token or its hash |
| `list_boards` | `boards:read` | The boards the token may read, by name, with status and Loop count; a board id comes from here |
| `loop_summaries` | `loops:read` | One row per Loop of a board (open ones unless `include_completed`; `stage` narrows them): its goal cut to 280 characters, its stage, `without_plan`, `next` (what has to happen now, in one sentence) and `waiting_on` (`person`, `agent` for a document, `anyone` or `nobody`; a Ticket never waits on an agent), `execution_allowed`, its Tickets by state (`ready`, `needs_input`, `blocked`, `not_done`, `completed`, `total`, `needs_person`) and by column, each document's state and revision, `poc_decisions` (`open`, `built_on_open`, `missing_open`, `due`, `answered`; once every Ticket is done `next` also says how many wait for the person's review), and `decision_link`, the address of the decision a person takes next or `null` (below). Computed from what the Loop records, never written by anyone |
| `read_board` | `boards:read`, `loops:read` | The board's Loops by id, key, name and stage, the people you may assign, the agents you may ask |
| `read_loop` | `loops:read` | The Loop's overview, by its id or its key: goal and stage, `execution_allowed`, each document's state, revision, provenance and size (never its text), the Phases and the columns with their Ticket counts, the work outside the plan, the newest five notes cut to 500 characters, `stops` (`lines`, `is_default`: the Loop's stop list), `poc_decisions` (the counts `loop_summaries` gives) and the `decision_link` `loop_summaries` gives the Loop; the Tickets themselves are `list_tickets`' answer |
| `read_document` | `loops:read` | One document of a Loop named by its id or its key, by `kind` (`info`, `analysis`, `analysis_ai`, `roadmap`, `roadmap_ai`): as numbered lines, at most 60 000 characters, with `continue_from` for the rest; `analysis_ai` and `roadmap_ai` also as `view: structured`, an outline of the findings or the Phases and Tickets, and one of them in full with `item` |
| `read_ticket` | `cards:read` | The Ticket's `face` (its summary, why, if skipped, for and against and steps; `null` without one), summary (with `summary_source` and `summary_stale`), `person_notes` (a person's notes, oldest first: `author`, `written_at`, `text`), description, acceptance criteria, evidence, checklist, comments, column, version, `state`, `workplace`, `wait` (what it waits for, the reason, who set it and when, `stop` when the wait names one, and `decision_link`, where the person who answers clears it; `null` without one), the plan's `blockers`, `awaiting_confirmation` and `confirmations`, `poc_decisions` (`count`, `open` and `keys` of the records taken on it), `needs_person`, `decision_link` (where a person confirms a person's task, else `null`), `attachments` (the newest 50 files, one row each: `id`, `filename`, `content_type`, `size_bytes`, `uploaded_at` and `text`) with `attachment_count`, and `allowed_actions` (only `comment_ticket` in a completed, archived or cancelled Loop) |
| `list_attachments` | `cards:read` | Every live file of one Ticket, newest first, in the rows `read_ticket` shows; `text` is true for `.txt`, `.md` and `.json`. `next_step` names `read_attachment` for a text file and the download route for the rest |
| `read_attachment` | `cards:read` | One file by `attachment_id`. A text file answers as numbered lines by `read_document`'s rule: at most 60 000 characters a page, `lines`, `text` and `continue_from` (the next `start_line`); a file whose bytes are not UTF-8 is refused with `422 attachment_not_text` naming it. Any other file answers its metadata, `text: false` and `download`, the route that answers its bytes with the same key; no tool answer carries a binary file |
| `search_tickets` | `cards:read` | Tickets by words in one Loop, a board's open Loops or every active board, each with board, Loop key, key and column |
| `list_tickets` | `cards:read`, `loops:read` | Which Tickets there are and where each stands, never what one says: id, key, title, Loop key, column, Phase, `state`, `workplace`, `human_action_required`, assignee and `completed` (`fields: brief` keeps id, key and title). Column by column, then by Phase and key. Filters: `loop_id` (an id or a key), `column` (names), `assignee` (`me`, `none` or an id), `phase`, `state` (one or more of `ready`, `needs_input`, `blocked`, `not_done`), `workplace`, `waiting_for`, `needs_person`, `human_action_required`, `label`, `priority`, `due_before`, `overdue`, `summary` (`missing` or `stale`), `query`; completed Tickets and Loops only with `include_completed`. The answer repeats the filters, maps each Loop key to its id and pages with `limit` (at most 200) and `continue_from`; an unknown column is refused with the column names there are, and an empty answer's `next_step` names the filters it applied and how to widen it. Work for a coding session: `workplace: codebase`, `state: ready`, `human_action_required: false`; what needs a person: `needs_person: true` |
| `write_ticket_summaries` | `cards:write` | Write up to 100 Ticket summaries; each is a versioned edit that reads the version itself and retries once on a race, and each Ticket answers `written` or its refusal |
| `set_ticket_wait` | `cards:write` | Stop an open Ticket that waits for nothing for a real stop: what it waits for (`decision`, `information`, `access` or `third_party`), why (`reason`) and, optionally, `stop`, the line of the Loop's stop list (its text or its number); the version is read for the caller. With a stop the answer's `wait` carries `stop`; a `stop` the list does not name is `422 not_a_stop` with `details.stops` and `details.use_instead` (`record_poc_decision`, `report_missing`). Clearing or replacing a wait is a person's act and never a tool: on a Ticket that already waits the call answers `403 human_action_required` with `decision_link`, where the person clears that wait |
| `record_poc_decision` | `cards:write` | Record a POC decision on a Loop (by its id or its key) through the record route: `title`, `chosen`, `reason`, `alternative`, `change_path`, optional `card_id`, `builds_on` and `details`. Answers `id`, `key`, `kind`, `status`, `card_id`, `ticket_key`, `built_on`, `deduplicated` and `next_step` (go on: nothing waits for it). `422 poc_decision_invalid` names each field and rule under the argument sent |
| `report_missing` | `cards:write` | Record something missing from a person: `title`, `missing`, `reason`, `went_around` (stored as `chosen`), `when_provided` (stored as `change_path`), optional `card_id`, `builds_on` and `details`; the answer and the refusal as `record_poc_decision`'s, a refusal naming `went_around` and `when_provided` |
| `list_poc_decisions` | `cards:read` | The Loop's records in review order, narrowed by `card_id` or `status`: each with `id`, `key`, `kind`, `title`, its text fields (`chosen`, `reason`, `alternative`, `change_path` for a decision; `missing`, `reason`, `went_around`, `when_provided` for something missing), `builds_on`, `card_id`, `ticket_key`, `status`, `due`, `feedback`, `feedback_ticket`, `answered_by`, `answered_at`, `created_by`, `created_at` and `has_details` (`details` itself with `include_details`), plus `counts` and `next_step` |
| `assign_ticket` | `cards:write` | Set or clear the owner; the current version is read for the caller |
| `move_ticket` | `cards:write` | Move to another column by id or name; the version is read and one retry absorbs a race. A key that has not reported on another Ticket it took is refused with `409 report_required` naming those Tickets, as the move route is, and the refusal is never retried |
| `create_ticket` | `cards:write`, `comments:write` | Add a Ticket outside the plan while the Loop executes, or to a Loop without a plan, where the first one starts the fast track ([A Loop without a plan](#a-loop-without-a-plan)); in its first column, keyed `<LoopKey>-UNP-<nnn>`, with an optional `summary`, face (`why`, `if_skipped`, `pros`, `cons`, `steps`; any one given checks the whole face, `422 face_invalid`), `workplace`, `waiting_for` with `waiting_reason`, and `labels` the board has (an unknown one is refused with the names there are, never created); `follow_up_of` prefixes the description and comments on the origin Ticket; the same request again answers the first Ticket |
| `comment_ticket` | `comments:write` | Add a progress note, finding or blocker, on an open or a completed Ticket, in a completed, archived or cancelled Loop too (a later Loop can point back at the work it replaced); only an archived board refuses it (`409 board_archived`) |
| `complete_ticket` | `cards:write`, `comments:write` | Complete a Ticket (`completed: true`, the version read for the caller, one retry on a race), then comment the summary and the evidence as a list; answers the key, version, comment id and the Loop's stage and progress. The summary is kept as a comment even on a Ticket that is already done or whose completion is refused; the refusal carries its `comment_id`. A human-only Ticket answers `403 human_action_required` with `decision_link`, where a person confirms it. A completed, archived or cancelled Loop refuses the call whole (`409 loop_read_only`, nothing written) |
| `create_loop` | `loops:write` | Start a Loop on a board for one coherent change |
| `write_info` | `loops:write` | Write the agreed intent; allowed while the Loop is `draft` or `analysis_review`, so not in a Loop without a plan once it has a Ticket; later refused with `403 human_action_required` and `decision_link`, the Info in the Plan tab |
| `write_note` | `loops:write` | Add a note to the Loop's log: what belongs to the Loop and to no single Ticket; refused on a completed Loop |
| `read_notes` | `loops:read` | The Loop's notes, oldest first, a page at a time (`older` is the next `before`) |
| `run_analysis` | `loops:generate` | Ask a board agent for the Analysis candidate and report the run and the document state |
| `write_analysis` | `loops:generate` | Hand in the worker's own analysis through the candidate route; schema errors answer one `loc: message` line each. The answer's `decision_link` is the analysis in the Plan tab, where a person reviews it. Over an approved analysis `403 human_action_required` with `decision_link`, the analysis in the Plan tab |
| `run_roadmap` | `loops:generate` | Ask for the RoadMap candidate once the analysis is approved |
| `write_roadmap` | `loops:generate` | Hand in the worker's own RoadMap; Phase and Ticket ids that are not UUIDs become `uuid5` of the Loop and the id, returned as `id_map`. Every Ticket carries its face, or the RoadMap answers `422 face_invalid` naming each Ticket, field and rule. The answer's `decision_link` is the RoadMap in the Plan tab, where a person reviews it. Both take an optional `brief`, stored as the human view instead of asking a board agent; an analysis brief that breaks the sign answers `422 brief_invalid`. Over an approved RoadMap `403 human_action_required` with `decision_link`, the RoadMap in the Plan tab |
| `write_brief` | `loops:generate` | Write the brief for people (`kind`: `analysis` or `roadmap`) of the current technical revision; refused over a current approval (`403 human_action_required` with `decision_link`, that document in the Plan tab); an analysis brief keeps the sign (`422 brief_invalid`) |
| `ask_person` | `loops:read`, `cards:read` | Ask the key's person for one decision (`decision`: `analysis`, `roadmap`, `implementation` or `qa` on the Loop, `wait` or `confirmation` on a Ticket with `card_id`) and report it. Answers `not_pending` with `why` when nothing waits; in MCP 2026-07-28 with the elicitation mode `url` declared and `TRALALA_PUBLIC_URL` set, `resultType: input_required` (below); otherwise `waiting_for_person` with `decision_link`. With `editor_decisions` on, `loops:decide` on the key and the mode `form` declared, the analysis, the RoadMap, a wait, a confirmation and the implementation of a Loop with a plan come as a form the person answers in their editor, never the agent (below). The repeated call with `requestState` answers `decided` (`outcome`, `decided_by`, `decided_by_id`, `decided_at`, and `taken_through` for a form), `declined`, `cancelled`, `not_decided` or `input_required` again |
| `ask_agents` | `discussions:write` | Create a `roundtable` discussion with the board's askable agents (or `agent_ids`; at most 12) on the Ticket (`card_id`) or, without one, on the board under a `title`, and run one round; returns the synthesis, the positions and the structured answers, which the person sees as the sign; with `background` it answers at once with the `discussion_id` and `next_step`; without an askable agent `422 no_agents_available` |
| `read_discussion` | `discussions:read` | Read a thread: its `title`, `state` (`open` or `closed`) and `closed_at`, the newest round's synthesis, each agent's position and the messages with their structured answers, `after_closed` and `ref_ticket` (the reasoning, which the person reads as raw text, with `include_prose`); sets the caller's read marker |
| `reply_discussion` | `discussions:write` | Post a message, in a closed thread too (`after_closed`), optionally pointing at a `ticket` (id or key); a round runs by default in a thread on a Ticket and only with `run: true` on the board, and never in a thread without agents or one that is closed, cancelled, approved or vetoed, where `run_skipped` (`no_participants`, `thread_closed`, `thread_decided`) says why; `background` as for `ask_agents` |
| `open_discussion` | `discussions:write` | Open a discussion on the board with a `title`, the `question` and an optional `ticket` it points at: no agent and no round; others answer with `reply_discussion` |
| `list_discussions` | `discussions:read` | A board's threads, newest activity first, never their text: `scope` (`board`, `ticket`), `state` (`open`, `closed`), `unread`, `mine` and `limit` (50, at most 100); each row with its id, title, status, state, Ticket, opener, `opened_by_me`, last activity, message count and `unread`, and `more` |
| `close_discussion` | `discussions:write` | Close a thread the caller opened; anyone else `403 not_opener` |
| `reopen_discussion` | `discussions:write` | Open a closed thread again; the opener or a signed-in person, another key `403 not_opener` |

Every successful tool answer carries `notices` when a discussion waits for the key, read on the
call's `board_id` (every board that is not archived for `whoami` and `list_boards`, with
`boards:read`) and only with `discussions:read`: `{count, threads, more, next_step}`, at most five
threads `{discussion_id, board_id, title, reason}` newest activity first, the title cut to 80
characters and never a message's text. `reason` is `comment_after_close`, `answer`, `run_failed`
or `open_question`; [Agent usage](Agent_usage.md) gives each rule. A thread leaves once the key
reads it with `read_discussion`. Reading the notices never fails the tool: a failure is logged
(`tool_notices_failed`) and the answer goes out without them.

What waits for a person carries `decision_link`, the address of the tab, dialog or button in the
web UI where that person takes the decision. It is a path inside Tralala, or a full address on
`TRALALA_PUBLIC_URL` when the installation sets one (`https://tralala.example.com/boards/...`); the
server never takes the host from a request's `Host` or `X-Forwarded-*` headers. Every address is
built from the ids of the rows the services read, never from a key:

| Decision | Address | Where a tool gives it |
| --- | --- | --- |
| Review the analysis | `/boards/{board_id}/loops/{loop_id}?tab=plan&doc=analysis` | `loop_summaries` and `read_loop` while a person reviews it (`analysis_review`); `write_analysis` when it hands one in for review; `write_analysis` and `write_brief` refused over an approved analysis |
| Review the RoadMap | `/boards/{board_id}/loops/{loop_id}?tab=plan&doc=roadmap` | `loop_summaries` and `read_loop` while a person reviews it (`roadmap_review`, or `planning` once one is handed in); `write_roadmap` when it hands one in for review; `write_roadmap` and `write_brief` refused over an approved RoadMap |
| Accept the implementation | `/boards/{board_id}/loops/{loop_id}?dialog=completion` | `loop_summaries` and `read_loop` once every Ticket is done, in a Loop without a plan too, which this one decision closes |
| Accept or reject QA | `/boards/{board_id}/loops/{loop_id}?dialog=completion` | `loop_summaries` and `read_loop` in `awaiting_qa` |
| Edit the Info | `/boards/{board_id}/loops/{loop_id}?tab=plan&doc=info` | `write_info` refused once planning has started |
| Clear a wait | `/boards/{board_id}/loops/{loop_id}/tickets/{card_id}?focus=clear-wait` | `read_ticket` under `wait`; `set_ticket_wait` refused on a Ticket that already waits |
| Confirm a person's task | `/boards/{board_id}/loops/{loop_id}/tickets/{card_id}?focus=confirm` | `read_ticket` on the Ticket; `complete_ticket` refused on a human-only Ticket |

`loop_summaries` and `read_loop` answer the same address from the same rule, and `null` when the
next step is anyone's, an agent's or nobody's, or a person's step that is no single decision of the
Loop: writing the Info, answering a Ticket's wait or doing a person's task, which `read_ticket`
links. `read_ticket`'s two addresses are `null` once the Ticket is done or archived, or its Loop is
completed, cancelled or archived. A refusal keeps its code, `403 human_action_required`, adds
`details.decision_link` and ends its message with where the person decides and the address:

```json
{
  "error": {
    "code": "human_action_required",
    "message": "K-2 is work for a person, and your summary is saved as a comment on the Ticket. Grace confirms it on the Ticket's page: /boards/…/loops/…/tickets/…?focus=confirm",
    "details": {
      "action": "Confirming K-2",
      "actor_type": "agent",
      "comment_id": "…",
      "ticket_key": "K-2",
      "confirmed_by": "Grace",
      "human_instructions": "Sign the contract",
      "decision_link": "/boards/…/loops/…/tickets/…?focus=confirm"
    },
    "retryable": false
  }
}
```

`ask_person` asks for a decision. In MCP 2026-07-28, when the request declares
the elicitation mode `url` (`clientCapabilities.elicitation.url`) and the installation sets
`TRALALA_PUBLIC_URL`, a decision that waits answers `input_required`, with the full address of the
decision, which carries only ids:

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "result": {
    "resultType": "input_required",
    "inputRequests": {
      "decision": {
        "method": "elicitation/create",
        "params": {
          "mode": "url",
          "message": "Open Tralala to approve the analysis of BE007 or ask for changes.",
          "url": "https://tralala.example.com/boards/…/loops/…?tab=plan&doc=analysis"
        }
      }
    },
    "requestState": "…",
    "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "tralala", "version": "1.0.0"}}
  }
}
```

The client repeats the call with `inputResponses` (`{"decision": {"action": "accept"}}`, or
`decline`, or `cancel`) and the same `requestState`. Only `tools/call` of this tool answers
`input_required`, and only in 2026-07-28; a call of 2025-06-18, a client without the `url` mode or
an installation without its public address gets `status: waiting_for_person` and `decision_link`
instead. The state is sealed with the installation's secret and
bound to the key, the call and what the question was about; it is valid for 15 minutes and opens
once. A state that is changed, expired, another key's, for another call, used before or out of
date answers JSON-RPC `-32602` with HTTP 200 and `data.reason`, and nothing about the decision:
call again without `requestState`.

Deciding in the editor is the opt-in mode `form`. It is used only when the request declares
`clientCapabilities.elicitation.form` (or an empty `elicitation`, which the revision reads as
form), the installation's setting `TRALALA_EDITOR_DECISIONS` is on and the key holds
`loops:decide`; and only for `analysis`, `roadmap`, `wait`, `confirmation` and the
`implementation` of a Loop with a plan. QA, a reset and closing a Loop keep the link. The request
is a flat form with no address in it, for the person to answer in their editor. An agent must never
answer it itself, by any route; Tralala cannot tell who sent the answer:

```json
{
  "method": "elicitation/create",
  "params": {
    "mode": "form",
    "message": "Approve revision 3 of the analysis of BE007, or ask for changes. Answer this yourself: an agent must never fill it in, and Tralala cannot tell who answered. Your answer is recorded as your decision, taken in a coding session through this key.",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "decision": {
          "type": "string",
          "title": "Your decision",
          "oneOf": [
            {"const": "approve", "title": "Approve"},
            {"const": "request_changes", "title": "Ask for changes"}
          ]
        },
        "feedback": {
          "type": "string",
          "title": "Feedback",
          "description": "Optional: what you want changed or want the agent to know.",
          "maxLength": 500
        }
      },
      "required": ["decision"]
    }
  }
}
```

The choices are `approve` and `request_changes` for a review, `clear` and `keep` for a wait,
`confirm` and `not_yet` for a person's task, `accept` and `reject` for the implementation. The
repeated call with `{"decision": {"action": "accept", "content": {"decision": "approve"}}}` and
the state takes the decision as the key's owner, through the same service method as the route:
the setting, the right on the key and the owner's account are checked again on that call
(`403 human_action_required` with `details.reason` `editor_decisions_off`, `no_right` or
`owner_disabled` otherwise), the revisions, the Ticket's version or the Loop's version the
question was about must still be in force, and content that is not the form's is asked again
(`input_required` with what holds now). The answer is `status: decided` with `taken_through`, the
key's name; `keep`, `not_yet` and `reject` take nothing (`status: not_decided`). A decision the
service refuses at that moment with a `409` (a board agent writing the brief for people,
`generation_in_progress`) is not taken either: `status: not_taken` with its `code` and `why`, and
the question stays open. The decision's
history row carries `taken_through` (`{credential_id, key_name, via: "form"}`) beside
`asked_through`, and so does the implementation's approval row and the `loop.plan_published` row
of a RoadMap approved so; a decision on a Ticket gets one comment saying it was decided in a coding
session through that key. `GET …/documents` gives each current approval the same `taken_through`
and `asked_through`, read from those rows when it answers.

The flow a person and their worker use to plan is `create_loop` → `write_info` → `write_analysis`
(or `run_analysis`) → the person approves the analysis → `write_roadmap` (or `run_roadmap`) → the
person approves the RoadMap, which publishes its Tickets with their keys. To work them:
`list_tickets` → `read_ticket` → `move_ticket` and `comment_ticket` → `set_ticket_wait` when an
answer is needed → `complete_ticket`; `create_ticket` for a follow-up outside the plan and
`write_note` for what belongs to the Loop. A small change skips the plan: `create_loop` →
`create_ticket` → the same work on its Tickets → a person closes the Loop in one decision. Every
step stays inside the same gates: the analysis and the RoadMap are candidates until a signed-in
person approves them, and a cancelled or completed
Loop is read-only but for comments on its Tickets. The Loop is the plan: nothing a worker plans or
logs is a file in a repository.

Deliberately absent: board and list structure changes, planned Ticket creation or archiving,
publishing or editing an approved RoadMap, QA decisions, attaching a file, provider configuration,
keys, and every rule-11a decision (approving or resetting a scope, editing Info once planning has
started, confirming a human-only Ticket, clearing a Ticket's wait, accepting the implementation or
QA, finalizing a Loop).

### The MCP endpoint

`POST /mcp` speaks two MCP revisions on the one address, 2026-07-28 and 2025-06-18, over
Streamable HTTP: one JSON-RPC 2.0 request per POST and one JSON answer (`application/json`), with
no session and no stream in either. [Agent_usage.md](Agent_usage.md#2-connect) says how a client
connects.

Each request is judged by itself, since there is no session to remember a handshake by:

- `initialize` is revision 2025-06-18;
- a request with `io.modelcontextprotocol/protocolVersion` in `params._meta` follows the version
  it names there: 2025-06-18 is the older revision, and any other is revision 2026-07-28, whose
  rules refuse a version neither revision speaks;
- any other request is revision 2026-07-28 when its `MCP-Protocol-Version` header is
  `2026-07-28`, and 2025-06-18 otherwise, with that header or without it.

#### Revision 2026-07-28

This revision has no handshake. Every request carries these, and the server compares each header
with the body:

| Where | What |
| --- | --- |
| `params._meta` | `io.modelcontextprotocol/protocolVersion`, the string `"2026-07-28"`, and `io.modelcontextprotocol/clientCapabilities`, an object (`{}` when the client declares none). `io.modelcontextprotocol/clientInfo` is optional and never identifies anyone; the key does |
| `MCP-Protocol-Version` header | `2026-07-28`, the version in `_meta` |
| `Mcp-Method` header | the request's `method`, exactly |
| `Mcp-Name` header | on `tools/call` only: `params.name`, or `=?base64?…?=` (the name's UTF-8 in Base64) for a name that is not plain ASCII |

A client also sends `Accept: application/json, text/event-stream`; every answer with a body is
JSON. The three methods:

| Method | Result |
| --- | --- |
| `server/discover` | `supportedVersions` (`["2026-07-28", "2025-06-18"]`), `capabilities` (`{"tools": {"listChanged": false}}`), `instructions` (how to start, the same text for every key) and the caching hints `ttlMs` (one hour) and `cacheScope: public` |
| `tools/list` | `tools`: every tool the key's scopes open, each with `name`, `description` and `inputSchema`, in the catalogue's order; `ttlMs` (five minutes) and `cacheScope: private`, because the list depends on the key |
| `tools/call` | the tool's answer as `structuredContent` and as one text item in `content` (its JSON), with `isError: false`; a refusal by the tool's service is a result too, with `isError: true` and the error's `code`, `message`, `details` and `retryable` as the text |

Every result carries `resultType: "complete"` (no tool asks the client for input yet) and `_meta`
with `io.modelcontextprotocol/serverInfo` (`name`, `version`). An `id` is a string or an integer
and comes back unchanged.

Before the body is read, the key is checked and the rate limit applied as on every REST route,
and those refusals (`401`, `429`) are the REST envelope; so is `413 payload_too_large` for a body
over `TRALALA_MAX_REQUEST_BYTES`. The rest are JSON-RPC answers, checked in this order, and the
first rule a request breaks answers it:

| HTTP | Code | When |
| --- | --- | --- |
| `403` | `-32600` | An `Origin` header is present and is neither in `TRALALA_CORS_ORIGINS` nor the origin of `TRALALA_PUBLIC_URL`, against DNS rebinding (the answer has no `id`). A request without `Origin` passes |
| `400` | `-32700` | The body is not JSON |
| `400` | `-32600` | The body is not one JSON-RPC 2.0 request or notification, or a request has no method or an `id` that is neither a string nor an integer |
| `202` | none | A notification (no `id`): accepted with no body, since this revision defines none to act on |
| `400` | `-32602` | `params` is not an object with `_meta`, or `_meta` lacks the version (a string) or the client's capabilities (an object) |
| `400` | `-32022` | A version in `_meta` that neither revision speaks: "Unsupported protocol version: Tralala speaks MCP 2026-07-28, and MCP 2025-06-18 after initialize", with `data.supported` (both versions) and `data.requested` |
| `400` | `-32020` | `MCP-Protocol-Version` or `Mcp-Method` is missing, repeated, holds characters a header may not, or differs from the body |
| `404` | `-32601` | Any method but the three above, `ping` and `subscriptions/listen` among them |
| `200` | `-32602` | On `tools/call`: `params.name` is not a string, or `arguments` is not an object |
| `400` | `-32020` | On `tools/call`: `Mcp-Name` is missing, repeated or malformed, or differs from `params.name` |
| `200` | `-32602` | On `tools/call`: `inputResponses` or `requestState` has the wrong type, the tool is unknown (`Unknown tool: …`) or the key lacks its scope (`Missing required scope: …`) |

#### Revision 2025-06-18

A client of this revision opens with `initialize` and then sends `MCP-Protocol-Version: 2025-06-18`
on every request, with no `_meta` version and none of the other MCP headers; a request without the
version header is served as 2025-06-18 too. The methods:

| Method | Result |
| --- | --- |
| `initialize` | `protocolVersion` (`"2025-06-18"`, whatever version the client asked for), `capabilities` (`{"tools": {"listChanged": false}}`), `serverInfo` (`name`, `version`) and `instructions`, the same text `server/discover` gives |
| `ping` | an empty result |
| `tools/list` | `tools`: every tool the key's scopes open, as in revision 2026-07-28, without the caching hints |
| `tools/call` | the tool's answer as in revision 2026-07-28 |

A result has no `resultType` and no `_meta`. Before the body is read the same `401`, `429`, `413`,
`403` and `-32700` apply, and then:

| HTTP | Code | When |
| --- | --- | --- |
| `400` | `-32600` | The body is not one JSON-RPC 2.0 request or notification |
| `202` | none | A notification (no `id`), `notifications/initialized` among them |
| `400` | `-32022` | The `MCP-Protocol-Version` header names a version neither revision speaks, with the same message and `data` as above |
| `200` | `-32602` | On `tools/call`: `params` is not an object, `params.name` is not a string, `arguments` is not an object, the tool is unknown or the key lacks its scope |
| `200` | `-32601` | Any method but the four above |

#### Both revisions

`GET` and `DELETE` answer `405` with `Allow: POST` and `-32600`: Tralala opens no stream and keeps
no session. An `Mcp-Session-Id` or `Last-Event-ID` header is ignored, and no session id is ever
sent, not even in the answer to `initialize`. The tools never change while the server runs (`listChanged: false`), so there is no
change stream: a client keeps the list it read. A page in a browser on another origin cannot call
`/mcp` today, because the server's CORS settings do not allow the MCP headers.

### Work outside the plan

`POST .../loops/{loop_id}/cards` in a Loop that executes a plan (`ready`, `in_progress` or
`awaiting_qa`), and the `create_ticket` tool, add a Ticket outside the plan: it is keyed
`<LoopKey>-UNP-<nnn>`, starts in the column it names (the tool takes the first one), never blocks a
Phase, the plan's readiness or the Loop's completion, and is listed under `unplanned` in readiness
and `unplanned_tickets` in `read_loop`. Accepting the implementation names the ones still open.
A Loop that has a plan but is not executing it refuses a new Ticket with
`409 plan_change_required`. A Loop without a plan takes one, keyed the same way, and one that has
no analysis or RoadMap either then runs its Tickets without a plan
([A Loop without a plan](#a-loop-without-a-plan)).

### Completion

A Ticket is completed by an explicit completion (`PATCH .../cards/{card_id}` with `completed: true`
and its `version`, or the `complete_ticket` tool), which passes the same readiness rules as the
plan: an unfinished prerequisite answers `409 ticket_blocked`, an open wait `409 ticket_waiting`
naming it, and a human-only Ticket `403 human_action_required` for a token (a person confirms it
with `POST .../cards/{card_id}/confirm`). Work completes only while the Loop executes an approved
plan: in another stage the answer is `409 approval_required`, or `409 plan_change_required` while
the plan is being replaced. A Loop without a plan has no plan to wait for, so its Tickets complete
whenever they are ready. Moving a Ticket into a column named `Done` completes nothing. A
completed, archived or cancelled Loop refuses a completion with `409 loop_read_only`.

Accepting the implementation (`POST .../completion`, a person only) is refused while a delivery
Ticket is not completed: `409 ticket_blocked`, with the Tickets under `details.open`. Readiness
lists the same Tickets as `open_delivery`: every Ticket a plan published that is not completed, an
archived one and one an earlier plan left on the Kanban included. With `accept_unfinished: true`
the person accepts without them. Nothing is changed on those Tickets: the decision records their
keys (`unfinished`), the Loop's activity names them (`loop.accepted_unfinished`), the answer lists
them as `unfinished`, and once the Loop is completed each one that is still not completed reads
`state: not_done`. The history snapshot keeps them with the disposition `open`. In a Loop without a
plan the same decision closes the Loop, its own open Tickets take the place of the delivery
Tickets, and the snapshot keeps them as `not_done` ([A Loop without a plan](#a-loop-without-a-plan)).

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
POST /api/v1/boards/{board_id}/loops/{loop_id}/cards
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
