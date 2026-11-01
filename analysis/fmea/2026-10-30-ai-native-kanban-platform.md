2026-10-30

# FMEA: ai-native kanban platform

## At a glance

16 failure modes · 8 high-severity concerns · 13 recommended actions · ratings: not rated (no agreed severity/occurrence/detection rubric; priorities are qualitative)

- A deployment that keeps the default session secret can have its admin session forged, so the service must generate its own secret or refuse to start (high severity, observed, F1).
- Restoring a backup can be read by a concurrent request because nothing excludes readers while the live database file is overwritten; users could read a partially restored board (high severity, observed, F2).
- Deleting an archived board removes its backups as well, so a mis-click permanently destroys the only copies; an export or backup confirmation should be required first (high severity, observed, F12).

## Scope and method

**FMEA type:** software/system FMEA for the single-host self-hosted deployment described by the specification and implemented in this repository. Lifecycle phase: design and pre-release operation, with existing controls as implemented today.

**Item boundary:** FastAPI service, registry and per-board SQLite databases, React UI, REST API, WebMCP adapter, Docker/nginx packaging. Outside scope: host OS, hardware failure handling, external identity providers (not used), and adversarial threat modeling (this FMEA is not a security threat model, although it records the security-relevant failure modes that surfaced).

**Intended functions reviewed:** human authentication, agent authentication and authorization, board creation, board reads, card mutation with concurrency, bulk card creation, cross-board transfer, backup/restore/validation, search, audit history, deployment/serving, WebMCP tool exposure, board deletion.

**Operating assumptions (inferred from repository):** one backend process per data directory; local or single-host deployment; operators create boards manually; backups are taken on demand; browsers may not support WebMCP; SQLite is the only datastore.

**Rating method:** none agreed, so no numeric S/O/D ratings or RPN are assigned. Priorities use severity of effect, exposure implied by the design, strength of existing detection, and uncertainty. All ratings are marked **not rated**. Any numeric estimate here would be invented.

## FMEA table

