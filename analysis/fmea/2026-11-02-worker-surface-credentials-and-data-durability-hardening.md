2026-11-02

# FMEA: worker surface, credentials and data durability hardening

## At a glance

16 failure modes · 6 high-severity concerns · 8 recommended actions · ratings: qualitative bands proposed by the analyst (no agreed rubric exists in the repository), no RPN

- A single request without a `Content-Length` header can stream an unbounded body into memory before anything authenticates it, and the process that dies is the one holding every board (High, observed in `main.py`, `api/mcp.py`, `api/v1/{attachments,boards}.py`, F1 and F2, Actions A1).
- A stolen member token is a full copy of that person's read access with no per-token limit and no signal beyond a timestamp, so an agent left running on a laptop keeps silently reading Boards nobody is watching (High, observed in `services/credentials.py` and `api/deps.py`, F4, Actions A5).
- A restore can report success while the uploaded files are the current ones rather than the snapshot's, and a crash between the database snapshot and its file sidecar leaves exactly that state (High, observed in `services/backups.py`, F6, Actions A4).

## Scope and method

**Type.** Software and process FMEA of the surfaces added in the worker-access work: the MCP tool
surface, the interaction-access credentials that authenticate it, the board data lifecycle
(delete, duplicate, export, import, backup) and the runtime calls that reach an agent. It is the
hardening pass that follows the functional work, not a re-analysis of the Loop workflow itself
(covered by `2026-11-01-loop-planning-delivery-qa-and-history-workflow.md`).

**Boundary.** In scope: `backend/app/api/mcp.py`, `backend/app/api/deps.py`,
`backend/app/services/{agent_tools,credentials,attachments,backups,backup_scheduler,boards,runtime,orchestrator,mentions}.py`,
`backend/app/storage/{board_db,sqlite,migration_manager}.py`, `backend/app/main.py`,
`backend/app/core/config.py` and the schemas those services validate. Out of scope: the Loop planning
stages, the frontend, themes, and the WebMCP adapter (it does not share this catalogue yet).

**Lifecycle phase and environment.** A single self-hosted backend process per data directory
(`AGENTS.md` rule 8), SQLite in WAL mode, `data/registry.sqlite` plus `data/boards/{uuid}/board.sqlite`
and its `attachments/` directory, an in-memory rate limiter, provider calls to a user-configured
OpenAI-compatible endpoint or A2A agent, and workers connecting from someone's desktop over HTTP(S).

**Intended functions analysed.** (1) accept a request of bounded size, (2) authenticate before
spending work, (3) let a person issue and revoke their own agent access, (4) keep a token from
becoming broader than its owner, (5) keep one board's files and database one unit, (6) restore a
board to the state a snapshot describes, (7) import an archive without trusting it, (8) keep uploads
and their rows consistent, (9) call an agent and interpret its answer, (10) reach consensus only on
real agreement, (11) keep the worker surface honest about what changed, (12) keep one process per
data directory.

**Rating method.** The repository defines no severity, occurrence or detection scale, so no numeric
S/O/D and no RPN is used. The bands are the analyst's proposal, matching the earlier reports in
`analysis/fmea/`:

- **Severity** - Critical: loses or corrupts board data, or breaks the approval record the product
  is sold on. High: the process can be stopped or a rule bypassed. Medium: a resource leak, a
  confusing state or a privilege larger than intended. Low: operational noise.
- **Control** - *Guarded*: enforced in the schema or by a test that fails if the rule is removed.
  *Partly guarded*: enforced in code with no test for this specific mode. *Unguarded*: neither
  prevention nor detection.
- **Evidence** - *observed* (read in this session), *inferred*, *unknown*.

## FMEA table

