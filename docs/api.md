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
`idempotency_key_reused`, `creation_in_progress`, `creation_failed`, `validation_failed`,
`payload_too_large`, `rate_limited`, and the Loop workflow codes `loop_not_found`,
`loop_required`, `loop_mismatch`, `loop_read_only`, `document_stale`, `approval_required`,
`human_action_required`, `invalid_dependency_graph`, `ticket_blocked`, `plan_change_required`,
`generation_input_changed`, `generation_unavailable`, `generation_in_progress`, `qa_incomplete`.

Human-only decisions (analysis approval, RoadMap approval, confirming a human-only Ticket,
accepting QA and finalizing a Loop) reject agent tokens with `403 human_action_required` even when
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
| GET | `/meta` | API version, `scopes`, `token_scopes` (the subset a token may hold), `member_token_scopes` and `member_token_limits` (what a person may grant themselves), feature flags (authenticated) |

### Auth and credentials

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/auth/login` | public; throttled per username and client address |
| POST | `/auth/enrol` (`{"token","password"}`) | public; claims an invitation link, sets the password and starts a session |
| POST | `/auth/logout` | authenticated; revokes the stored session |
| POST | `/auth/password` | authenticated user; revokes every session |
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
| POST | `/credentials` | signed-in person; an admin may grant any grantable scope, a member only `member_token_scopes` |
| POST | `/credentials/{id}/rotate` | the owner or `credentials:admin`; issues a new token and revokes the old one |
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
the operator delivers the link. See
[decisions/0014](decisions/0014-enrolment-links-instead-of-email-verification.md).

Logins are rate limited per client address and backed off per username after repeated failures
(`429 rate_limited` with `details.retry_after_seconds`). Passwords must be at least
`TRALALA_PASSWORD_MIN_LENGTH` characters (default 8) and are never accepted when they equal the
username.

### Boards

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/boards?q=&status=&sort=&order=&limit=&offset=` | `boards:read` |
| POST | `/boards` (`Idempotency-Key` supported) | `boards:write` |
| GET | `/boards/{board_id}` | `boards:read` |
| PATCH | `/boards/{board_id}` | `boards:write` |
| POST | `/boards/{board_id}/archive` | `boards:write` |
| POST | `/boards/{board_id}/restore` | `boards:write` |
| POST | `/boards/{board_id}/duplicate` | `boards:write` |
| DELETE | `/boards/{board_id}` (body `{"confirm_name": "…"}`, board must be archived) | `boards:admin` |
| GET | `/boards/{board_id}/export` | `boards:write` — `application/zip` |
| POST | `/boards/import` (raw zip body) | `boards:admin` |
| GET | `/boards/{board_id}/validate` | `boards:read` |
| POST | `/boards/{board_id}/migrate` (retry a failed schema migration) | `boards:admin` |
| GET | `/boards/{board_id}/actors` (`people` to assign, `agents` to ask) | `boards:read` |
| GET/POST | `/boards/{board_id}/backups` | `boards:read` / `boards:write` |
| POST | `/boards/{board_id}/backups/{name}/restore` (verifies the backup before replacing data) | `boards:admin` |
| POST | `/boards/{board_id}/templates` (`{"name","description"}`; snapshots the board's lists and labels) | `boards:write` |

`POST /boards` accepts an optional `template_id`. When present, the template's description, list
names and labels are applied; an explicit `description` or `lists` in the payload wins. A missing
template is rejected with `422 validation_failed` before any board row is written, so an
`Idempotency-Key` can be reused after correcting the request.

`POST` and `PATCH /boards` accept `repository_ids: [uuid]`: the set of GitHub repositories the board
is about. The list replaces the board's previous selection (an empty list detaches every
repository); an unknown id is rejected with `404 repository_not_found` before anything is written.
Every `BoardOut` carries `repository_ids`, which is what the create/edit dialogs show as checkboxes.

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
| POST | `/boards/{board_id}/loops/{loop_id}/candidates` | Submits an analysis or RoadMap candidate; validation only, never approval |
| POST | `/boards/{board_id}/loops/{loop_id}/reviews/analysis` | Human-only decision bound to exact revision ids |
| POST | `/boards/{board_id}/loops/{loop_id}/reviews/roadmap` | Human-only; publishes the plan atomically |
| GET | `/boards/{board_id}/loops/{loop_id}/plan` | Active plan with phases and readiness |
| GET | `/boards/{board_id}/loops/{loop_id}/agents` | The agent this Loop prefers per purpose |
| PUT | `/boards/{board_id}/loops/{loop_id}/agents` | Sets that preference (`boards:write`; omitted field keeps its value, `null` clears) |
| GET | `/boards/{board_id}/loops/{loop_id}/readiness` | Machine-readable blockers and human gates |
| GET | `/boards/{board_id}/loops/{loop_id}/context` | Bounded, versioned context plus output schemas |
| POST | `/boards/{board_id}/loops/{loop_id}/generation-runs` | Starts an analysis, RoadMap or QA run (`202`); `Idempotency-Key` supported |
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
| DELETE | `/repositories/{id}` | `boards:admin` |

