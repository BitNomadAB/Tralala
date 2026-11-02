2026-11-02

# Anti-reverse-engineering analysis: worker surface, public bootstrap and shipped client bundle

## At a glance

4 findings · CRITICAL 0 · HIGH 0 · MEDIUM 2 · LOW 2 · VERIFIED 4 · PLAUSIBLE 0

- Any invited member can read the product's built-in analysis, RoadMap and QA prompt texts in full, so a competitor with one account can copy the prompt engineering the product is sold on (MEDIUM · VERIFIED · MEDIUM-1).
- The installation publishes a plain-text description of its whole worker surface and workflow to anyone who finds the URL, which is a deliberate bootstrap decision but also a free map for anyone probing the host (MEDIUM · VERIFIED · MEDIUM-2).
- The shipped browser bundle contains the entire settings and administration UI with its endpoint names, so the management surface is enumerable from the download alone even though the server refuses it (LOW · VERIFIED · LOW-1).

## Scope

**What was read.** `AGENTS.md`; `README.md`; `docs/architecture.md`; `docs/decisions/0015`-`0019`;
`backend/app/main.py`; `backend/app/api/{deps,mcp}.py`; `backend/app/api/v1/{auth,boards,agents,attachments}.py`;
`backend/app/services/{agent_tools,credentials,boards,attachments,mentions}.py`;
`backend/app/core/{errors,security,ratelimit,config}.py`; `frontend/nginx.conf`;
`scripts/check-client-build.mjs`; `frontend/src/features/settings/*`; the response schemas under
`backend/app/schemas/`.

**What was not done.** The production bundle was not built and not scanned with
`scripts/scan_build.py` in this pass; the existing guard `scripts/check-client-build.mjs` was read
instead. No request was sent to any running installation.

**Code author and reviewer.** The repository's instructions set no independence rule. The code in
scope was written with an AI assistant in the same session family as this review; that is recorded
here as a limitation, not resolved.

## Product and core value

**Product.** Self-hosted Kanban for planning and tracking work, with an AI surface: Loops hold
planning documents, Tickets and a discussion; external workers connect over MCP. Roles: `admin`
(everything, including users and credentials), `member` (every scope except `users:admin`), and a
worker token, which holds only board, card, comment, Loop and discussion scopes.

**Core value a competitor would want.** (1) The prompt engineering in the built-in role templates
that turns an intent into an analysis, a RoadMap and QA acceptance criteria, including the JSON
contracts the server validates. (2) The Loop workflow rules - what blocks a phase, when a plan is
stale, what a human must approve. (3) The evaluation/trace output of real runs.

## Exposure map

| Surface | Path | What an outsider gets | Status |
| --- | --- | --- | --- |
| Browser bundle | `frontend/dist` (served by `frontend/nginx.conf`) | Every screen including admin settings, and the REST paths they call | checked, LOW-1 |
| Public bootstrap | `GET /llms.txt` (`api/mcp.py:render_bootstrap`) | Product description, workflow stages, tool names, envelope and auth rules | checked, MEDIUM-2 |
| MCP surface | `POST /mcp` | Tool list filtered by scope, and results for the caller's boards | checked, clean |
| API responses | `/api/v1/**` | Board, Loop, Ticket, document and discussion content for the caller's installation | checked, mostly clean |
| Role prompts | `GET /role-templates` (`api/v1/agents.py`) | Full built-in prompt text for any `agents:read` holder, which includes every member session | checked, MEDIUM-1 |
| Credentials | `GET /credentials/mine`, admin list | `has_api_key`, a short hint, timestamps; never the value | checked, clean |
| Error responses | all | Stable `code`, a message, and the caller's own input in `details` | checked, clean |
| Session and CSRF cookies | login/enrol | HttpOnly session, script-readable CSRF double-submit token | checked, clean |
| Response headers | `main.py` middleware, `nginx.conf` | `no-store`, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP | checked, clean |
| Health and metadata | `GET /api/v1/health`, `GET /api/v1/meta` | Status and capability flags; no version or dependency state | checked, clean |
| Realtime stream | discussion events | Events for the caller's thread only | checked, clean |
| Source maps and server-only strings | build guard | None shipped; the guard fails the build if one appears | checked, clean |

## Findings