| ID | Function | Failure mode | Effects | Causes | Existing prevention controls | Existing detection controls | Evidence | Severity | Control |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | Accept a request of bounded size | A request without `Content-Length` streams an unbounded body | Process memory grows until it is killed; every board in the installation is unavailable | Chunked transfer encoding, or a proxy that strips the header | `settings.max_request_bytes` is compared against the header only, in the `observability` middleware | None | observed (`main.py` middleware, `max_request_bytes` = 8 MiB) | High | Unguarded |
| F2 | Authenticate before spending work | `/mcp` parses the JSON body before resolving the actor | Unauthenticated callers spend parse CPU and memory; token guessing never reaches the limiter, which is keyed by actor id | `await request.json()` precedes `get_context(request)` | Nothing; authentication itself is guarded, only its ordering is late | The request log shows `401` with a duration, no counter | observed (`api/mcp.py`, `api/deps.py:54`) | High | Unguarded |
| F3 | Import an archive without trusting it | A small archive expands into gigabytes when `board.sqlite` is read | Import exhausts memory and takes the process down | Deflate ratio; only the compressed upload size is limited | Attachment entries are measured against `board_attachment_max_bytes`; the database entry is not | None | observed (`services/boards.py` `import_archive`) | High | Partly guarded |
| F4 | Keep a token from becoming broader than its owner | A leaked member token reads every board its owner can read, for the token's whole lifetime | Silent, sustained read access to board content; the owner may never notice | Token is identity by design; no device binding; `last_used_at` is the only signal | TTL (30 days default), per-person token cap, revoke on disable, scopes limited to boards/cards/comments/loops | `last_used_at` in `GET /credentials/mine` and the admin user list | observed (`services/credentials.py`, `services/agent_tools.py`, decision 0017) | High | Partly guarded |
| F5 | Let a person issue and revoke their own access | A person cannot tell which of their keys is which when rotating | The wrong key is revoked, or an old one is left alive because it looked current | Only `has_api_key` and a short hint are exposed | Named keys, `created_at`, `last_used_at`, expiry, owner-or-admin rotate/revoke | The settings card lists them | observed (`frontend/src/features/settings/InteractionAccessCard.tsx`, `GET /credentials/mine`) | Medium | Guarded |
| F6 | Restore a board to the state a snapshot describes | A missing or stale file sidecar is silently accepted | Restore reports success while uploaded files are the current ones, not the snapshot's | Crash between the database snapshot and the sidecar write | The sidecar is written next to the snapshot; restore skips it when absent and reports `skipped: true` | `has_attachments` per snapshot; the restore response names what it restored | observed (`services/backups.py` `_restore_attachments`) | High | Partly guarded |
| F7 | Keep one board's files and database one unit | Deletion fails halfway on Windows because a file is still open | The row survives (by design) but the directory is partly removed, and the next delete has less to work with | An in-flight request holds a connection, or an antivirus scanner holds the file | `delete_database` closes engines under the board lock, then removes the directory; the registry row goes last | The delete raises; the operator retries | observed (`storage/board_db.py`, `services/boards.py` `delete`) | Medium | Partly guarded |
| F8 | Keep one board's files and database one unit | Duplicate or export copies files without a size bound | Disk exhaustion on the host holding every board | `_copy_attachments` copies whatever is in `attachments/`; no quota check at copy time | Upload enforces `board_attachment_max_bytes`, so the source is already bounded by it | None | observed (`services/boards.py`) | Low | Guarded |
| F9 | Keep uploads and their rows consistent | The process dies after the file is in place and before the row is inserted | An unreferenced `.bin` file nobody can see | Kill during insert | The file is staged and moved before the insert; a rejected insert removes it | None | observed (`services/attachments.py` `upload`) | Low | Partly guarded |
| F10 | Call an agent and interpret its answer | A stored agent hostname re-resolves to a blocked address (cloud metadata, link-local) at call time | The backend is used as a probe into the metadata service of the host it runs on | DNS rebinding after the endpoint was validated at creation | `services/connections.validate_endpoint` at create/update rejects link-local, multicast, unspecified and reserved addresses always, and private and loopback addresses when `TRALALA_AGENTS_ALLOW_PRIVATE_ENDPOINTS` is off; `httpx.Client(follow_redirects=False)` at call time | Provider errors surface in the run's `failures` | observed (`services/runtime.py:125`, `services/connections.py`, config default `agents_allow_private_endpoints=True`) | Medium | Partly guarded |
| F11 | Call an agent and interpret its answer | An A2A agent replies with parts the collector does not recognise | A successful call records an empty answer | Card or message shape differs from the documented one | Text is collected from parts, artifacts and status; empty text becomes `a2a_empty_response` | The run reports the failure | observed (`services/runtime.py` `call_a2a`, `tests/test_a2a_runtime.py`) | Low | Guarded |
| F12 | Reach consensus only on real agreement | A round where every agent repeats its previous text is classified as consensus | A thread is marked decided without a new argument being made | `unanimous` reads the latest votes, which only change when a position changes | Roundtable threads need an earlier answered round; duplicate answers are counted in `repeats` | `_classify` sees `answers` and `repeats` but checks consensus first | observed (`services/orchestrator.py` `run_round`, `services/runs.py` `_classify`) | Medium | Partly guarded |
| F13 | Reach consensus only on real agreement | An agent that never emits a verdict is recorded as `abstain` forever | A roundtable can never conclude, and nobody is told why | The provider answer shape is not validated, only parsed leniently | The verdict is read from JSON, a labelled line or a lone word, defaulting to `abstain`; the prompt asks for one | The vote list shows `abstain` per agent | observed (`services/runtime.py` `extract_position`, `tests/test_orchestrator.py`) | Medium | Guarded |
| F14 | Keep the worker surface honest about what changed | `/llms.txt` describes tools or rules the deployment no longer serves | A worker calls a removed tool and gives up, or follows an outdated rule | The tool list is generated, the surrounding prose is written by hand | `render_bootstrap` is generated from `tool_catalog()` | A stale sentence is only noticed by reading it | observed (`api/mcp.py` `render_bootstrap`) | Medium | Partly guarded |
| F15 | Keep one process per data directory | A second process starts against the same data directory | Two backup schedulers, two rate limiters, two migration runners on the same board file | Restart overlap, `--reload`, or a second container | `.process.lock` in the data directory; migrations run under a lock | Startup fails loudly when the lock is held | observed (`AGENTS.md` rule 8, `.devdata/.process.lock`, `storage/sqlite.py`) | Critical | Guarded |
| F16 | Let a person issue and revoke their own access | The first administrator password sits in a file in the data directory | The password is readable by anything that can read that directory | The password is generated rather than published, and must be delivered somehow | `write_private_file` sets owner-only permissions where the platform allows | Documented in the README; the operator changes it on first login | observed (`core/security.py` `write_private_file`, README) | Medium | Partly guarded |