Repositories are a registry-level list, managed from **Settings -> GitHub repositories**
(`/settings/repositories`). A repository is never owned by a board: boards select the ones they are
about with `repository_ids`, so one repository can serve several boards and a board can list several
(it resolves to `board_repositories`). The token is a fine-grained personal access token with
`Contents: read` for that repository; it is sealed with the same mechanism as provider keys,
returned only as `has_token`/`token_hint`, never logged, and re-sealed when the session secret
rotates. `check` reports `ok`, `unauthorized`, `not_found`, `forbidden`, `branch_missing` or
`unreachable` and stores the last outcome on the record. See
[decisions/0011](decisions/0011-repository-access-for-analysis-agents.md).

`GET /repositories` and `GET /repositories/{id}` are readable with `boards:read`, but a caller without
`boards:admin` gets the entry without `token_hint`, `last_checked_at`, `last_check_status` and
`last_check_detail`: the list stays usable for board dialogs while credential hints and access-check
history remain administration detail.

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
SSH deploy key (`ssh-keygen`) grants a *git client* read access; Tralala reads the REST API over
HTTPS and runs no git binary, so a deploy key is not an alternative for this field.

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
| DELETE | `/agents/{id}` | `agents:admin` |

An agent needs either `role_template_id` or `role_prompt_override`. `connection_type` is
`openai_compatible` or `a2a`. Base URLs are validated: `http`/`https` only, no embedded
credentials, no cloud-metadata or link-local targets, no redirect following; private/loopback
targets are allowed because local model servers are the primary use case
(`TRALALA_AGENTS_ALLOW_PRIVATE_ENDPOINTS`).

API keys are sealed with Fernet (HKDF-derived from the install secret). Responses expose only
`has_api_key` and a `••••ab12` hint — never the key itself. `/agents/directory` is the autocomplete
projection: enabled agents with `id`, `name` and role only, no endpoint, model or credential hint.

`POST /agents/{id}/test` probes `GET {base_url}/models` for OpenAI-compatible endpoints and the A2A
agent card (`/.well-known/agent.json`) for `a2a`, then records `last_test_status`,
`last_test_message` and `last_tested_at`.

**Role snapshot rule:** `role_templates` and `agents` are separate resources. Editing a template
changes *future* work; every discussion persists `AgentService.role_snapshot(...)` (template id and
name, template `updated_at`, effective prompt, SHA-256, timestamp) so history stays explainable. See
[decisions/0001](decisions/0001-role-template-vs-agent-snapshot.md).

