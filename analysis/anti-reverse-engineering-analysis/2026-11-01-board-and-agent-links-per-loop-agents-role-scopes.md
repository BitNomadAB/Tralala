2026-11-01

# Anti-reverse-engineering analysis: board/repository links, per-Loop agents, role scopes

## At a glance

2 findings · CRITICAL 0 · HIGH 0 · MEDIUM 1 · LOW 1 · VERIFIED 2 · PLAUSIBLE 0

- Every agent token that can read boards can also list every repository the installation knows, including which other boards share it and a hint of its access token, which maps the organisation's code inventory for whoever holds such a token (MEDIUM · VERIFIED · MEDIUM-1).
- A token that may read Loops sees which agent a Loop prefers, which is correlation data about the installation's staff rather than a secret (LOW · VERIFIED · LOW-1).

## Scope

Delta review of every surface added or changed since the 2026-11-01 analysis of the Loop refactor:
registry revisions `0007`-`0011`, board revision `0009` (Loop agent preferences), `/repositories` and
`/boards/{id}/loops/{id}/agents`, `agent_ids` on boards, `agent_scope_organisation`, the role seed
file, and the frontend components `AgentPicker`, `LoopAgentsDialog`, `RepositoryTokenGuide`,
`BoardContext`. Read: the services, routers and schemas of those surfaces, and the frontend
components. Ran: the local dev instance on `127.0.0.1` with a purpose-issued agent token (no external
system was contacted), `pytest`, `ruff` and `pnpm build`. Not inspected: a client bundle from a
release pipeline (only the local production build, guarded by the repository's `client-build-guard`).

## Product and core value

Self-hosted kanban for AI-assisted delivery. Roles: administrator, member, agent (API token), and two
organisation-wide agent profiles. What a competitor would want: the role prompts (the product's
opinionated know-how), the Loop workflow rules, and the inventory of a customer's repositories.

## Exposure map

| Surface | Path | What an outsider gets | Status |
| --- | --- | --- | --- |
| Client bundle | `frontend/src/features/{boards,loops,settings}` | UI code; repository URLs and agent names that the API already returns | Clean |
| Responses | `GET /api/v1/repositories` | Full repository list, board links, `has_token`, four-character token hint, last check detail | Finding MEDIUM-1 |
| Responses | `GET/PUT /api/v1/boards/{id}/loops/{id}/agents` | Agent UUIDs per purpose | Finding LOW-1 |
| Responses | `GET /api/v1/role-templates` | Role prompts and descriptors | Clean (not grantable to tokens) |
| Responses | `GET /api/v1/agents/directory` | Agent identity and role | Clean (not grantable to tokens) |
| Errors | `agent_scope_organisation`, `agent_not_on_board`, `agent_not_found` | Whether an agent id exists and is an organisation profile | Clean |
| Credentials | sealed tokens, `token_hint` | A hint only, never the token | Clean (invariant 12) |
| Public metadata | `backend/app/seeds/role_seeds.json` | Role prompts in the source tree | Clean (source-available by decision) |

## Findings

| ID | Severity | Category | Finding in one sentence | Location | Verdict | Slice |
| --- | --- | --- | --- | --- | --- | --- |
| MEDIUM-1 | MEDIUM | LEAK | Any token with `boards:read` lists every registered repository with its board links, token hint and health detail | `backend/app/api/v1/repositories.py` | VERIFIED | 1 |
| LOW-1 | LOW | LEAK | A token with `loops:read` learns which agent each Loop prefers | `backend/app/api/v1/loops.py` | VERIFIED | 2 |

### MEDIUM-1 [LEAK]: the repository inventory is served to every board reader

- Location: `backend/app/api/v1/repositories.py` (`GET /repositories`, scope `boards:read`) and
  `app/services/repositories.py::serialize`, which returns `token_hint`, `last_check_*` and `boards`.
- Outsider scenario: a token issued for one narrow job calls `GET /api/v1/repositories` and receives
  every GitHub URL the installation is configured with, the boards each one serves, a four-character
  hint of each access token and the outcome of the last access check. It cannot read the token, but it
  now knows the organisation's code inventory and how the installation is wired. Observed locally with
  a token holding only `boards:read` and `loops:read`.
- Why tests miss it: every API test authenticates as an administrator; no test fixes the field set a
  narrower token receives.
- Verdict: VERIFIED.

### LOW-1 [LEAK]: a Loop's agent preference is readable by every Loops reader

- Location: `backend/app/api/v1/loops.py` (`GET …/loops/{loop_id}/agents`, scope `loops:read`).
- Outsider scenario: a token that can read Loops learns which agent UUID is preferred for analysis,
  RoadMap and QA on each Loop. Nothing secret is exposed (no names, no connection details, no
  credentials), but it is correlation data an outsider does not need.
- Why tests miss it: the endpoint is tested for behaviour, not for a minimal field set.
- Verdict: VERIFIED (low impact: agent ids only, and agent tokens are installation-wide anyway).

## Clean areas

- Role prompts cannot be read by an agent token: `agents:read` is not in the grantable scope list, so
  `GET /role-templates` answers `403` to a token (verified locally). Prompts reach human sessions only.
- The seed file ships in the source tree, which the licence already makes readable, and holds no
  credentials or customer data.
- `POST /repositories/{id}/check` never echoes the GitHub response body: details are the service's own
  strings plus the owner/name from the stored record.
- `PUT …/loops/{loop_id}/agents` requires `boards:write`, so a board-readable agent token is refused.
- The client bundle carries no source maps and no server-only strings; `client-build-guard` passed on
  the production build.
- `RepositoryTokenGuide` is instructions only: no example repository, no secret, no internal host.
- Registry revisions `0007`-`0011` and board revision `0009` contain no default secrets and no
  customer identifiers.

## Refactoring plan

### Slice 1: a repository list that fits the caller (MEDIUM-1)

- Goal: a caller without repository administration sees the repositories it may need, without token
  hints, access-check outcomes or the installation's wiring.
- Findings covered: MEDIUM-1.
- Changes: `RepositoryService.serialize` takes the caller's scopes; without `boards:admin` the entry
  carries `id`, `name`, `provider`, `url`, `branch`, `enabled` and `boards` (id and name), and omits
  `token_hint`, `last_checked_at`, `last_check_status` and `last_check_detail`. The router passes the
  actor, and the admin page keeps its current view.
- Guard: a test that issues a `boards:read` token and pins the exact key set, next to the existing
  administrator test that the hint is present.
- Size: S.
- Risk: an agent that reads health detail from the list loses it; nothing in this repository does, and
  the check endpoint stays admin-only.
- Done when: the key set differs by scope as described and both tests pass.

### Slice 2: a Loop's agent choice (LOW-1)

- Goal: the preference stops being enumerable by every Loops reader, without breaking the dialog that
  labels its default.
- Findings covered: LOW-1.
- Changes: keep the read path for `loops:read` (the generation dialog needs it) and state in
  `docs/` that a Loop's chosen agents are visible inside the installation; if tightening is wanted,
  move the read to `boards:read` in the next hardening round.
- Guard: a test pinning the current shape until that decision.
- Size: S.
- Risk: any tightening must keep the read path working for whoever may generate.
- Done when: the decision is recorded and the pinned test passes.

## Open questions

- Should an agent token see repositories that are not linked to the board it works on? Today no token
  is board-scoped, so the answer changes only when per-board actor access exists.
- Is the four-character token hint acceptable in handover screenshots? Invariant 12 allows the hint;
  the session screenshots of this repository show one.

## Status after this analysis

The findings this round could close cheaply are closed; the rest are recorded as work.

- **MEDIUM-1 closed:** `GET /repositories` and `GET /repositories/{id}` now hide `token_hint`,
  `last_checked_at`, `last_check_status` and `last_check_detail` from a caller without `boards:admin`
  (`services/repositories.py::serialize(with_health=?)`, router helper `_sees_health`), and
  `test_a_board_reader_gets_no_credential_hint_or_check_history` pins the exact key set.
- **LOW-1 accepted:** a Loop's agent preference stays readable with `loops:read`, because the
  generation dialog needs it and agent tokens are installation-wide; the decision is recorded in
  `docs/decisions/0012` rather than tightened.