## Priorities

High-severity concerns, in the order this analysis recommends acting on them:

1. **F1 / F2** - the request path can be made to buffer an arbitrary body before anything
   authenticates it. These are the only rows where an unauthenticated caller reaches the process,
   and the single-process architecture turns that into total unavailability.
2. **F6** - a restore that reports success while the files are not the ones in the snapshot is worse
   than a restore that refuses: the operator believes the board is back.
3. **F3** - admin-scoped, but the archive arrives from outside the installation by definition.
4. **F4** - a designed tradeoff rather than a defect; ranked high because the mitigation available
   today (revoke, or wait for expiry) is weak and the product's answer must be honest about it.
5. **F12** - a decision recorded on duplicate text is a workflow integrity concern, not a data-loss
   one.

F15 is Critical but guarded, so it needs no action beyond keeping the lock honest. F5, F8, F11 and
F13 are guarded and only need the tests that already exist.

## Recommended actions

| ID | Targets | Action | Targeted cause or control gap | Expected effect | Status |
| --- | --- | --- | --- | --- | --- |
| A1 | F1, F2 | Read raw bodies through one bounded reader that counts bytes while streaming and raises `413 payload_too_large`, and use it in the three endpoints that read raw bytes; authenticate `/mcp` before parsing the body | The header-only check and the late authentication | A request without a header, or without a token, can no longer make the process buffer an arbitrary body | done in this session |
| A2 | F3 | Cap the uncompressed size of every member of an imported archive before reading it | Only attachment entries were measured against a limit | A small archive can no longer expand into memory | done in this session |
| A3 | F12 | Exclude a round in which every answer repeated the previous text from the consensus decision, and report it as `no_progress`/`duplicate_answers` | `unanimous` read the votes, which a repeated round does not refresh | A thread decided on repeated text reports that it made no progress | done in this session |
| A4 | F6 | Report in the restore response when a snapshot has no file sidecar and the current files were kept (`attachments.reason` plus a `warning`) | A silent mismatch between database and files | Restore either matches the snapshot or says it does not | done in this session |
| A5 | F4 | Expose a rolling 7-day use count next to `last_used_at` in `GET /credentials/mine`, so an unused or unexpectedly active key is visible to its owner without an admin | The only signal was a single timestamp | A person can spot a token they are not using | declined by the owner: internal-network deployment, and the per-actor limiter already bounds runaway work |
| A6 | F10 | Re-resolve the hostname inside `call_a2a` and `call_completion` immediately before the request, check it against the same policy that applied at creation, and connect to the resolved address | Validation happened only at creation | A hostname that now resolves to a blocked address cannot be called | proposed, not done |
| A7 | F7 | Route every board-file operation through one platform profile: retry only the errors a host can clear on its own, never `EACCES`/`EPERM`/`EROFS`, and answer `409 board_files_busy` with the relative leftover directory | Windows shares a file it may not delete; POSIX fails for different reasons | A held file costs a short wait and an actionable error instead of a half-deleted board, on every host | done in this session (decision 0020) |
| A8 | F14 | Assert in tests that every tool named in `render_bootstrap` exists in `tool_catalog()` and that every tool is mentioned there | Hand-written prose could drift from the catalogue | The bootstrap cannot go stale silently | done in this session |