### Discussions

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/discussions/overview` (one entrance per board, newest discussion activity first) | `boards:read` + `discussions:read` |
| GET | `/boards/{board_id}/discussions?status=&limit=` | `discussions:read` |
| POST | `/boards/{board_id}/discussions` | `discussions:write` |
| GET | `/boards/{board_id}/discussions/{id}` (participants, messages, votes, runs) | `discussions:read` |
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
`discussion_count`, `open_count` and the board's newest `last_activity_at`, ordered newest activity
first (boards without threads come last, by name). It discloses board metadata, so it requires both
`boards:read` and `discussions:read`. The client then loads threads for the selected board only, so
the page never ships every thread of every board to the browser.

`start` and `runs` take the same body:

```json
{ "rounds": 3, "autonomous": true, "token_budget": 20000, "time_budget_seconds": 120 }
```

`rounds` defaults to the thread's `max_rounds` in autonomous mode and to `1` otherwise. A request
that resolves to a single interactive round runs inline and returns the round summary
(`status`, `answers`, `votes`, `failures`, `rounds_completed`, `tokens_used`, `elapsed_ms`,
`run_status`, `stop_reason`); anything longer returns `pending: true` and finishes in the
background, and the client polls the run. `pause`, `resume` and `stop` answer with the same summary
and `409` when the transition is not possible (for example pausing a finished run). Only one run
per thread can be active, and review is rejected (`409`) while a run is running or paused.

Run statuses: `running`, `paused`, `stopped`, `completed`, `failed`, `budget_exhausted`,
`no_progress`. A run stops at consensus, when the requested rounds are used up, when every
participant fails, when answers repeat (duplicate guard), or when a budget is exhausted. Thread
`run_state` mirrors `idle`/`running`/`paused`/`stopped` for the UI.

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
it describes, so the log is always ahead of (never behind) the stream.

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
`TRALALA_ATTACHMENT_MAX_BYTES` (default 10 MiB per file) and `TRALALA_BOARD_ATTACHMENT_MAX_BYTES`
(default 200 MiB per board). Bytes are stored as `data/boards/{uuid}/attachments/{attachment_id}.bin`;
the original filename is metadata only and is sanitized (no separators, no leading dots).

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
| GET | `/boards/{board_id}/cards` with `list_id|q|label|priority|due_before|overdue|completed|include_archived|sort|order|limit|offset` | `cards:read` |
| POST | `/boards/{board_id}/cards` (`Idempotency-Key`) | `cards:write` |
| POST | `/boards/{board_id}/cards/bulk` (`{"cards": [...]}`, max 100, partial failures, `Idempotency-Key`) | `cards:write` |
| GET | `/boards/{board_id}/cards/{card_id}?include=checklists,comments` | `cards:read` |
| PATCH | `/boards/{board_id}/cards/{card_id}` (requires `version`) | `cards:write` |
| POST | `/boards/{board_id}/cards/{card_id}/move` (`version`, `list_id`, `position`) | `cards:write` |
| POST | `/boards/{board_id}/cards/{card_id}/archive` | `cards:write` |
| POST | `/boards/{board_id}/cards/{card_id}/restore` | `cards:write` |
| POST | `/boards/{board_id}/cards/{card_id}/transfer` (`version`, `target_board_id`, `target_list_id`) | `cards:write` |

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
| GET | `/boards/{board_id}/search?q=&label=&priority=&overdue=&completed=&list_id=&include_archived=` | `cards:read` |
| GET | `/search?q=` (all active boards) | `cards:read` |
| GET | `/boards/{board_id}/activity?entity_type=&entity_id=&actor_type=&action=` | `boards:read` |

## Worker tools (MCP and `/llms.txt`)

`backend/app/services/agent_tools.py` holds one catalogue: a name, a description, a JSON Schema, the
scope it needs and a handler that calls the same services as the routes above. `/mcp` serves it as
MCP tools (`initialize`, `tools/list`, `tools/call`, `ping`; notifications answer `202`), and
`/llms.txt` summarises it. The browser WebMCP adapter is a separate surface for a person's own
session and is not generated from this catalogue yet. A tool is listed only when the
calling token holds its scope, and `tools/call` re-checks it before the handler runs.

| Tool | Scope | What it does |
| --- | --- | --- |
| `read_board` | `boards:read` | Loops with stage, `execution_allowed` and `blocked_reason`, the people you may assign, the agents you may ask |
| `read_loop` | `loops:read` | Goal, Info/Analysis/RoadMap documents, plan with per-Ticket readiness, Kanban columns |
| `read_ticket` | `cards:read` | Acceptance criteria, evidence, checklist, comments, column, version and `allowed_actions` |
| `create_loop` | `loops:write` | Start a Loop on a board for one coherent change |
| `write_info` | `loops:write` | Write the agreed intent; allowed while the Loop is `draft` or `analysis_review` |
| `run_analysis` | `loops:generate` | Ask a board agent for the Analysis candidate and report the run and the document state |
| `assign_ticket` | `cards:write` | Set or clear the owner; the current version is read for the caller |
| `move_ticket` | `cards:write` | Move to another column by id or name; the version is read and one retry absorbs a race |
| `comment_ticket` | `comments:write` | Add a progress note, finding or blocker |
| `ask_agents` | `discussions:write` | Create a discussion on the Ticket and run one round; returns the messages and positions |

The flow a person and their worker use to start work is `create_loop` → `write_info` →
`run_analysis` → the person approves the analysis → `read_loop`/`read_ticket` to work the Tickets it
produces. Every step stays inside the same gates: the analysis and the RoadMap are candidates until a
signed-in person approves them, and a cancelled or completed Loop is read-only.

Deliberately absent: board and list structure changes, Ticket creation or archiving, RoadMap and QA
writes, provider configuration and the approval decisions themselves.

Calling a tool the token may not use is a JSON-RPC error (`-32602`) rather than a silent downgrade.
A tool that fails returns `isError: true` with the API error code in the text content, so a client
sees `version_conflict` or `human_action_required` instead of a broken transport.

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


## Timestamps and sizes

- `due_at` and `due_before` accept an ISO 8601 date (`2027-01-15`) or timestamp
  (`2027-01-15T09:30:00Z`). Dates are normalized to midnight UTC; free text is rejected with
  `422 validation_failed` so due-date filters stay correct.
- Request bodies are limited by `TRALALA_MAX_REQUEST_BYTES` (default 8 MiB, matching the bundled
  nginx `client_max_body_size`). Requests rejected by nginx itself return an HTML error page, not
  the JSON envelope.

## Cross-board transfer semantics

`POST /boards/{board_id}/cards/{card_id}/transfer` copies the card into the target board and then
deletes the source copy. If the final delete fails, the source card is archived and the response
reports `finalized: false` with a warning; an `card.transfer_incomplete` activity entry records the
cause. Operators reconcile such cards deliberately.


## Board schema state

Each board tracks its schema with an Alembic revision in its own database. Board responses include
`schema_revision` (the applied revision) next to `schema_version` (the number of revisions in the
chain). Boards are migrated eagerly at startup; if a migration fails the board status becomes
`migration_failed`, mutations return `409 board_migration_failed` and reads return
`503 board_schema_outdated` until an administrator retries `POST /boards/{id}/migrate` or restores
a pre-migration backup.
