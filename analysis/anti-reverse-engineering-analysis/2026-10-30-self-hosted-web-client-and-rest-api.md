2026-10-30

# Anti-reverse-engineering analysis: self-hosted web client and REST API

Code state: 9f18fa6 (clean). Code author: GitHub Copilot (this agent family). Reviewer: GitHub Copilot (same family; AGENTS.md defines no independence rule).

## At a glance

10 findings · CRITICAL 0 · HIGH 1 · MEDIUM 4 · LOW 5 · VERIFIED 9 · PLAUSIBLE 1

- Someone who reaches a freshly started install before the operator sets a password can sign in as the administrator, because the fallback credential is the published word "admin" (HIGH · VERIFIED · HIGH-1).
- Anyone can download the complete API description and Swagger UI without signing in, which maps every operation, including administration and backup endpoints (MEDIUM · VERIFIED · MEDIUM-3).
- A failed bulk card request can hand the caller raw database or driver text, which reveals internal implementation details (MEDIUM · VERIFIED · MEDIUM-2).

## Scope

**In scope:** the whole repository at commit `9f18fa6`: React client bundle produced by `frontend/` (`pnpm build`), FastAPI REST API (`backend/app`), the nginx/uvicorn deployment configuration, and the responses, headers, errors and credentials those surfaces produce.

**What was read:** `AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/api.md`, `docs/database.md`, all of `backend/app`, `frontend/src` (API client, auth, board/card features, WebMCP tools), `frontend/vite.config.ts`, `frontend/package.json`, `frontend/nginx.conf`, `frontend/Dockerfile`, `backend/Dockerfile`, `backend/requirements.txt`, `docker-compose.yml`, `.env.example`, and the earlier reports under `analysis/`.

**What was built and run:** `pnpm build` (production bundle) and the skill's `scripts/scan_build.py frontend/dist` with three forbidden strings (`dev-insecure-secret-change-me`, `session-secret`, `board.sqlite`). Result: 3 files, 519 KB, 0 SECRET, 0 LEAK, 1 REVIEW.

**What was skipped:** no live or shared system was contacted; no production deployment was inspected. No native client, mobile app, game client or delivered device exists in this product, so those checklist sections do not apply. Timing measurements were not run (noted where that matters).

## Product and core value

**Product:** a self-hosted, single-user Kanban board for humans and AI agents. The React client is a thin view over a REST API; each board is its own SQLite database; agents authenticate with scoped bearer tokens.

**Users and roles:** one human administrator (implicitly all scopes) and any number of agent tokens with explicit scopes (`boards:read/write/admin`, `cards:read/write`, `comments:write`). There is no anonymous role with data access and no second human role, so cross-user disclosure is not a meaningful category today.

**Core value a competitor would want:** the board data and the workflow rules (ordering, versioning, activity history, per-board isolation), plus the agent integration. The rules themselves are not secret; the data is the asset. There is no proprietary scoring, matching or ranking algorithm in this product.

## Exposure map

| Surface | Path | What an outsider gets | Status |
| --- | --- | --- | --- |
| Web bundle | `frontend/dist/assets/index-*.js` (504 KB), `index.html`, CSS | Client code for all routes, including the settings/credential screen that every signed-in user can open | LOW-5 |
| Source maps | `frontend/dist` | None shipped; Vite production build emits no `.map` files (verified by directory scan and `scan_build.py`) | Clean |
| Client storage | `localStorage` | Theme preference only; no tokens (session is an HttpOnly cookie, CSRF cookie is a non-secret random value) | Clean |
| API responses | `/api/v1/**` | Caller's own board data, entity UUIDs, versions, timestamps, audit entries for that board | Clean apart from listed findings |
| Error responses | all | Stable envelope `{success:false, error:{code,message,retryable,details}, request_id}`; generic 500 handler | MEDIUM-2, MEDIUM-4 |
| Exports and backups | `/boards/{id}/export`, `/boards/{id}/backups` | Full board archive for the caller (intended); backup creation also exposed the server directory path | MEDIUM-1 |
| Credentials held by the client | `kanban_session` (HttpOnly, SameSite=Lax, signed), `kanban_csrf` (readable, doubles as CSRF proof), bearer tokens returned once | Cookie theft via injected script is limited by HttpOnly; the CSRF value alone is not an authenticator | Clean |
| Public metadata | `/openapi.json`, `/docs`, `/api/v1/health`, `/api/v1/meta`, `/api/v1/auth/scopes` | Full API schema and version; feature/scope lists | MEDIUM-3, LOW-4 |
| Listing surfaces | `/boards`, `/boards/{id}/cards`, `/search`, pagination `limit<=200` | Authenticated caller can enumerate its own data only; no anonymous listing | Clean |
| Server banners | uvicorn `Server` header, nginx `Server` header | Server product/version | LOW-2 |
| Build/deployment files | `Dockerfile`s, `nginx.conf`, `.env.example`, compose | No secrets; placeholder values only | Clean |

