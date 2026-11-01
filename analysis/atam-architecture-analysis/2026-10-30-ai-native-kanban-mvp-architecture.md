2026-10-30

# ATAM Architecture Analysis: ai-native kanban mvp architecture

## At a glance

9 risks · 3 sensitivity points · 2 tradeoff points · 4 non-risks · provisional: yes

- A deployment that never sets `KANBAN_SECRET_KEY` signs sessions with a published default, so anyone who reads the repository can forge a login; the service should generate its own secret and never use the published default (risk F2, observed, Findings).
- Restoring a backup closes the board engine and overwrites the live database file with no per-board lock, so a concurrent request can read a half-restored board; restore needs to exclude readers (risk F3, observed, Findings).
- Card due dates accept any string, so overdue filters and due-date sorting silently return wrong answers for users and agents; the API should validate ISO 8601 (risk F5, observed, Findings).

## Scope and evidence

**System boundary:** the self-hosted AI-native Kanban application in this repository: FastAPI backend, React frontend, registry plus one SQLite database per board, REST API, WebMCP adapter, Docker deployment. Excluded: the host operating system, reverse proxies other than the bundled nginx configuration, and any future multi-tenant service.

**Evaluation purpose:** repository-based ATAM-style review of how the implemented architecture supports the specification's quality goals, to prioritize hardening work before further feature growth.

**Evidence inspected (observed):**
- `backend/app/` (56 route handlers, services, storage, security, migrations), 38 pytest tests at
  analysis time (52 after the recommendations below were implemented).
- `frontend/src/` (TanStack Query, dnd-kit board, safe Markdown renderer, WebMCP adapter), 15 Vitest tests, 14 Playwright journeys.
- Deployment: `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.yml`.
- Design records: `docs/architecture.md`, `docs/database.md`, `docs/api.md`, `docs/decisions/0001`-`0005`, `AGENTS.md`.

**Participants:** none available. Business drivers and requirement priorities below are taken from the specification text that this implementation targets and from its acceptance criteria (`README.md`), not from stakeholder interviews.

**Assumptions and limitations:**
- No stakeholder priorities, production incident data, load measurements or operating conditions were available. Scenario priorities are therefore **candidate** priorities derived from the specification, and every result is **provisional**.
- Response measures are the specification's engineering targets ("p95 under 200 ms for ordinary local card reads", "100 boards", "10,000 cards per board"), not measured values. No performance measurement was run for this report.
- Claims about runtime behaviour come from reading code and configuration; none were validated against a load or failure-injection test except where a listed test exists.

## Business drivers and utility tree

**Business drivers (source: specification and `README.md`):**
- D1 Local-first, self-hosted operation with no external AI provider or cloud dependency.
- D2 AI agents are first-class clients with auditable, least-privilege access.
- D3 Board data is portable and recoverable (per-board export, backup, restore).
- D4 Single-host operation for at least 100 boards and 10,000 cards per board with p95 < 200 ms for ordinary local reads.
- D5 A maintainable, testable codebase that a small team can extend without duplicating business rules.

**Quality attributes selected:** security (D2), data integrity/recoverability (D3), performance (D4), availability/operability (D3, D4), modifiability (D5).

**Candidate utility tree (business importance / technical difficulty, judged from specification emphasis and code evidence):**

| ID | Scenario | Attribute | Importance | Difficulty |
| --- | --- | --- | --- | --- |
| QS1 | An operator deploys the containers without setting a session secret; an attacker forges a session cookie for the admin actor. | Security | High | Low |
| QS2 | An admin restores a board backup while a user is reading the board; no request observes missing or partial data. | Integrity/Availability | High | Medium |
| QS3 | Two agents update the same card concurrently; the later write is rejected with the current version. | Integrity | High | Low |
| QS4 | A dashboard lists 100 boards within the p95 target while other API traffic continues. | Performance | High | Medium |
| QS5 | The backend process dies between creating the registry row and initializing the board database; after restart the board is either usable or visibly failed, never a silent trap. | Recoverability | Medium | Medium |
| QS6 | An agent creates a card with `Idempotency-Key` after a network timeout; exactly one card exists. | Integrity | Medium | Low |
| QS7 | An agent creates 50 cards in one bulk request; retrying the request does not duplicate cards. | Integrity | Medium | Low |
| QS8 | A card due date of "next Tuesday" or "2026-13-45" is submitted; the API rejects it instead of corrupting overdue queries. | Correctness | Medium | Low |
| QS9 | An external agent completes discovery, card creation, movement and search through REST alone, with scope enforcement and an audit trail. | Interoperability/Security | High | Low |
| QS10 | A new card field is added end-to-end; changes stay inside schema, service, one API route and tests. | Modifiability | Medium | Medium |

