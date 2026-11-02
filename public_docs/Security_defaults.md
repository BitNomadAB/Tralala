# Security defaults

What Tralala does out of the box, what it refuses to do, and the short list of things only you can
decide. Every claim here is behaviour of this repository, not a promise about your deployment.

## Before you expose it

| Do | Why |
| --- | --- |
| Set `TRALALA_SECRET_KEY` to a long random value and keep it | It signs sessions and seals provider keys. Without it a per-install secret is generated, which is fine locally but invisible in a container that is recreated. |
| Serve over HTTPS and set `TRALALA_COOKIE_SECURE=true` | Otherwise the session cookie can travel in clear text. With the bundled Caddy, set `TRALALA_SITE_ADDRESS` to a hostname. |
| Keep `TRALALA_TRUST_PROXY_HEADERS=true` behind the bundled Caddy, `false` if the backend is directly reachable | It decides whether `X-Forwarded-For` is believed, and therefore whether the sign-in throttle sees clients or the proxy. |
| Change the administrator password, then delete `<data>/.bootstrap-password` | The generated password is a delivery mechanism, not a long-term credential. |
| Keep backups of `<data>` and test one restore | A backup you never restored is a hypothesis. Restoring a snapshot restores the database **and** the uploaded files. |
| Decide about `/docs` and `/openapi.json` | They require a session by default. `TRALALA_ENABLE_DOCS=false` removes them entirely. |

## Administrator and people

- There is **no shared or published password**. The first administrator is created on first start
  with a unique generated password, written owner-only to `<data>/.bootstrap-password`.
- A password configured as `admin`, `password`, `change-me`, `changeme`, `tralala-dev-1` or empty is
  treated as "no password chosen", so a generated one is used. Copying an old `.env` cannot restore a
  known password.
- `docker compose` refuses to start without an explicit `TRALALA_BOOTSTRAP_PASSWORD`, because that is
  the one place a documented default would have become a real credential.
- Passwords need at least 8 characters (`TRALALA_PASSWORD_MIN_LENGTH`, floor 8) and cannot equal the
  username. Changing your own password requires the current one and signs out every device.
- People join through an **invitation link** that the administrator shows once
  (`/enrol?token=…`, valid for `TRALALA_INVITE_TTL_HOURS`, default 72). Tralala sends no e-mail, so
  delivery is yours. See [decisions/0014](../docs/decisions/0014-enrolment-links-instead-of-email-verification.md).
- Roles are `admin` and `member`. A member holds every scope except `users:admin` and
  `credentials:admin`, which stay with the administrator; no token of any kind can hold those or the
  `agents:*` administrative scopes.

## Sessions

- Sessions are rows in `registry.sqlite`, not bearer blobs: logout, a password change, a role change
  and disabling an account all revoke them. Expired sessions are purged at startup.
- The cookie is `HttpOnly` with `SameSite=Lax`; the CSRF token is a separate script-readable cookie
  and must be echoed in `X-CSRF-Token` on cookie-authenticated writes.
- Sign-in is throttled per username and per client address with exponential backoff. Cookies are
  signed with a per-install secret; a session value from another installation is invalid.

## Agent access keys

- A person issues keys for their own machine under **Settings → New access key**. The value is shown
  once; only its SHA-256 is stored, and responses carry `has_api_key`, a short hint and `last_used_at`.
- A personal key expires after `TRALALA_MEMBER_TOKEN_DEFAULT_DAYS` (default 30), cannot exceed
  `TRALALA_MEMBER_TOKEN_MAX_DAYS` (default 365), and a person may hold
  `TRALALA_MEMBER_TOKEN_LIMIT` live keys (default 10). Disabling the account revokes the keys it
  issued. An administrator may issue a wider token (`TRALALA_CREDENTIAL_DEFAULT_TTL_DAYS`, default
  90; `0` for none).
- Scopes are enforced server-side on every request. A tool that needs more than the token holds is
  refused, and `/mcp` hides it from `tools/list` rather than advertising a call that would fail.
- A key is identity: it is not bound to a device and there is no per-token rate limit. The intended
  deployment is a local machine or an internal network with approved models, not the open internet.
  Cost is bounded per discussion instead: at most four rounds, with a default token and time budget
  per run. See [decisions/0017](../docs/decisions/0017-interaction-agent-access-ownership.md).

## What no token can do

Approving an analysis or a RoadMap, confirming a human-only Ticket, accepting QA, finalizing a Loop,
changing a board's structure, and managing users or credentials are human decisions. They reject
tokens with `403 human_action_required` regardless of scope, and they are not registered as worker
tools. Approvals bind to exact document revision ids, so a changed input invalidates them.

## Secrets and provider credentials