| ID | Function / requirement | Failure mode | Effects | Causes (evidence) | Existing prevention controls | Existing detection controls | Evidence | Rating basis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | Authenticate humans with a private session secret | Service signs cookies with the repository's default secret | Anyone with the source can forge an admin session; full board access and mutation | Default literal in `core/config.py:16` is used when the env var is absent | Operator expected to set `KANBAN_SECRET_KEY` (documented in `.env.example`); none enforced | None at startup or runtime | `backend/app/core/config.py`, `backend/app/core/security.py` | High severity, medium exposure, no detection |
| F2 | Restore a backup without disturbing live readers | Restore overwrites the live database while another request opens it | Reader sees missing/partial tables or stale WAL state; possible write loss during the window | `backups.restore` closes the engine then snapshots over the file; `BoardDatabaseManager.open` has no shared lock (observed) | Restore requires `boards:admin`; validation runs afterwards | `validate()` after restore; no alert, no concurrency test | `backend/app/services/backups.py:restore`, `backend/app/storage/board_db.py:open` | High severity, low exposure, weak detection |
| F3 | Create a board atomically across registry and file | Process dies after registry insert, before database initialization | Board listed as `maintenance`; UI shows a board that cannot be opened until restart | Two-phase operation by design (decision 0002); recovery runs only at startup | `try/except` sets `error`; `recover()` repairs leftovers at startup | Status visible in dashboard; startup log only | `backend/app/services/boards.py:create,recover` | Medium severity, low occurrence, medium detection |
| F4 | Board creation is idempotent | Crash after board creation but before the idempotency record is stored | A client retry creates a second board | Idempotency record written in a separate transaction (`services/boards.py:create`) | Idempotency key support exists; response stored after creation | None for the crash window | `backend/app/services/boards.py:create` | Medium severity, low exposure, weak detection |
| F5 | Move a card between boards without losing or duplicating it | Source delete fails after the copy succeeds | Duplicate cards in two boards; agents may act on both | Two independent board transactions (decision 0002) | Copy-first ordering; response carries `finalized` and a warning | Response warning; no reconciliation job | `backend/app/services/cards.py:584-593` | Low severity, low exposure, good detection |
| F6 | Bulk card creation is retry-safe | Client retries a timed-out bulk request | Duplicated cards across the batch | Bulk endpoint has no idempotency support (`api/v1/cards.py:85`) | Per-card validation and savepoints (partial-failure semantics) | Failed items reported; duplicates not detected | `backend/app/api/v1/cards.py` | Medium severity, medium exposure, weak detection |
| F7 | Card due dates are meaningful | Any string is accepted as `due_at` | Overdue filters and due sorting silently wrong; agent decisions based on false signals | `due_at: str` without format validation (`schemas/cards.py:14,23`) | None | None | `backend/app/schemas/cards.py`, `backend/app/services/search.py` | Medium severity, medium exposure, no detection |
| F8 | Single writer per board database | Two backend processes (workers or containers) share one data directory | `database is locked` 500s; rate limiting and board locks ineffective; conflicting writes | In-memory limiter, per-process locks, SQLite writes (`core/ratelimit.py`, `board_db.py`); Compose runs one container but nothing prevents scaling | Busy timeout, WAL | Only error logs when locks time out | `docker-compose.yml`, `backend/app/core/ratelimit.py`, `backend/app/storage/board_db.py` | High severity, low exposure, weak detection |
| F9 | Search finds matching cards | FTS5 index missing or out of sync | Search returns fewer results than exist | Optional FTS5 (runtime-dependent); triggers maintained in migrations; external tools could write without triggers | LIKE fallback; FTS rebuild on migration | `/search` reports `engine`; `/meta` wrongly reports `fts5: true` | `backend/app/storage/migrations.py`, `backend/app/services/search.py`, `main.py:180` | Low severity, medium exposure, medium detection |
| F10 | Reverse proxy accepts board imports | Proxy rejects payloads above 8 MB while backend rejects above 2 MB | Import fails with an HTML error page, agent gets an unexpected content type | Independent limits (`nginx.conf:client_max_body_size`, `core/config.py:max_request_bytes`) | Both layers limit size | Status code only; no JSON envelope from nginx | `frontend/nginx.conf`, `backend/app/core/config.py` | Low severity, high exposure for large boards, good detection |
| F11 | Activity history and idempotency stores stay bounded | Tables grow without retention | Disk exhaustion; writes fail; backups grow | No pruning (`storage/migrations.py`, `services/common.py`) | Indexed for reads; idempotency expiry on replay only | Disk usage only via host monitoring | `backend/app/storage/migrations.py`, `backend/app/services/common.py` | High severity, low exposure, weak detection |
| F12 | Physical board deletion is deliberate | Operator confirms deletion of an archived board | Board database, backups and metadata are destroyed; no copy remains | `BoardService.delete` removes the database and its backup directory | Requires archived state and exact name confirmation; `boards:admin` scope | Audit entry not written (row and DB are gone) | `backend/app/services/boards.py:delete` | High severity, low exposure, no recovery path |
| F13 | Restore produces a usable board | Restore a corrupted or truncated backup | Board unusable after restore; previous data replaced | Backup files can be damaged on disk; restore does not pre-verify before overwriting | Backup creation verifies integrity; restore validates after | `validate()` runs after restore and returns a report; no rollback | `backend/app/services/backups.py` | High severity, low exposure, medium detection |
| F14 | WebMCP exposes authorized tools | Tool registration throws or the API is absent | Agent sees no tools; user cannot tell whether this is expected | Experimental browser API; registration errors swallowed (`registry.ts`) | Capability detection; UI badge reports availability | Badge only reports API presence, not registration result | `frontend/src/webmcp/registry.ts`, `frontend/src/features/settings/SettingsPage.tsx` | Low severity, high exposure where WebMCP exists, weak detection |
| F15 | Markdown descriptions are safe | Card content contains HTML/JS | Script execution in another user's browser | Untrusted input | Renderer builds React text nodes only; links restricted to http(s) | Unit and E2E tests assert no script/img injection | `frontend/src/lib/markdown.tsx`, `frontend/src/e2e/agent.spec.ts` | Low severity, high exposure, strong detection |
| F16 | Agents stay within granted scopes | Token used beyond its scopes or after revocation | Unauthorized mutation; stale access | Scope check on every request; revocation sets `revoked_at` and disables the actor | Server-side scope enforcement on all endpoints; CSRF for cookie clients | 403/401 tests; activity log records actor | `backend/app/api/deps.py`, `backend/app/services/auth.py`, `tests/test_agents.py` | Low severity, low exposure, strong detection |

## Priorities

**High-severity concerns first (by consequence, then exposure, then control weakness):**

1. **F1** — default secret: severity high, exposure medium, no detection.
2. **F2** — non-exclusive restore: severity high, exposure low, weak detection; a data-integrity failure is unrecoverable if it happens.
3. **F12** — deletion destroys backups: severity high, no recovery path.
4. **F8** — multiple writers: severity high, low exposure today, weak detection.
5. **F11** — unbounded growth: severity high (disk full stops writes), low exposure, weak detection.
6. **F13** — restore of a damaged backup: severity high, low exposure, medium detection.
7. **F3/F4** — interrupted board creation: medium severity, low exposure, weak detection in the crash window.
8. **F6/F7** — duplicate bulk cards and invalid due dates: medium severity, medium exposure, weak or no detection.

