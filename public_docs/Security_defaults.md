# Security defaults

What Tralala does out of the box, what it refuses to do, and the short list of things only you can
decide. Every claim here is behaviour of this repository, not a promise about your deployment.

## Before you expose it

| Do | Why |
| --- | --- |
| Set `TRALALA_SECRET_KEY` to a long random value and keep it | It signs sessions and seals provider keys. Without it a per-install secret is generated, which is fine locally but invisible in a container that is recreated. |
| Serve over HTTPS and set `TRALALA_COOKIE_SECURE=true` | Otherwise the session cookie can travel in clear text. With the bundled Caddy, set `TRALALA_SITE_ADDRESS` to a hostname. |
| Keep `TRALALA_TRUST_PROXY_HEADERS=true` behind the bundled Caddy, `false` if the backend is directly reachable | It decides whether `X-Forwarded-For` is believed, and therefore whether the sign-in throttle sees clients or the proxy. |
| Set `TRALALA_TRUSTED_PROXIES` when another proxy sits in front of Caddy | Otherwise Caddy replaces the client address with that proxy's, and every visitor shares one sign-in throttle. See [Client addresses behind a proxy](#client-addresses-behind-a-proxy). |
| Change the administrator password | The generated password is a delivery mechanism, not a long-term credential. The bootstrap account's password change deletes `<data>/.bootstrap-password`; until then Settings reminds every administrator. |
| Keep backups of `<data>` and test one restore | A backup you never restored is a hypothesis. Restoring a snapshot restores the database **and** the uploaded files. |
| Decide about `/docs` and `/openapi.json` | They require a session by default. `TRALALA_ENABLE_DOCS=false` removes them entirely. |

## Administrator and people

- There is **no shared or published password**. The first administrator is created on first start
  with a unique generated password, written owner-only to `<data>/.bootstrap-password`. When that
  account changes its password, the file is deleted; while it exists, Settings shows administrators
  a banner, and `/meta` reports `bootstrap_password_file_present` to administrators only.
- A password configured as `admin`, `password`, `change-me`, `changeme`, `tralala-dev-1` or empty is
  treated as "no password chosen", so a generated one is used. Copying an old `.env` cannot restore a
  known password.
- `docker compose` refuses to start without an explicit `TRALALA_BOOTSTRAP_PASSWORD`, because that is
  the one place a documented default would have become a real credential.
- Passwords need at least 8 characters (`TRALALA_PASSWORD_MIN_LENGTH`, floor 8) and cannot equal the
  username. Changing your own password requires the current one and signs out every device.
- People join through an **invitation link** that the administrator shows once
  (`/enrol?token=…`, valid for `TRALALA_INVITE_TTL_HOURS`, default 72). Tralala sends no e-mail, so
  delivery is yours.
- Roles are `admin` and `member`. A member holds every scope except `users:admin` and
  `credentials:admin`, which stay with the administrator; no token of any kind can hold those or the
  `agents:*` administrative scopes.

## Sessions

- Sessions are rows in `registry.sqlite`, not bearer blobs: logout, a password change, a role change
  and disabling an account all revoke them. Expired sessions are purged at startup.
- The cookie is `HttpOnly` with `SameSite=Lax`; the CSRF token is a separate script-readable cookie
  and must be echoed in `X-CSRF-Token` on cookie-authenticated writes.
- Sign-in is throttled per username and per client address with exponential backoff. An attempt
  counts from the moment it starts, so parallel requests try no more passwords before the lock than
  the same requests one after another. Cookies are signed with a per-install secret; a session value
  from another installation is invalid.

## Client addresses behind a proxy

The sign-in throttle counts per client address, so the backend has to learn the address of the
browser rather than of a proxy. With the bundled Caddy a request passes up to two hops, and each one
decides for itself whether to believe the `X-Forwarded-For` header it receives:

1. **Into Caddy: `TRALALA_TRUSTED_PROXIES`.** A space-separated list of addresses or CIDR ranges,
   empty by default. A connection from a listed address keeps its `X-Forwarded-For` (and
   `X-Forwarded-Proto` and `X-Forwarded-Host`), and Caddy appends the address that connected. From
   any other address Caddy replaces the header with the address that connected, so empty trusts no
   one, which is right when browsers reach Caddy directly.
2. **Into the backend: `TRALALA_TRUST_PROXY_HEADERS`.** With `true` (the compose default) the
   backend takes the first address in `X-Forwarded-For`; with `false` it takes the address that
   connected, which behind Caddy is always Caddy.