| ID | Severity | Category | Finding in one sentence | Location | Verdict | Slice |
| --- | --- | --- | --- | --- | --- | --- |
| MEDIUM-1 | MEDIUM | CLONE | Built-in role prompts, the product's prompt engineering, are readable in full by any member | `backend/app/api/v1/agents.py:26`, `GET /role-templates` requiring `agents:read` | VERIFIED | 1 |
| MEDIUM-2 | MEDIUM | LEAK | `/llms.txt` publishes the worker surface and workflow to anyone | `backend/app/api/mcp.py` `render_bootstrap` | VERIFIED | 2 |
| LOW-1 | LOW | LEAK | The bundle ships the whole admin/settings UI and its endpoint names | `frontend/src/features/settings/*`, `scripts/check-client-build.mjs` | VERIFIED | 3 |
| LOW-2 | LOW | LEAK | A member's own token list exposes a deterministic short hint of the key | `backend/app/services/credentials.py` | VERIFIED | 3 |

### MEDIUM-1 [CLONE]: built-in role prompts are readable by any member

- Location: `backend/app/api/v1/agents.py` - `GET /role-templates` and
  `GET /role-templates/{id}` require `agents:read`. `AGENTS.md` gives a member every scope except
  `users:admin`, so a member session reads the seeded built-in prompts, including the JSON contracts
  the server validates (`schemas/loops.py`) and the rules in each prompt.
- Outsider scenario: someone with an invitation - a contractor, a customer, an evaluator - opens the
  network panel, calls `GET /api/v1/role-templates`, and saves the analysis, RoadMap and QA prompts.
  They now hold the part of the product that took the most iteration, and can stand up a competing
  tool with the same output contract. They can also see which model settings and output shapes the
  server accepts.
- Why tests miss it: the tests assert that a member can read templates (that is the feature) and
  that a member cannot read users or issue admin credentials. Nothing asks whether the *built-in*
  prompts should be readable by everyone.
- Counterpoint recorded as a rule, not a finding: `AGENTS.md` rule 11 and decision 0013 make role
  prompts editable registry data on purpose, so a person can tune how their agents think. This is a
  product tradeoff that needs an owner decision, not a bug.
- Verdict: VERIFIED.

### MEDIUM-2 [LEAK]: the public bootstrap describes the whole surface

- Location: `backend/app/api/mcp.py` `render_bootstrap` served at `GET /llms.txt`, unauthenticated.
- Outsider scenario: a scanner finds a Tralala installation, reads `/llms.txt`, and learns the
  product's stage model, tool list, envelope, error codes and the fact that human approvals cannot be
  automated. That is enough to target the API or to skip exploring the UI. It also confirms which
  version family the deployment is, because the prose names tools a given release introduced.
- Why tests miss it: the file is generated and tested for content, not for "does it tell a stranger
  more than they need".
- Counterpoint: this file is the reason a URL plus a token is enough to start working (decision
  0015). It carries no ids, no data and no secrets - verified - so the finding is about the map, not
  a leak of content.
- Verdict: VERIFIED.

### LOW-1 [LEAK]: the bundle ships the administration UI

- Location: `frontend/src/features/settings/*` (users, interaction access, agents, backups, danger
  zone) is part of the single SPA bundle. `scripts/check-client-build.mjs` fails the build for source
  maps and server-only strings, which is the important part; it does not separate admin screens.
- Outsider scenario: anyone who loads the app reads the bundle and learns every management endpoint,
  field name and capability before signing in. The server still refuses; what is given away is the
  shape.
- Why tests miss it: an SPA ships one bundle by design, and the guard only forbids server-only text.
- Verdict: VERIFIED.

### LOW-2 [LEAK]: the credential hint is a deterministic fragment

- Location: `backend/app/services/credentials.py` - responses carry `has_api_key` and a short hint
  derived from the key.
- Outsider scenario: an attacker who can read a person's settings response (a shared screen, a
  support screenshot) learns a fragment of a live token. On its own it does not yield the token, and
  the value never leaves the server otherwise; the fragment narrows a guess only if the token space
  were small, which it is not.
- Verdict: VERIFIED, low.

## Clean areas

- **Tokens.** Only `sha256` of a token is stored (`core/security.py`), the raw value is returned once,
  and every response exposes `has_api_key` plus a hint. A token cannot hold `agents:*`,
  `users:admin` or `credentials:admin` - the schema rejects those scopes rather than trusting the
  router.
