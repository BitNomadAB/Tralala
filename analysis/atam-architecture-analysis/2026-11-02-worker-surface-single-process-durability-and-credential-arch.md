2026-11-02

# ATAM Architecture Analysis: worker surface, single-process durability and credential architecture

## At a glance

6 risks · 5 sensitivity points · 4 tradeoff points · 4 non-risks · provisional: yes

- Everything that matters runs in one process: a body the process cannot refuse, a threadpool full of worker calls or a blocked board lock stops every board, and the operator has no way to shed the load (risk, observed in `main.py`, `api/mcp.py` and the composition root, F1/F2, Recommendations R1).
- The worker surface is one catalogue behind two transports, so a rule added there is immediately true over MCP and REST, but the browser adapter is outside that catalogue and can drift from it (tradeoff point, observed in `docs/architecture.md` and `services/agent_tools.py`, F7, R4).
- Board data, uploaded files and their backups are one unit only because three separate code paths agree; the snapshot sidecar is written after the database, so "restore" and "restore everything" are not the same promise yet (sensitivity point, observed in `services/backups.py`, F5, R3).

## Scope and evidence

**System and version.** The Tralala backend and its worker-access surface at the commit that follows
the interaction-access work (workspace state on 2026-11-02, `master` plus the change set committed by
the product owner).

**Purpose.** A provisional ATAM pass over the architecture as it now stands, asking whether the
quality goals the worker surface demands (availability, security, recoverability, modifiability) are
supported by the decisions taken for it.

**Sources inspected.** `AGENTS.md`; `docs/architecture.md` (since moved to `public_docs/Architecture.md`) (storage model, request lifecycle,
consistency across databases, WebMCP and the worker surface, operational notes);
`docs/decisions/0001-per-board-sqlite.md`, `0002-multi-database-consistency.md`,
`0007-accounts-sessions-and-keys.md`, `0012-board-agent-membership.md`, `0015-worker-surface-mcp-and-llms-txt.md`,
`0016-worker-authored-info-while-speculative.md`, `0017-interaction-agent-access-ownership.md`,
`0018-a2a-execution.md`, `0019-board-files-travel-with-the-database.md`; `backend/app/main.py`,
`backend/app/api/{deps,mcp}.py`, `backend/app/api/v1/{attachments,boards}.py`,
`backend/app/services/{agent_tools,credentials,attachments,backups,backup_scheduler,boards,runtime,orchestrator,mentions,connections}.py`,
`backend/app/storage/{board_db,sqlite,migration_manager}.py`, `backend/app/core/{config,errors,security,ratelimit}.py`,
`frontend/src/features/settings/{InteractionAccessCard,AgentAccessGuide,UsersCard}.tsx`,
`.github/workflows/ci.yml`, and the test suite under `backend/tests`.

**Participants.** None. This is a repository-only assessment; no operator, product owner or
security owner took part, so scenario priorities are candidates, not agreed priorities.

**Limitations.** No deployment evidence (reverse proxy, TLS termination, host sizing, how many
installations are reachable from a network); no incident history; no measurements. Claims are
labelled **observed** (read in the repository), **inferred**, or **unknown**.

## Business drivers and utility tree

**Drivers.** Source: `README.md`, `AGENTS.md`, decisions 0015-0019, and the product owner's
statements in this session (stakeholder-reported).

| ID | Driver | Source |
| --- | --- | --- |
| D1 | A person can hand their own desktop agent read access to their Boards and have it track Tickets without a cloud provider | stakeholder-reported, decision 0017 |
| D2 | The installation is self-hosted: no external AI provider, no Postgres/Redis, one data directory | `README.md`, `AGENTS.md` |
| D3 | Approvals, plans, QA and history are the product's record; they must not be silently changed | decisions 0015-0016, `docs/architecture.md` "Loop workflow" |
| D4 | A board is the unit of data: it moves, copies, exports and restores as one thing | decision 0019 |

**Utility tree (candidate priorities).** Business importance and technical difficulty are separate
judgements by the analyst; both are provisional.

| Attribute | Scenario | Importance | Difficulty |
| --- | --- | --- | --- |
| Availability | S1: an unauthenticated client sends a body the process must buffer | high | low |
| Availability | S2: a worker makes many concurrent tool calls while a person uses the UI | high | medium |
| Security | S3: a member's agent token is leaked | high | medium |
| Security | S4: a configured agent endpoint is pointed at an internal address | medium | medium |
| Recoverability | S5: an operator restores a board after a bad edit | high | medium |
| Modifiability | S6: a new worker capability is added | high | low |
| Operability | S7: the process is restarted while a backup is running | medium | low |