A5 was declined by the owner on 2026-11-02: the product runs on internal networks with staff and
approved models, and the per-actor limiter is a runaway guard rather than defence, so a per-token
limit would only throttle the legitimate burst. What replaced it is a cost guard on the thing that
actually spends money: a discussion is capped at four rounds and every run gets a default token and
time budget (`TRALALA_DISCUSSION_TOKEN_BUDGET`, `TRALALA_DISCUSSION_TIME_BUDGET_SECONDS`).

A7 turned out to be broader than a Windows workaround: the owner asked whether Linux and macOS
suffer the same failure, and they do not for an open file - POSIX removes the name and keeps the
inode alive - but they do for permissions, a read-only volume, an immutable flag and a network
share. It is now one platform profile (`core/platform.py`, `TRALALA_PLATFORM_PROFILE`, decision
0020) that decides retry policy while the locking mechanism still follows the real operating
system, and a busy file can no longer leave a board half deleted.

A6 is narrower than it first looks, and the owner's question exposed that. Private and loopback
endpoints are normal here: a self-hosted installation points an agent at a model on its own network,
which is why `TRALALA_AGENTS_ALLOW_PRIVATE_ENDPOINTS` defaults to `True`. So A6 does not protect
against "reaching the internal network" - that access is the feature. What a re-check would close is
the one case the current policy still refuses: a hostname that resolves to a link-local, multicast,
reserved or unspecified address *after* it was validated (typically the cloud metadata endpoint
`169.254.169.254`). That matters only on a host where a metadata service is reachable and where an
untrusted party can change what a hostname resolves to; on a workstation or a plain internal server
it has almost no value. It is recorded, not scheduled.

## Assumptions and open questions

- **Exposure is unknown.** The analysis assumes the service may be reachable from a network (the
  `README` and the `TRALALA_COOKIE_SECURE` warning), but no deployment evidence was available: how
  many installations are public, and whether a reverse proxy sets `Content-Length` on chunked
  bodies. A1 does not depend on the answer; its priority does.
- **F4 severity depends on the product's promise.** Whether a member key should read every board its
  owner can read is a product decision (decision 0017 says yes). This analysis records the exposure,
  not a verdict on it.
- **No incident history was available.** Occurrence is therefore not rated for any row.
- **F10 needs a threat-modelling pass.** Endpoint validation against internal addresses is a
  security concern with an adversarial actor; FMEA only records that a control exists at one point
  in time. A threat model should cover SSRF, DNS rebinding and credential forwarding together.
- **Reviewers needed.** Whoever operates an installation (for the F1/F6 priority) and whoever owns
  the credential model (for F4/A5).