## Findings

| ID | Severity | Category | Finding in one sentence | Location | Verdict | Slice |
| --- | --- | --- | --- | --- | --- | --- |
| HIGH-1 | HIGH | LEAK (credentials) | A fresh install accepts the published fallback password `admin` for the administrator when the operator does not set one. | `backend/app/core/config.py:25`, `backend/app/storage/registry.py:bootstrap_admin` | VERIFIED | 1 |
| MEDIUM-1 | MEDIUM | LEAK (response content) | Creating a backup returns the absolute server directory in `data_dir`. | `backend/app/services/backups.py:57` | VERIFIED | 2 |
| MEDIUM-2 | MEDIUM | LEAK/ORACLE (errors) | Bulk creation returns the raw exception text for each failed card. | `backend/app/services/cards.py:254` | VERIFIED | 2 |
| MEDIUM-3 | MEDIUM | LEAK (metadata) | `/openapi.json` and `/docs` are reachable without authentication and enumerate the whole API. | `backend/app/main.py:63-64`, `frontend/nginx.conf` | VERIFIED | 3 |
| MEDIUM-4 | MEDIUM | LEAK (errors) | A failed transfer finalize returns the raw exception text in `warning` and stores it as the activity `reason`. | `backend/app/services/cards.py:628` region | VERIFIED | 2 |
| LOW-1 | LOW | ORACLE (timing) | An unknown user name skips password hashing, so the response can be distinguished from a wrong password by time. | `backend/app/services/auth.py:30-32` | PLAUSIBLE (code path observed; timing not measured) | 4 |
| LOW-2 | LOW | Headers | API responses carry no `Cache-Control`, 401 has no `WWW-Authenticate`, and uvicorn/nginx send product banners. | `backend/app/main.py`, `backend/Dockerfile`, `frontend/nginx.conf` | VERIFIED | 5 |
| LOW-3 | LOW | Headers | `X-Request-ID` echoes arbitrary client-supplied text (length-capped) into the response and logs. | `backend/app/main.py:78-83` | VERIFIED | 5 |
| LOW-4 | LOW | SCRAPING/metadata | `/api/v1/meta` and `/api/v1/auth/scopes` are unauthenticated metadata endpoints. | `backend/app/main.py`, `backend/app/api/v1/auth.py` | VERIFIED | 4 |
| LOW-5 | LOW | LEAK (shipped code) | The sign-in screen shipped the exact server environment variable names used for bootstrap credentials. | `frontend/src/features/auth/LoginPage.tsx` | VERIFIED | 6 |

### HIGH-1 [LEAK]: default administrator password is a published word

- Location: `backend/app/core/config.py:25` sets `bootstrap_password: str = "admin"`; `backend/app/storage/registry.py:bootstrap_admin` hashes it into the first user, and `AuthService.login` accepts it.
- Outsider scenario: an operator starts the container without `KANBAN_BOOTSTRAP_PASSWORD` (the variable is optional in the code even though Compose requires it). The attacker, who knows the project, signs in with `admin`/`admin`, obtains the full administrator session, reads and mutates every board, and issues agent tokens.
- Why tests miss it: `tests/conftest.py` and the Playwright config set an explicit password, so the default path is never exercised.
- Verdict: VERIFIED (read the code path; `docker-compose.yml` requires the variable, but direct `uvicorn`/`python -m` runs and the documented local quick start do not).