## Architecture and approaches

| Approach | Evidence | Rationale |
| --- | --- | --- |
| One service layer, every interface calls it | `AGENTS.md` rule 1, `docs/architecture.md` "Backend layers" | Business rules cannot diverge between REST, MCP and the UI |
| Registry is authoritative; boards are separate SQLite files | `AGENTS.md` rules 2-3, `docs/decisions/0001-per-board-sqlite.md` | A board is portable and a corrupt board cannot take the registry down |
| Single writer per data directory, enforced by an OS file lock | `docs/architecture.md` "Operational notes", `storage/sqlite.py` | SQLite plus in-process locks make multi-process unsafe |
| Curated worker catalogue, one description, two transports | `services/agent_tools.py`, `api/mcp.py`, decision 0015 | The worker surface cannot exceed what the services allow |
| Token identity with owner, TTL, scopes and revocation | `services/credentials.py`, decision 0017 | A person's key is theirs; disabling the person disables the key |
| Snapshot plus file sidecar | `services/backups.py`, decision 0019 | A board is its database and its files |
| Sequential in-round discussion with a review round for consensus | `services/orchestrator.py` | Consensus must follow reading, not parallel guessing |
| Bounded, staged uploads | `services/attachments.py` | A row must never name a file that is not there |

## Scenario analysis

**S1 - unbounded body from an unauthenticated client.** Source: an internet client or a scanner.
Stimulus: `POST /mcp` with a chunked body and no `Content-Length`. Environment: normal operation.
Response expected: the request is refused with `413` before the body is buffered, and the process
keeps serving every board. Observed response: the size check in `main.py` reads the `Content-Length`
header only, and `api/mcp.py` parses the JSON before `get_context` resolves the actor, so the body is
buffered with no configured bound and no rate limit. Response measure: a body of any size must be
refused with `413` and bounded memory; no measurement exists. Confidence: high that the gap exists;
unknown how often a proxy supplies the header. Quality attribute: availability, security.

**S2 - worker load competing with the UI.** Source: a worker inside a coding agent. Stimulus: dozens
of `tools/call` requests, some of which poll a generation run for up to 120 s. Environment: one
backend process. Response expected: UI requests stay responsive; worker calls are bounded. Observed:
tool handlers run in the default threadpool via `run_in_threadpool`, the rate limiter is per actor
(600/min, `core/config.py`) and is checked after authentication; a worker polls with
`wait_seconds` up to 120 s inside a pooled thread. Response measure: p95 latency of a UI `GET` under
worker load; not measured. Confidence: medium (inferred from code and configuration). Quality
attribute: availability, performance.

**S3 - a leaked member token.** Source: a laptop that keeps the token, or a log. Stimulus: an
attacker uses the token. Environment: normal operation. Response expected: exposure is bounded and
visible. Observed: the token is identity (decision 0017), scopes are limited to boards, cards,
comments and loops, the TTL is 30 days by default, the owner can revoke, disabling the account
revokes, and `last_used_at` is recorded per credential. There is no per-token rate limit and no
behavioural signal. Response measure: time from leak to revocation; unknown. Confidence: high.
Quality attribute: security, operability.

**S4 - an agent endpoint pointed inward.** Source: an administrator or a stolen admin token.
Stimulus: an agent `base_url` that resolves to a link-local address. Environment: normal operation.
Response: the connection is refused. Observed: `services/connections.validate_endpoint` rejects
metadata and link-local targets, embedded credentials and redirects at create/update; at call time
`runtime` uses `httpx` with `follow_redirects=False` but does not re-validate the resolved address.
Response measure: no internal address is reachable through the product; not measured. Confidence:
medium (the create-time control is observed; the rebinding path is inferred). Quality attribute:
security.

**S5 - restore after a bad edit.** Source: an operator. Stimulus: restore `backup-<UTC>.sqlite`.
Environment: the board is active, the process is serving. Response expected: the board returns to the
snapshot, files included, and says what it did. Observed: the restore snapshots the backup into the
live file under the board lock behind a verified pre-restore copy and re-validates integrity; the
file sidecar is restored when present and silently skipped when absent, and a snapshot is listed with
`has_attachments`/`attachments_size_bytes`. Response measure: database and files both match the
snapshot's timestamp; not measured. Confidence: high. Quality attribute: recoverability,
operability.

**S6 - adding a worker capability.** Source: a developer. Stimulus: a new tool. Environment:
development. Response expected: one place to change, and the transports pick it up. Observed: the
catalogue in `services/agent_tools.py` carries name, description, scopes, input schema and handler;
`/mcp` filters by scope and `render_bootstrap` is generated from it; the browser WebMCP adapter is a
separate registry that calls REST directly (`docs/architecture.md` "WebMCP and the worker surface").
Response measure: number of files to edit per capability; observed as one for MCP/REST, more for
WebMCP. Confidence: high. Quality attribute: modifiability.