## Architecture and approaches

**Style (observed):** modular monolith. A single FastAPI application exposes `/api/v1`, all interfaces (React, WebMCP, external agents) call the same service functions in `backend/app/services`, and storage is split into a registry database plus per-board databases (`docs/architecture.md`, decision 0001).

**Significant approaches and their quality effects:**

| Approach | Evidence | Quality effect |
| --- | --- | --- |
| Per-board SQLite with a registry authority and UUID-only path resolution | `backend/app/storage/board_db.py`, `registry.py` | Strong isolation, simple per-board backup/restore and deletion; costs cross-board consistency and is why transfer is copy-then-delete |
| `NullPool` engines with idle sweep and a 64-board cache cap | `board_db.py` | Bounds open file handles (operability), at the cost of re-opening databases under sparse access |
| Explicit `maintenance → active/error` recovery states | `board_db.py`, `services/boards.py`, decision 0002 | Makes interrupted multi-file operations observable; recovery only runs at startup |
| Versioned card mutations with `409 version_conflict` | `services/cards.py`, `schemas/cards.py`, tests | Multi-agent safety; requires every client to carry versions |
| Session cookie (HMAC-signed) plus CSRF double-submit; scoped bearer tokens stored hashed | `core/security.py`, `api/deps.py`, tests | No external auth provider; session revocation is only by expiry |
| Gap-based integer ordering with lazy normalization | `services/common.py`, decision 0003 | Cheap reorders; normalization bounds |
| FTS5 external-content index with `LIKE` fallback | `storage/migrations.py`, `services/search.py` | Good local search where available; capability varies by runtime |
| Idempotency records with payload fingerprints | `services/common.py`, board and card creation | Safe retries for single-entity creation |
| Structured JSON logs with request ids and actor ids | `main.py` | Auditable requests; no metrics or readiness differentiation |
| WebMCP adapter behind a capability check, scope-filtered registration | `frontend/src/webmcp/*`, decision 0004 | Agent discoverability without coupling; registration failures are silent |
| Docker: nginx static frontend proxying `/api` to a single backend container on one data volume | `docker-compose.yml`, `nginx.conf` | Simple deployment; implicitly single backend process |

## Scenario analysis

| ID | Stimulus and environment | Expected response | Response measure | Evidence and reasoning |
| --- | --- | --- | --- | --- |
| QS1 | Deployment starts with default environment; forged session cookie presented. | Startup refuses, or the secret is unique per install so forged cookies fail. | Zero valid forged sessions. | `core/config.py:16` sets a literal default; `security.read_session_value` verifies with that value. No startup guard exists. Observed. |
| QS2 | Admin restores backup while a GET card request is in flight. | Restore excludes reads; readers see either old or restored data, never partial. | No request observes a missing table or stale WAL state; restore reports integrity ok. | `services/backups.py:restore` calls `boards.close()`, snapshots over the live file, then validates. `BoardDatabaseManager.open` can be called by another thread between those steps (no lock) and will create a fresh engine against the half-written file. Observed by inspection; no test exercises concurrency. |
| QS3 | Two concurrent PATCH requests with the same version. | Second request gets `409 version_conflict` with `current_version`. | Exactly one winner; audit entry per mutation. | `services/cards.py` compares `payload.version` inside a single write transaction; covered by `tests/test_cards.py::test_version_conflict_returns_409`. Observed and tested. |
| QS4 | Dashboard load with 100 boards, 50 per page. | List returns within target. | p95 < 200 ms (specification target, not measured). | `services/boards.py:list` calls `_counts()` per returned board, opening each board database and running two `COUNT(*)` queries. 50 opens per page plus registry read. No measurement exists, so the outcome is unknown; the growth is linear in page size. Sensitive. |
| QS5 | Kill -9 during board creation after registry insert. | Board is `maintenance`/`error`, never a usable-looking empty board. | Recovery at next startup sets `active` or `error`. | `BoardService.create` inserts `maintenance`, initializes, then flips to `active`; `recover()` runs only at startup and repairs leftovers. No sweeper during runtime and no test for the interrupted path. Observed. |
| QS6 | Retry of card creation with the same `Idempotency-Key` after timeout. | Same card returned; no duplicate. | One card row; replayed response flagged. | `run_idempotent` stores fingerprint plus response inside the board transaction; tested in `tests/test_cards.py::test_card_creation_idempotency`. Observed and tested. |
| QS7 | Retry of `/cards/bulk` after timeout. | Same semantics as QS6. | No duplicated cards. | `api/v1/cards.py:bulk_create_cards` accepts no idempotency key and applies per-card savepoints. A retry duplicates all successful cards. Observed risk. |
| QS8 | Card created with a non-date `due_at`. | `422 validation_failed`. | Overdue filters and `due_at` ordering remain correct. | `schemas/cards.py` declares `due_at: str | None` without format validation; `search.py` compares the string lexicographically. Observed. |
| QS9 | Bearer-token agent creates and moves cards, creates no boards. | Success for permitted actions, `403` otherwise, activity attributed to the agent. | Covered by an automated journey. | `frontend/e2e/agent.spec.ts` asserts card creation, move, `403` on board creation and an `agent` badge in the activity panel; `tests/test_agents.py` asserts scopes and auditing. Observed and tested. |
| QS10 | Add a new card field. | Locality of change. | Files touched and test coverage. | Current path: `schemas/cards.py` → `services/cards.py` (571 lines, largest module) → `api/v1/cards.py` → frontend types and card dialog → migration if persisted. No repository abstraction separates persistence from rules. Observed; moderate coupling. |