### MEDIUM-1 [LEAK]: backup creation discloses the server directory

- Location: `backend/app/services/backups.py:57` returns `"data_dir": str(directory)` and the API passes it through.
- Outsider scenario: an authenticated caller (or a curious agent with `boards:write`) calls `POST /boards/{id}/backups` and learns the host path layout, which supports path-based follow-up attacks and reveals the deployment layout; no view needs it.
- Why tests miss it: `tests/test_backups.py` asserts verification and listing but not field minimalism.
- Verdict: VERIFIED.

### MEDIUM-2 [LEAK/ORACLE]: bulk creation echoes internal exception text

- Location: `backend/app/services/cards.py:254` appends `{"index": index, "error": str(exc)}`; exceptions can come from SQLAlchemy/SQLite, not only from the service's own validation.
- Outsider scenario: an agent posts a batch that triggers a database-level failure (for example a constraint or lock error) and receives driver text that may include table names, SQL fragments or file paths, then uses it to probe the schema.
- Why tests miss it: the partial-failure test uses an unknown list id, so only the service's own message is returned.
- Verdict: VERIFIED (the code path is unconditional; producing a raw driver message requires an environment-dependent failure).

### MEDIUM-3 [LEAK]: API documentation is public

- Location: `backend/app/main.py:63-64` enables `/openapi.json` and `/docs` by default; `frontend/nginx.conf` proxies both paths.
- Outsider scenario: an unauthenticated visitor downloads the schema, learns every endpoint, scope and payload shape, including `/credentials`, `/boards/{id}/backups` and `/credentials/{id}/revoke`, and targets the deployment accordingly.
- Why tests miss it: no test asserts an authentication requirement for the documentation routes.
- Verdict: VERIFIED.

### MEDIUM-4 [LEAK]: transfer warning echoes internal exception text

- Location: `backend/app/services/cards.py` builds `warning = f"Card was copied but the source copy could not be removed: {exc}"` and also stores `reason: str(exc)` in the activity entry.
- Outsider scenario: a caller triggers a finalize failure (for example by racing a restore) and reads a driver message that names the file or table involved.
- Why tests miss it: the fallback test simulates a plain `RuntimeError` with a controlled message.
- Verdict: VERIFIED.

### LOW-1 [ORACLE]: unknown user names skip password hashing

- Location: `backend/app/services/auth.py:30-32` short-circuits `record is None or not verify_password(...)`.
- Outsider scenario: request timing separates "no such user" from "wrong password". With a single known account the value is low; it also enables cheaper username probing before password attacks.
- Why tests miss it: tests assert equal status and code, not timing.
- Verdict: PLAUSIBLE (timing difference not measured; the code path is unambiguous).

### LOW-2 [Headers]: caching and banner hygiene