**S7 - restart during a backup.** Source: an operator, a package upgrade or a host reboot. Stimulus:
the process stops while `BackupScheduler` is snapshotting. Environment: a single process. Expected
response: no snapshot is listed that cannot be restored, and the scheduler resumes after restart.
Observed: snapshots are written with SQLite's online-backup API to the final filename and pruning
only considers `BACKUP_PATTERN`; a partially written snapshot is not distinguished from a complete
one, and a failing backup is logged while the next check is an hour away. Response measure: a listed
snapshot always restores; unknown. Confidence: medium. Quality attribute: recoverability,
operability.

## Findings

| ID | Type | Finding | Scenarios | Attributes | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | Risk | The request-size limit is a header check, so a chunked body bypasses it | S1 | availability, security | `main.py` middleware, raw-body reads in `api/mcp.py`, `api/v1/attachments.py`, `api/v1/boards.py` (observed) | high |
| F2 | Risk | `/mcp` parses its body before authenticating, so the only unauthenticated entry point does work before any check | S1, S2 | availability, security | `api/mcp.py` order of `request.json()` and `get_context` (observed) | high |
| F3 | Risk | Availability is a single point: one process hosts every board, the threadpool and the rate limiter, so any unbounded resource is an installation-wide outage | S1, S2 | availability | `AGENTS.md` rule 8, `docs/architecture.md` "Operational notes" (observed) | high |
| F4 | Risk | Restore does not distinguish "the snapshot had no files" from "the sidecar is missing", so a restore can report success with current files and a snapshot database | S5 | recoverability | `services/backups.py` `_restore_attachments` (observed) | high |
| F5 | Risk | Snapshots are written straight to their final name, so an interrupted backup leaves a file that is listed like any other | S7 | recoverability | `services/backups.py` create/prune/list (observed) | medium |
| F6 | Risk | A stored agent hostname is validated at creation only, so a name that later resolves to a link-local or metadata address is still called; private and loopback endpoints are allowed by design | S4 | security | `services/runtime.py` `call_a2a`/`call_completion`, `services/connections.py` (observed at create; rebinding inferred) | medium |
| F7 | Sensitivity point | The rate limit is keyed by actor, not by token or endpoint, so one worker can consume a person's whole budget and an unauthenticated caller is limited by nothing | S1, S2 | availability, security | `api/deps.py:54`, `core/ratelimit.py`, `core/config.py` (observed) | high |
| F8 | Sensitivity point | The MCP surface is filtered by scopes at listing time as well as at call time, which keeps a worker from even seeing a capability it cannot use | S6 | security, modifiability | `api/mcp.py` `_tool_payload`, `missing_scopes` (observed) | high |
| F9 | Sensitivity point | Board engines are pooled, idle-closed and capped, which is what keeps many boards from exhausting file handles | S2 | performance, operability | `docs/architecture.md` "Storage model", `storage/board_db.py` (observed) | high |
| F10 | Sensitivity point | The per-board lock serializes every write for one board, so a slow restore blocks that board's API for its duration | S5 | availability | `docs/architecture.md` "Request lifecycle" (observed) | high |
| F11 | Sensitivity point | The worker catalogue's descriptions are the product's documentation for external agents: `render_bootstrap` is generated from them, so wording changes behaviour | S6 | modifiability, interoperability | `api/mcp.py` `render_bootstrap`, `services/agent_tools.py` (observed) | medium |
| F12 | Tradeoff point | One process is the price of a zero-dependency self-hosted install; it buys simplicity and costs availability headroom | S1, S2, S7 | availability, deployability | decision context in `AGENTS.md` rule 8 and `docs/architecture.md` (observed) | high |
| F13 | Tradeoff point | A token is identity: it buys a simple, auditable model and costs the ability to bind a key to a device or narrow it per board | S3 | security, modifiability | decision 0017, `services/credentials.py` (observed) | high |
| F14 | Tradeoff point | Duplicating a board copies files as well as the database, so a copy is complete; the cost is doubling disk on a host that has no quota | S5 | recoverability, operability | `services/boards.py` `_copy_attachments` (observed) | high |
| F15 | Tradeoff point | Human decisions are excluded from every token scope at the schema level, so no worker can approve a plan; the cost is that an unattended workflow always stops for a person | S6 | security, modifiability | `AGENTS.md` rules 5, `services/agent_tools.py` docstring, decision 0015 (observed) | high |
| F16 | Non-risk | Approvals are bound to exact revision ids and source hashes, so a plan cannot be approved unseen | S5, S6 | security, integrity | `docs/architecture.md` "Loop workflow", decision 0016 (observed) | high |
| F17 | Non-risk | A board's deletion, duplication, export and import all treat the database and its files as one unit | S5 | recoverability | `services/boards.py`, `storage/board_db.py`, decision 0019 (observed) | high |
| F18 | Non-risk | The single-writer assumption is enforced, not merely documented: startup takes an OS file lock and fails with an actionable message | S7 | availability, operability | `docs/architecture.md` "Operational notes" (observed) | high |
| F19 | Non-risk | Every worker capability calls the same service function as REST, so version checks, workflow gates and audit entries cannot be skipped by using MCP | S6 | security, modifiability | `services/agent_tools.py` module docstring, `backend/tests/test_agent_tools.py` (observed) | high |