## Findings

| ID | Type | Finding | Scenarios / attributes | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| F1 | Risk | Board creation spans a registry transaction and a filesystem initialization; a crash in between leaves a `maintenance` row that is only repaired at the next startup, and no runtime sweeper exists. | QS5 / recoverability | `services/boards.py:create`, `recover` | High |
| F2 | Risk | Insecure default session secret is accepted silently, allowing cookie forgery in a misconfigured deployment. | QS1 / security | `core/config.py:16`, `core/security.py` | High |
| F3 | Risk | Backup restore is not exclusive: the engine is disposed and the live file overwritten while other requests may reopen it. | QS2 / integrity | `services/backups.py:restore`, `storage/board_db.py:open` | High |
| F4 | Risk | Cross-board transfer finalization failure leaves a duplicated card with only a warning; nothing reconciles it later. | QS2 / integrity | `services/cards.py:584-593` | High |
| F5 | Risk | Card `due_at` is an unvalidated string, so overdue filters, due-before filters and due sorting can return wrong results. | QS8 / correctness | `schemas/cards.py:14,23`, `services/search.py` | High |
| F6 | Risk | Bulk card creation has no idempotency, so a retried bulk request duplicates cards. | QS7 / integrity | `api/v1/cards.py:bulk_create_cards` | High |
| F7 | Risk | Board-creation idempotency is recorded after the side effect; a crash between the two transactions lets a retry create a second board. | QS5, QS6 / integrity | `services/boards.py:create` | Medium |
| F8 | Sensitivity point | Dashboard board counts open every listed board database, so listing cost grows with page size and board count. | QS4 / performance | `services/boards.py:list,_counts` | Medium |
| F9 | Sensitivity point | `/meta` always advertises `fts5: true` although search falls back to `LIKE` when FTS5 is unavailable. | QS9 / interoperability | `main.py:180`, `services/search.py` | Medium |
| F10 | Sensitivity point | The backend is implicitly single-process (in-memory rate limiter, in-process board locks, SQLite writes); nothing prevents a multi-worker or multi-container deployment. | QS2, QS4, QS5 / availability | `core/ratelimit.py`, `main.py`, `docker-compose.yml` | Medium |
| F11 | Tradeoff point | Per-board isolation buys portability and blast-radius containment but costs cross-board consistency and forces serial global search and copy-then-delete transfer. | QS2, QS4 / integrity, performance | decisions 0001/0002, `services/search.py`, `services/cards.py:transfer` | High |
| F12 | Tradeoff point | WebMCP contextual registration improves agent discovery but swallows registration failures, so tools can silently disappear. | QS9 / operability | `frontend/src/webmcp/registry.ts` | Medium |
| F13 | Non-risk | Card concurrency control works as designed and is covered by tests. | QS3 / integrity | `services/cards.py`, `tests/test_cards.py` | High |
| F14 | Non-risk | Authentication, CSRF and scope enforcement are implemented consistently and covered by backend and E2E tests. | QS9 / security | `core/security.py`, `api/deps.py`, `tests/test_agents.py`, `frontend/e2e/agent.spec.ts` | High |
| F15 | Non-risk | Backups use SQLite's online backup API and are integrity-checked; restore re-validates. | QS2 / integrity | `services/backups.py`, `tests/test_backups.py` | High |
| F16 | Non-risk | Board isolation is enforced by UUID-only ids plus registry lookups; traversal attempts are tested. | QS2 / security | `storage/board_db.py`, `tests/test_boards.py` | High |
| F17 | Risk | Request-size limits disagree across layers: nginx allows 8 MB while the backend default rejects above 2 MB, and a rejected proxy request returns HTML instead of the JSON envelope. | QS9 / operability | `frontend/nginx.conf`, `core/config.py:max_request_bytes` | High |
| F18 | Risk | Activity log and idempotency records have no retention or pruning; storage grows without bound and no operational guidance exists. | QS4, QS5 / operability | `storage/migrations.py`, `services/common.py` | Medium |