F5, F9, F10, F14, F15, F16 are lower priority: effects are contained, detected, or already covered by strong controls.

**No RPN is used** because no agreed scales exist and none of occurrence values could be evidenced from incident history.

## Recommended actions

| Action | Targets | Cause or control gap | Expected effect | Owner / status | Residual-risk plan |
| --- | --- | --- | --- | --- | --- |
| Generate and persist a per-install session secret when `KANBAN_SECRET_KEY` is unset, and reject the known insecure literal in production mode. | F1 | Hardcoded default with no guard | Forged cookies require the local secret file | Implemented (2026-10-30) | Re-check after rotation documentation exists |
| Hold a per-board lock shared by `open()` and `restore()` so restore is exclusive within the process. | F2 | No synchronization between engine disposal and readers | No in-process reader observes a partial file | Implemented (2026-10-30) | Add a failure-injection test; cross-process remains a documented constraint |
| On transfer finalize failure, archive the source card and record the incomplete finalize in the activity log. | F5 | Only a warning was returned | Users see one card; reconcile later | Implemented (2026-10-30) | Operator reconciliation procedure still needed |
| Validate and normalize `due_at` to ISO 8601 at the API boundary; reject other formats. | F7 | Free-text accepted | Overdue and due ordering stay correct | Implemented (2026-10-30) | Clients with free-text input must change |
| Accept `Idempotency-Key` on bulk creation and replay the stored response. | F6 | No idempotency on bulk | Retries do not duplicate cards | Implemented (2026-10-30) | Stored responses expire with the idempotency TTL |
| Reserve the board id in the idempotency record before initializing the board, and resolve retries to that board. | F4 | Record written after the side effect | No duplicate boards after a crash | Implemented (2026-10-30) | Retry during initialization returns a conflict until recovery |
| Pre-verify a backup file before overwriting the live database. | F13 | Validation only after restore | Corrupt backups are rejected before data is replaced | Implemented (2026-10-30) | Damaged-backup recovery still relies on other backups |
| Report FTS5 capability truthfully and document the LIKE fallback. | F9 | `/meta` hardcoded `true` | Agents no longer assume FTS-only syntax | Implemented (2026-10-30) | — |
| Align nginx and backend body limits and document the proxy-level behavior. | F10 | Mismatched limits | Large imports succeed; expectation set | Implemented (2026-10-30) | Proxy 413 still returns HTML |
| Require an export or verified backup artifact before physical board deletion, and write an audit entry before removing the database. | F12 | Deletion removes all copies | A mistaken deletion leaves an artifact | TBD (needs product decision on retention) | Depends on the decision |
| Add retention/pruning for activity and idempotency tables. | F11 | Unbounded growth | Bounded storage | TBD (needs audit-retention requirement) | Confirm retention policy |
| Declare and enforce a single backend process per data directory, or introduce a shared coordination store before scaling out. | F8 | Implicit single-writer assumption | Prevents silent corruption and ineffective limits | Documented constraint (2026-10-30) | Revisit for multi-host |
| Surface WebMCP registration failures in logs and the settings badge. | F14 | Swallowed errors | Operators can diagnose missing tools | TBD | Low priority |

## Assumptions and open questions

- **Missing requirements:** no agreed severity/occurrence/detection scales, no recovery point objective, no audit-retention policy, no defined operator skill level.
- **Evidence gaps:** no incident history, no load measurements, no backup age data, no data on how often agents retry requests. Occurrence is therefore not rated.
- **Stakeholders needed:** operator (backup cadence, deletion policy), security owner (secret handling, TLS termination), auditor (retention), product owner (multi-user plans).
- **Complementary analyses required:**
  - Security threat modeling for deliberate attacks (session forgery, token theft, CSRF bypass, SSRF through board content links); this FMEA only records accidental and misconfiguration failures.
  - Fault-tree analysis for combinations (disk full + restore + simultaneous agent writes).
  - The ATAM report `analysis/atam-architecture-analysis/2026-10-30-ai-native-kanban-mvp-architecture.md` for quality-attribute tradeoffs.
- **Verification plan for implemented actions:** backend tests cover due-date validation, transfer fallback, bulk idempotency, board reservation, restore pre-verification and secret handling; E2E continues to cover agent scopes and Markdown safety.