- Provider API keys are encrypted with a key derived from the session secret and never echoed; the
  API returns `has_api_key` and a hint. Repository tokens are sealed the same way.
- After rotating `TRALALA_SECRET_KEY`, set `TRALALA_PREVIOUS_SECRET_KEY` for one start: stored
  credentials are re-sealed with the new secret, then the old value can be removed.
- Agent endpoints are validated when saved: `http`/`https` only, no embedded credentials, no
  redirects, and never link-local, multicast or reserved addresses. Private and loopback addresses
  are allowed on purpose (`TRALALA_AGENTS_ALLOW_PRIVATE_ENDPOINTS`, default `true`) because a
  self-hosted install points at a model on its own network. See
  [decisions/0018](../docs/decisions/0018-a2a-execution.md).

## Requests, responses and errors

- Every request body is bounded (`TRALALA_MAX_REQUEST_BYTES`, default 8 MiB). The bound is counted
  while bytes arrive, so a chunked body without a `Content-Length` header is refused too. The bundled
  Caddy sits one step above it (`request_body max_size 9MB`) so the backend's JSON envelope is what a
  client normally sees.
- Requests are rate limited per actor (`TRALALA_RATE_LIMIT_PER_MINUTE`, default 600). It is a runaway
  guard, not a defence.
- Authentication is resolved before a request body is parsed, including on `/mcp`.
- Errors are one envelope with a stable `code`, never a stack trace, driver message or server path.
  An unhandled exception logs its type and returns `internal_error`.
- API responses carry `Cache-Control: no-store`, `nosniff`, `X-Frame-Options: DENY` and
  `Referrer-Policy: no-referrer`; the web tier adds a CSP that forbids inline scripts. Neither tier
  advertises its product or version.
- An unknown request field is rejected (`422`), so a typo cannot silently change behaviour.

## Data and history

- A board is its directory: the database and the uploaded files, moved, copied, backed up, exported
  and deleted as one unit ([decisions/0019](../docs/decisions/0019-board-files-travel-with-the-database.md)).
- A completed Loop is read-only: finalization writes an immutable, hashed snapshot to `loop_history`
  in the same transaction and blocks every later mutation path.
- Uploaded files are allowlisted by extension and content signature, capped per file and per board,
  and stored under a generated name; the original filename is metadata only.
- Every active board is snapshotted every `TRALALA_BACKUP_INTERVAL_HOURS` (default 24, `0` disables)
  and only the newest `TRALALA_BACKUP_KEEP` (default 10) are kept. Files that do not match the
  snapshot pattern are never pruned.
- The production bundle is checked for source maps and server-only strings by
  `frontend/scripts/check-client-build.mjs` as part of `pnpm build`.

## Known limits of these defaults

- One backend process per data directory. The rate limiter, the board locks and the session secret are
  process-local, so horizontal scaling needs a shared coordination store first.
- There is no per-board access control yet: a member sees every board in the installation. Private
  boards are a separate feature, not a setting.
- Accounts are administrator-provisioned; there is no self-registration.
- The ban on tokens for human decisions is enforced in the services and the tool catalogue. A future
  endpoint that forgets it would be a defect, which is why the guarantees live in one layer.

Report a security issue to <tralala@bitnomad.se> rather than in a public issue.

## Accepted risks, on purpose

These are known and deliberately left as they are. Read them before you decide your own posture.

- **Members can read built-in role prompts.** Anyone who may read agents can see the role text a
  board profile was created from. It is guidance for an external agent, not a secret rule, so it is
  treated as content rather than a credential. Left open in the anti-reverse-engineering analysis
  (`analysis/anti-reverse-engineering-analysis/`, finding MEDIUM-1) and in the decision log.
- **Discussion budgets are per run, not per token.** There is no per-token rate limit, because the
  deployment is a private network with known agents. A run is capped at four rounds and by
  `TRALALA_DISCUSSION_TOKEN_BUDGET` and `TRALALA_DISCUSSION_TIME_BUDGET_SECONDS`.
- **An agent endpoint is checked when it is saved, not on every call.** A hostname that passed
  validation could later resolve to a link-local address. Re-resolving before each provider call is
  only worth doing where a metadata service is reachable, such as a cloud instance; Tralala is built
  for a private network or a private Tailscale, so it was declined (FMEA action A6). Do not run it on
  a cloud host without adding that check.
- **The board counters are cached in the registry.** They are measured from each board and dropped
  when that board is written to, so the dashboard does not open every board file. The numbers can be
  at most `TRALALA_BOARD_COUNTS_CACHE_SECONDS` stale if a board file is changed behind the app's
  back. Nothing leaks; it is a cost trade-off, not a permission.