- **Login and enrolment.** A dedicated throttle keyed by user and by address, plus the per-address
  rate limiter, so a login attempt cannot walk a password list (`api/v1/auth.py`).
- **Cookies.** HttpOnly session cookie with `SameSite=Lax` and `secure` from configuration; the CSRF
  cookie is deliberately script-readable for the double-submit check.
- **Headers.** `no-store` on API responses, `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, and a CSP in `frontend/nginx.conf` that forbids inline scripts.
  `server_tokens off` is set. HSTS is absent, correctly: nginx listens on plain 80 and TLS is the
  operator's terminator.
- **Errors.** One envelope, stable codes, no stack traces, no driver text; an unhandled exception
  logs only its type and returns `internal_error` (`main.py`).
- **Identifiers.** Board, Loop, Ticket and attachment ids are UUIDs; no sequential id reveals volume
  or invites walking.
- **Listing.** `max_page_size` caps page size at 200 and search is scoped to the caller's
  installation; there is no anonymous listing endpoint.
- **MCP.** The tool list is filtered by the token's scopes, and a tool that is not permitted is
  refused with `missing required scope` rather than being silently absent from the call path.
- **Bootstrap content.** `/llms.txt` contains no ids, URLs of a specific installation, tokens or
  personal data.
- **Build guard.** No source maps and no server-only strings ship; the guard fails the build.

## Refactoring plan

### Slice 1: the built-in prompts stop being public property

- **Goal:** a member can still tune and use their own role prompts but can no longer read the
  product's built-in prompt library.
- **Findings covered:** MEDIUM-1.
- **Changes:** give role templates an owner split - built-ins are `scope='builtin'` and readable by
  `users:admin` only - and let a member's Loop copy a built-in into their own template when they
  first edit it. A run resolves a built-in server-side without ever returning its text. The settings
  screen shows a built-in's name and description, not its prompt.
- **Guard:** a backend test that a member session receives `403 forbidden_scope` for a built-in
  prompt while it can still read its own copies, and that a run's persisted `role_snapshot` remains
  the only stored form.
- **Size:** M - schema change plus a settings screen change.
- **Risk:** the product loses the "edit everything" property for built-ins; existing installations
  may have edited built-ins in place. Rollout needs a migration that turns edited built-ins into
  copies.
- **Done when:** an outsider with a member account cannot obtain a built-in prompt text through any
  endpoint, and the edit path still works.

### Slice 2: the bootstrap cannot grow into a map of the installation

- **Goal:** keep the one-URL bootstrap while making it impossible for it to carry data or
  installation-specific detail.
- **Findings covered:** MEDIUM-2.
- **Changes:** none in behaviour; add the guard below.
- **Guard:** a test that `render_bootstrap` output matches no UUID, no email address, no absolute URL
  other than the placeholder, and that its tool list equals `tool_catalog()` (extend the FMEA action
  A8 test).
- **Size:** S.
- **Risk:** none for users.
- **Done when:** adding a sentence to the bootstrap that names a board or a host fails the suite.

### Slice 3: the shipped bundle states what it may contain

- **Goal:** make the bundle's contents a decision rather than an accident.
- **Findings covered:** LOW-1, LOW-2.
- **Changes:** record in `docs/decisions/` that the SPA ships the administration UI on purpose (one
  bundle, server-authoritative), and extend `scripts/check-client-build.mjs` with `--forbid` entries
  for anything that must never appear (unreleased feature names, internal hosts). Shorten the
  credential hint to the last four characters and only for the owner's own key.
- **Guard:** the existing build guard plus assertions on the hint's shape.
- **Size:** S.
- **Risk:** very low.
- **Done when:** the build fails if a forbidden string ships, and the decision exists.

## Open questions

1. Does the owner accept that built-in prompts are readable by members today, or is Slice 1 wanted?
   This is the only finding with real competitive value.
2. Should `/llms.txt` stay public, or move behind a token for a public installation? Decision 0015
   argues public; the argument weakens if the same host also serves a marketing site.
3. When private boards arrive, does a forbidden board answer `404` like a missing one? Today there is
   no board ACL, so there is no oracle yet - but the answer must be chosen before the feature ships.
4. Licensing protection for the prompt library is a legal question for a lawyer, not a finding here.