- Location: `backend/app/main.py` middleware adds `X-Request-ID`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` but no `Cache-Control`; 401 responses have no `WWW-Authenticate`; `frontend/nginx.conf` does not set `server_tokens off`; `backend/Dockerfile` starts uvicorn without `--no-server-header`.
- Outsider scenario: shared caches may store personal board data; version banners help select exploits; a missing `WWW-Authenticate` is a protocol defect rather than an attack.
- Why tests miss it: no header assertions.
- Verdict: VERIFIED.

### LOW-3 [Headers]: request-id reflection

- Location: `backend/app/main.py:78-83` accepts an incoming `X-Request-ID` of up to 100 characters and returns it in the response header and logs.
- Outsider scenario: a caller fills logs and response headers with arbitrary text (for example to forge log entries) within the length limit; Starlette blocks header injection, so impact is low.
- Why tests miss it: no test sends a hostile request id.
- Verdict: VERIFIED.

### LOW-4 [SCRAPING/metadata]: unauthenticated metadata endpoints

- Location: `backend/app/main.py` `/api/v1/meta` and `backend/app/api/v1/auth.py` `/api/v1/auth/scopes`.
- Outsider scenario: an unauthenticated visitor learns the scope vocabulary and feature flags, useful for targeted probing. Nothing user-specific is exposed.
- Why tests miss it: `/meta` is only tested with a session.
- Verdict: VERIFIED.

### LOW-5 [LEAK]: server environment variable names in the sign-in bundle

- Location: `frontend/src/features/auth/LoginPage.tsx` rendered `<code>KANBAN_BOOTSTRAP_USERNAME</code>` and `<code>KANBAN_BOOTSTRAP_PASSWORD</code>` in a help paragraph, which the production bundle contains verbatim (found by the new build guard, `scripts/check-client-build.mjs`).
- Outsider scenario: a visitor reads the bundle, learns the deployment's configuration vocabulary, and uses it to tailor advice/attacks (for example, requesting that an operator set those names). No credential value is exposed.
- Why tests miss it: no test inspected the built bundle before the guard existed.
- Verdict: VERIFIED.

## Clean areas

- **Client business logic (LOGIC):** positions, ordering, version conflicts, scope checks, status transitions and archiving are enforced in `backend/app/services/*`; the client duplicates only display rules and always sends `version`, which the server re-checks (`services/cards.py`). No server action is protected only by hidden UI.
- **Shipped code and data (LEAK):** the production bundle contains no source maps, no comments with internal hosts, no server code, no test tools, no unreleased features and no credential constants. `scan_build.py` found only React Router's internal `http://localhost` placeholder constant (library code, not configuration). Server environment variable names were present (LOW-5) and are now covered by the build guard.
- **Tokens and sessions:** the session cookie is signed and HttpOnly; the CSRF value is a random non-secret used as double-submit proof; bearer tokens are shown once and stored only as SHA-256 hashes; no token in URLs or `localStorage`; logout clears cookies; tokens can be revoked and revoked tokens are rejected (tested end to end).
- **Response content and identifiers:** entity ids are random UUIDv4, not sequential; responses contain only the caller's own board data; no other-user data model exists.
- **Error envelope for validation:** structured `validation_failed` details list only the caller's own input fields; 404/403 codes are stable and do not disclose foreign resources.
- **Scraping and quotas:** all data endpoints require authentication; pagination is capped at 200; global search scans at most 25 boards; per-actor rate limiting is applied on every authenticated request and per address on login; exports and imports require write/admin scopes.
- **Headers that exist:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, restrictive CSP in nginx, CORS allowlist (empty by default in Compose), `SameSite=Lax` cookies, `Secure` flag configurable for TLS deployments.
- **Deployment files:** `.env.example` and compose contain placeholders only; `.env`, databases and secrets are gitignored; secrets are generated per install.
- **Native/device surfaces:** none exist in this product.

## Refactoring plan

### Slice 1: No usable default administrator credential

- **Goal:** a fresh install cannot be entered with a published password.
- **Findings covered:** HIGH-1.
- **Changes:** in `storage/registry.py:bootstrap_admin`, treat the shipped defaults (`admin`, `change-me`, empty) as "no password chosen": generate a random password, store its hash, and write the generated password once to the server log with a clear warning. Document the behaviour in README and `.env.example`.
- **Guard:** backend test that bootstrapping with the default settings produces a user whose stored hash does not verify `admin`, and that login with `admin` returns 401.
- **Size:** S (one function plus a test).
- **Risk:** an operator who relied on `admin`/`admin` must read the startup log; documented.
- **Done when:** the test passes and the startup log contains the generated-password notice.

### Slice 2: Responses stop echoing internals

- **Goal:** callers never receive server paths or driver text.
- **Findings covered:** MEDIUM-1, MEDIUM-2, MEDIUM-4.
- **Changes:** drop `data_dir` from the backup response; replace bulk-failure text with a stable `code`/`message` (`card_create_failed`, plus the service's own validation message when the cause is a validation failure) and log the exception; replace the transfer warning and activity `reason` with the stable code `source_delete_failed`.
- **Guard:** tests asserting the backup payload has no absolute path, that bulk failures expose only `index`/`code`/`message`, and that a simulated finalize failure yields a generic warning without exception text.
- **Size:** S.
- **Risk:** operators lose inline driver detail in the response; it remains in server logs.
- **Done when:** tests pass and a simulated failure contains no `Traceback`, `sqlite`, `SQLAlchemy` or path text.

### Slice 3: API documentation requires a session

- **Goal:** unauthenticated visitors cannot enumerate the API.
- **Findings covered:** MEDIUM-3.
- **Changes:** keep `KANBAN_ENABLE_DOCS` as the master switch, add `KANBAN_DOCS_REQUIRE_AUTH` (default true), and serve `/docs` and `/openapi.json` through routes that apply the normal authentication dependency when the flag is set. Update nginx comments and README.
- **Guard:** tests that unauthenticated `/openapi.json` and `/docs` return 401 and that an authenticated session receives the schema.
- **Size:** S.
- **Risk:** bearer-only agents cannot use the Swagger UI (they can still fetch the schema with their token); documented.
- **Done when:** tests pass and the settings page link works after login.

### Slice 4: Uniform login work and authenticated metadata

- **Goal:** no timing oracle for account existence and no anonymous endpoint inventory.
- **Findings covered:** LOW-1, LOW-4.
- **Changes:** verify against a precomputed dummy hash when the user does not exist, then fail with the same code; require authentication for `/api/v1/meta` and `/api/v1/auth/scopes`.
- **Guard:** tests for equal status/code for an unknown user and a wrong password, and 401 for both metadata endpoints without a session. Timing remains measured only qualitatively; a timing test is proposed as a follow-up.
- **Size:** S.
- **Risk:** agents that read `/meta` before authenticating must authenticate first; no client uses it.
- **Done when:** tests pass.

### Slice 5: Response and banner hygiene

- **Goal:** personal API responses are not cacheable, 401 is protocol-correct, and banners stop advertising versions.
- **Findings covered:** LOW-2, LOW-3.
- **Changes:** add `Cache-Control: no-store` to `/api/**` responses and `WWW-Authenticate: Bearer` to 401s; accept an incoming request id only when it matches `[A-Za-z0-9._-]{1,100}`; set `server_tokens off` in nginx and start uvicorn with `--no-server-header`.
- **Guard:** header assertions in backend tests.
- **Size:** S.
- **Risk:** middleware or clients that relied on heuristic caching now always refetch; desirable for personal data.
- **Done when:** tests pass and a local response shows the new headers.

### Slice 6: Build guard for shipped code

- **Goal:** a future change cannot ship source maps or server-only strings to the browser bundle.
- **Findings covered:** LOW-5, and supports the LEAK checks for the whole client surface (and the scan result above).
- **Changes:** add `scripts/check-client-build.mjs` (no dependencies): fails when `frontend/dist` contains `.map` files or forbidden strings (`dev-insecure-secret-change-me`, `session-secret`, `KANBAN_`, `registry.sqlite`, `board.sqlite`). Run it as part of `pnpm build`. Document `scripts/scan_build.py` from the skill as the broader optional scan.
- **Guard:** the build itself fails on a violation.
- **Size:** S.
- **Risk:** none for users; a false positive blocks a build until the allowlist changes.
- **Done when:** `pnpm build` runs the guard and a deliberately added `.map` file fails it.

### Implementation status

All six slices were implemented on 2026-10-30, with guards: backend tests cover the generated bootstrap password, hidden server paths, bulk failure shape, transfer warning, documentation authentication, metadata authentication, cache and auth headers, and request-id sanitizing. `scripts/check-client-build.mjs` runs in `pnpm build` and fails on source maps or server-only strings, which is how LOW-5 was found.

## Open questions

1. Should `/docs` be available at all in internet-facing deployments, or is `KANBAN_ENABLE_DOCS=false` the expected setting? (Product/operations decision.)
2. Should sessions be revocable server-side (logout everywhere, password change), or is the 12-hour signed-cookie lifetime accepted? (Token lifetime; not raised as a separate defect because no second user exists.)
3. Is HSTS expected to be added by the operator's TLS-terminating proxy, or should nginx send it? (Deployment decision.)
4. Is any legal protection (licence, terms) intended for board exports? (For a lawyer, not this analysis.)