**Risk themes.**

- *Unbounded work before authentication* (F1, F2, F3, F7): the same architectural choice - one
  process, one threadpool, a rate limiter that needs an actor - makes every unbounded input an
  installation-wide problem. Fixing the inputs one by one is necessary but the theme is only closed
  when the process has a way to shed load.
- *Recovery promises that outrun the mechanism* (F4, F5, F10): the product tells an operator that a
  board is one unit, but two of the mechanisms behind that promise are partial.
- *Validated once, trusted forever* (F6, F11): a control applied at creation (an endpoint check, a
  tool description) is relied on later without re-checking.

## Recommendations and open questions

| ID | Addresses | Recommendation | Expected benefit | Cost or tradeoff |
| --- | --- | --- | --- | --- |
| R1 | F1, F2, F7 | Make the body limit a streaming byte count shared by every raw-body endpoint and authenticate `/mcp` before parsing | Closes the only unauthenticated resource path | A little more code on the request path |
| R1b | F7 | No per-token limit. A discussion is capped at four rounds and every run gets a default token and time budget instead | Cost is bounded by the work a question may do rather than by a number nobody can justify | A budget that stops a legitimate long discussion; configurable per installation |
| R2 | F5 | Write a snapshot to a temporary name and rename it into place, so a listed snapshot is always complete | A listed snapshot always restores | A rename per backup; pruning must ignore the temporary suffix |
| R3 | F4 | Report the sidecar state per snapshot and refuse a restore that would mix a snapshot database with current files unless the operator opts in | Recovery claims match what happened | One more field in the API and one more explicit decision for the operator |
| R4 | F11 | Keep the bootstrap generated from the catalogue and assert the two stay in step in tests | Documentation cannot drift from the surface | A test that has to be maintained |
| R5 | F3, F12 | Document the load ceiling (one process, one threadpool, one writer) in operational notes, and treat "scale out" as a decision with a coordination store, not a tuning exercise | Operators get an honest ceiling | None beyond documentation |
| R6 | F6 | Re-resolve the agent hostname immediately before a provider call, check the same policy, and connect to the resolved address; only worth doing if installations run where a metadata service is reachable | Closes the rebinding path to a blocked address | An extra DNS lookup per call; needs a decision because private endpoints are allowed here on purpose. **Declined by the owner (2026-11-02):** self-hosted, no metadata service |
| R7 | F10 | State in the API documentation that a restore blocks the board for its duration | An operator is not surprised | Documentation only |

**Done in this session** (the FMEA pass acted on the same evidence): R1's body limit and `/mcp`
ordering, R3's sidecar reporting, R4's bootstrap test, and the archive-size bound that belongs to the
same theme; see `analysis/fmea/2026-11-02-worker-surface-credentials-and-data-durability-hardening.md`,
actions A1-A8. After the owner's decision on 2026-11-02, the per-token limit is dropped (R1b): the
deployment model is an internal network, and the cost guard is a four-round cap plus a default token
and time budget per run instead.

**Open questions for stakeholders.**

1. How many installations are reachable from the internet, and does a reverse proxy set
   `Content-Length`? (Decides F1's priority.)
2. Per-token limiting is declined (2026-11-02): the deployment model is an internal network, so the
   actor limiter stays a runaway guard and cost is bounded per run instead (R1b). Does the
   four-round cap match how the team actually discusses a Ticket? (R1b.)
3. Should a restore ever be allowed to mix a snapshot database with current files? (R3.)
4. What is the intended ceiling for concurrent boards and workers on the smallest supported host?
   (F3, R5 — no measurement exists.)
5. Does the browser WebMCP adapter need to share the worker catalogue, or is drift between the two
   acceptable while it stays UI-contextual? (F7, R4.)