| Deployment | `TRALALA_TRUSTED_PROXIES` | `TRALALA_TRUST_PROXY_HEADERS` |
| --- | --- | --- |
| Browsers reach Caddy directly (plain HTTP or Caddy's own HTTPS) | empty | `true` |
| A TLS-terminating proxy or load balancer in front of Caddy | that proxy, as Caddy sees it | `true` |
| The backend is reachable without Caddy | not used | `false` |

- List the address Caddy sees the proxy connect from, for example
  `TRALALA_TRUSTED_PROXIES=192.168.1.20` or `TRALALA_TRUSTED_PROXIES=10.0.0.0/8 192.168.0.0/16`. A
  proxy on another machine arrives with its own address. A proxy on the same machine that forwards
  to the published port usually arrives from the Docker network's gateway (such as `172.18.0.1`;
  `docker network inspect` on the project's network shows it), and a proxy container on the same
  Compose network from that network's subnet.
- Trust that proxy and nothing else: whoever reaches Caddy from a trusted address chooses the client
  address the throttle sees. When the trusted address is the Docker gateway, publish Caddy only to
  the proxy, for example `TRALALA_HTTP_PORT=127.0.0.1:8080` for a proxy on the same machine.
- The proxy in front must set `X-Forwarded-For` to the address it sees instead of appending to a
  value the client sent, because the backend believes the first address in the list.

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
  per run, and every key belongs to the account that issued it.

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
  redirects, and never a cloud metadata, link-local, multicast, unspecified or reserved address.
  A host name is resolved and every address it returns is judged like a literal address; one
  refused address refuses the endpoint. Private and loopback addresses (`127.0.0.1` and `::1`
  alike) are allowed on purpose (`TRALALA_AGENTS_ALLOW_PRIVATE_ENDPOINTS`, default `true`) because a
  self-hosted install points at a model on its own network; with `false`, only globally routable
  addresses are accepted.
- The same rule is applied again on every provider call, at the moment of connecting: the host
  name is resolved, every address is checked, and the connection is made to a checked address
  only. The `Host` header and the TLS name stay the host name, so certificates are verified as
  usual. A name that resolves differently after it was saved (DNS rebinding), or an A2A agent card
  that names another endpoint, cannot reach a refused address; the call fails with
  `ForbiddenAddressError` and the backend logs `endpoint_address_refused`. Provider calls connect
  directly: `HTTP_PROXY`/`HTTPS_PROXY` do not apply to them, because through a proxy the proxy would
  choose the address.

## Repository code

- **Nothing from a repository is ever executed.** A GitHub repository is read as an archive through
  the API. A *Git over HTTPS* repository is read from a bare, shallow mirror that `git` maintains
  with six commands only (`ls-remote`, `clone`, `fetch`, `archive`, `reflog expire` and `gc`), a
  fixed argument list and no shell; hooks, the file-system monitor and every protocol but HTTPS are
  switched off, and the system's and the account's Git configuration are ignored. Nothing is checked
  out. The files reach a prompt as text, and the prompts call them material to analyse, never
  instructions.
- A mirror fetches only over HTTPS from the hosts in `TRALALA_REPOSITORY_HOSTS` (default
  `github.com`), checked when a repository is added and before every fetch; a URL with credentials
  in it is refused. The sealed token travels in the environment of the one `git` process that needs
  it: never in a URL, a command line, a log line, the mirror's configuration or a run.
- A mirror is bounded by `TRALALA_REPOSITORY_MIRROR_MAX_BYTES` and
  `TRALALA_REPOSITORY_FETCH_TIMEOUT_SECONDS`, is a cache that backups leave out, and is removed with
  its repository or its last board link. [Repositories.md](Repositories.md) has the details.

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
  and deleted as one unit.
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
  treated as content rather than a credential. Accepted on purpose: a member who cannot see the
  shape of a role cannot tune one.
- **Discussion budgets are per run, not per token.** There is no per-token rate limit, because the
  deployment is a private network with known agents. A run is capped at four rounds and by
  `TRALALA_DISCUSSION_TOKEN_BUDGET` and `TRALALA_DISCUSSION_TIME_BUDGET_SECONDS`.
- **The board counters are cached in the registry.** They are measured from each board and dropped
  when that board is written to, so the dashboard does not open every board file. The numbers can be
  at most `TRALALA_BOARD_COUNTS_CACHE_SECONDS` stale if a board file is changed behind the app's
  back. Nothing leaks; it is a cost trade-off, not a permission.