**Risk themes:**
- **Multi-file and multi-process integrity (F1, F3, F4, F7, F10):** the architecture accepts explicit intermediate states, but repair is startup-only and nothing serializes restore or prevents parallel writers.
- **Input trust at the edges (F5, F17):** formats and size limits are enforced inconsistently between layers.
- **Capability honesty (F9, F12):** the system reports more capability than it can verify at runtime.
- **Growth and retention (F8, F18):** costs scale linearly with boards and records, without measurement or retention policy.

## Recommendations and open questions

| Recommendation | Addresses | Expected benefit | Cost / tradeoff | Status |
| --- | --- | --- | --- | --- |
| Remove the hardcoded default secret: generate and persist a per-install secret when none is configured, and refuse the insecure literal in a production mode. | F2 | Forgery requires the local secret file; secure-by-default installs. | One extra file under `data/`; secret rotation requires a documented procedure. | Implemented |
| Serialize restore with a per-board lock shared with `open()`, and validate only after releasing it. | F3 | No reader observes a partially restored file within one process. | Cross-process safety still requires a single backend instance. | Implemented |
| Fall back to archiving the source card when the final delete fails during transfer, and audit the incomplete finalize. | F4 | Users see one card instead of two after a partial failure. | The source is archived rather than moved; operators must still reconcile deliberately. | Implemented |
| Validate and normalize `due_at` as ISO 8601 at the schema boundary. | F5 | Overdue and due-date queries stay correct for humans and agents. | Clients sending free text now get `422`. | Implemented |
| Accept `Idempotency-Key` on bulk creation and replay the stored batch response. | F6 | Safe retries for agent batches. | Stored responses add bytes until expiry. | Implemented |
| Record a pending idempotency reservation (with the future board id) before initializing a board, and resolve a retry to the existing board. | F7 | No duplicate boards after an interrupted creation. | One extra registry write per creation; a visible "in progress" conflict during recovery. | Implemented |
| Report FTS5 capability truthfully in `/meta` based on the SQLite build, and document the fallback. | F9 | Agents stop assuming FTS-only syntax works. | Small runtime check. | Implemented |
| Align request-size limits: raise the backend default to match nginx and document that proxy-level rejections are not enveloped. | F17 | Large board imports succeed; limit mismatch removed. | A larger accepted body increases memory exposure per request. | Implemented |
| Measure dashboard listing with 100 boards and add a counts cache or aggregate counters if the target is missed. | F8 | Evidence-based performance decision. | Cache invalidation complexity if adopted. | Open question |
| Declare and enforce a single backend process per data directory (deployment documentation and startup signal), or move coordination to an external store before scaling out. | F10 | Prevents silent corruption and ineffective rate limits. | Blocks horizontal scaling until a shared store exists. | Documented constraint |
| Add retention/pruning for `activity_log` and `idempotency_records`. | F18 | Bounded storage growth. | Deleted audit history must respect auditing requirements. | Open question |
| Surface WebMCP registration failures to the UI/log instead of swallowing them. | F12 | Operators learn why tools are missing. | Small amount of noise when the API is absent. | Open question |

**Open questions for stakeholders:**
1. What are the real p95 targets and expected board/card volumes on the target host? (QS4 is currently measured against specification targets only.)
2. Is horizontal scaling a requirement, or is one backend process per install acceptable? (F10.)
3. How long must activity history be retained for audit purposes? (F18.)
4. Which actor may physically delete a board, and is a second approver required? (Currently `boards:admin` plus exact name confirmation.)
5. Is free-text due-date entry expected in any client, or is ISO 8601 always acceptable? (F5.)

**Validation of this report:** repository-only assessment. The quality-attribute priorities are candidates derived from the specification and were not confirmed by stakeholders. No load, failure-injection or restore-concurrency test was run for the analysis; the implemented changes listed above are covered by the tests named in `analysis/fmea/2026-10-30-ai-native-kanban-platform.md` and the repository test suite.
