2026-11-01

# Anti-reverse-engineering analysis: Loop planning, delivery, QA and history refactor

Code state: commit `3737a9c` ("Loops v1"); only this report is uncommitted. Code author: the same
model family as the reviewer (the refactor was written by the Copilot agent in this session).
Reviewer: Copilot agent (Claude-family model) in VS Code. The repository has no independence rule
that forbids this review, so it ran.

## At a glance

3 findings · CRITICAL 0 · HIGH 0 · MEDIUM 1 · LOW 2 · VERIFIED 3 · PLAUSIBLE 0

- An installation administrator cannot issue a token limited to Loop work from the settings page, so the only reachable alternative is to give an agent the board-administrator scope it does not need, and that token can then delete boards, read every Loop or wipe a board's data (MEDIUM · VERIFIED · MEDIUM-1).
- Whoever holds `history:read` receives the exact instructions the planning agent was given, so the product's prompt wording travels with every completed Loop (LOW · VERIFIED · LOW-1).
- Any signed-in actor, including a bearer agent token, can download the complete list of permission names the server knows, which gives a full map of the authorization model for free (LOW · VERIFIED · LOW-2).

## Scope

Read in full: `backend/app/core/context.py`, `backend/app/schemas/auth.py`,
`backend/app/schemas/loops.py`, `backend/app/main.py`, `backend/app/api/v1/auth.py`,
`backend/app/services/loops.py`, `loop_documents.py`, `loop_generation.py`, `loop_history.py`,
`runtime.py`, `backend/app/services/discussions.py`, `backend/migrations/board/versions/0008_loops.py`,
`frontend/src/lib/types.ts`, `frontend/src/features/loops/*`, `frontend/src/webmcp/useWebMcp.ts`,
`scripts/check-client-build.mjs`.

Built and scanned: the production client build (`pnpm build`, then
`scripts/scan_build.py frontend/dist` from the analysis skill) - 3 files, 653.7 KB, **0 SECRET,
0 LEAK, 4 REVIEW** (the four REVIEW hits are example endpoints such as `http://127.0.0.1:11434` in
the agent-connection form copy, which are placeholders a user reads, not addresses the build calls).

Skipped: no live system was contacted; the desktop/mobile/game/device surfaces do not exist in this
product; the discussion engine was checked only at its Loop intersection (Thread → Ticket → Loop).

## Product and core value

Self-hosted, source-available Kanban for humans and AI agents (PolyForm Noncommercial, commercial
licences sold). Users: signed-in people with role `admin` or `member` (identical working access
except account and credential administration), plus bearer **agent tokens** with an explicit scope
list. Anonymous visitors see only the sign-in page.

What a competitor would want: the Loop workflow itself (the five planning documents, the approval
and staleness rules, the readiness graph, the QA handover, the immutable history envelope) and the
prompts that drive generation. None of it is data of other tenants, because an installation is
single-tenant: every actor that reaches a board is already entitled to that board.

## Exposure map

| Surface | Path | What an outsider gets | Status |
| --- | --- | --- | --- |
| Production client build | `frontend/dist/assets/index-*.js` | The whole Loop UI, its API calls and the client-side scope list | Checked - clean, 4 REVIEW hits explained |
| Client build guard | `scripts/check-client-build.mjs` | Fails the build on source maps and server-only strings | Checked - runs in `pnpm build` |
| Loop responses | `backend/app/schemas/loops.py` (`LoopOut`, `PlanOut`, `ReadinessOut`, `QaCycleOut`) | Loop metadata, plan, readiness and QA state of boards the actor already reaches | Checked - no cross-board or cross-actor fields |
| Agent context | `GET /boards/{id}/loops/{loop_id}/context` | Documents, plan, tickets, JSON schemas; no credentials, no other Loop | Checked - clean |
| Generation runs | `backend/app/services/loop_generation.py` + `GenerationRunOut` | Status, sanitized error, output, model, agent name; input and role snapshot stripped | Checked - clean |
| History | `loop_history.py` envelope, `GET /boards/{id}/history[/{id}]` | Full Loop snapshot, including `generation_provenance` | Finding LOW-1 |
| Error responses | `backend/app/main.py` handlers | Stable code, own-input details, no message or traceback | Checked - clean |
| Credentials in the client | session cookie (HttpOnly), CSRF cookie (readable by design), agent token shown once | Cookie theft by injected script limited to the CSRF value | Checked - clean |
| Public metadata | `GET /api/v1/health`, `GET /api/v1/meta`, `/openapi.json`, `/docs` | Health has no version; meta and schemas are session-gated | Finding LOW-2 |
| Listing surfaces | `GET /boards/{id}/tickets`, search, history search, pagination | Bounded (`limit<=500`, `max_boards=25`, `limit_per_loop=10`), session required | Checked - clean |
| Scope catalogue in the settings form | `frontend/src/lib/types.ts` `SCOPES` | Drives which scopes an administrator can grant | Finding MEDIUM-1 |

## Findings

| ID | Severity | Category | Finding in one sentence | Location | Verdict | Slice |
| --- | --- | --- | --- | --- | --- | --- |
| MEDIUM-1 | MEDIUM | LOGIC | The settings page ships its own token scope list, which the refactor left stale, so least-privilege Loop tokens cannot be issued | `frontend/src/lib/types.ts:495` | VERIFIED | Slice 1 |
| LOW-1 | LOW | LEAK | The history envelope stores and returns the exact generation system prompt | `backend/app/services/loop_history.py:323` | VERIFIED | Slice 2 |
| LOW-2 | LOW | LEAK | `GET /api/v1/meta` hands the complete scope catalogue to every signed-in actor | `backend/app/main.py:218` | VERIFIED | Slice 1 |

### MEDIUM-1 [LOGIC]: the client owns a copy of the server's token scope list, and the copy is now wrong

- Location: `frontend/src/lib/types.ts:495` lists thirteen scopes for the "New token" form
  (`frontend/src/features/settings/SettingsPage.tsx:271` renders one checkbox each). The server's
  canonical list is `backend/app/core/context.py:8` (twenty names) and the accepted token subset is
  `backend/app/schemas/auth.py:9`. The client list is missing `loops:read`, `loops:write`,
  `loops:generate` and `history:read`, all of which the token schema accepts.
- Outsider scenario: an administrator wants a planning agent that may read Loops, submit analysis
  and roadmap candidates and move Tickets, and nothing else. The form offers no `loops:*` scope, so
  the least-privilege answer is impossible. The reachable alternatives are to skip agent planning
  entirely or to tick `boards:admin`, which the token then really holds: board deletion, every Loop
  of the board and the backup endpoints all accept it. A token that only needed to draft an analysis
  can therefore wipe a board's data, and the audit trail will show an administrator-typed actor for
  work an agent performed.
- Why tests miss it: the backend tests create credentials through the API, where the scope literal
  accepts the Loop scopes; the frontend tests render forms, and the e2e token journey
  (`frontend/e2e/settings.spec.ts`, "issues and revokes an agent token") ticks `cards:write` and
  asserts that row's text, so a missing scope never shows up.
- Verdict: VERIFIED (the three lists were read side by side).

### LOW-1 [LEAK]: the generation system prompt leaves with every completed Loop

- Location: `backend/app/services/loop_generation.py:251` and `:276` persist the built system
  prompt into `loop_generation_runs.role_snapshot_json`;
  `backend/app/services/loop_history.py:323` copies that JSON into the history envelope as
  `generation_provenance[].role_snapshot`, and the envelope is returned by the history detail
  endpoint. `_serialize_run` deliberately strips the same field from run responses, so the intent
  clearly was not to hand it out.
- Outsider scenario: a token issued with `history:read` - the natural read-only scope for a
  reporting agent, and the one the settings form cannot even issue today - fetches
  `GET /boards/{id}/history/{history_id}` for a finished Loop and receives the exact wording of the
  analysis, roadmap and QA instructions, including the sentence that forces a plain-language finding
  for every technical one. The workflow prompts are the cheap-to-copy part of the product: they fit
  in one screen and encode how the five documents relate, so a competitor rebuilds the same prompts
  and skips the design work.
- Why tests miss it: `backend/tests/test_loops.py` asserts that history search finds ticket keys and
  decisions; nothing asserts which fields the envelope may contain.
- Verdict: VERIFIED. Severity is LOW only because the prompts are currently short and generic; they
  grow more valuable as house rules are added, and the fix is cheap now.

### LOW-2 [LEAK]: the full permission catalogue is readable by any signed-in actor

- Location: `backend/app/main.py:218` returns `"scopes": list(SCOPES)` from `GET /api/v1/meta`; the
  route calls `get_context`, so any session or bearer token may read it. The React client never
  consumes that field - it ships its own list (MEDIUM-1) - so nothing in the product needs it.
- Outsider scenario: a member who wants to escalate, or anyone holding a deliberately narrow agent
  token, calls `/api/v1/meta` and learns every permission name the server implements, including the
  ones the UI never offers (`loops:review`, `users:admin`, `credentials:admin`) and the shape of the
  naming convention. That is a free map of the authorization model, and it invites a token to be
  probed against every name in the list instead of guessed.
- Why tests miss it: `backend/tests/test_hardening.py` covers unauthenticated access and header
  hygiene, not response minimality.
- Verdict: VERIFIED.

## Clean areas

- **Client build**: scanned 3 files / 653.7 KB - no secrets, no source maps, no server-only files, no
  internal host names beyond placeholder examples in user-facing copy; `scripts/check-client-build.mjs`
  already fails the production build for source maps and server-only strings, so this is guarded.
- **Business rules in the client**: Loop stage names, readiness, blockers, ticket keys, approval
  validity and QA decisions are all computed server-side; the UI only decides which button to show
  (`LoopHeader.tsx:292` mirrors the "current, non-stale revisions" rule, and the server rejects a
  review that does not match the exact revisions - `test_review_requires_the_exact_revisions`).
- **Human-only actions**: `require_human()` runs before the scope check and `loops:review` is not in
  the token literal, so an agent token gets `403 human_action_required` rather than a silent
  success; covered by `test_agents_cannot_approve`.
- **Error responses**: one envelope, stable codes, own-input details only; the unhandled handler logs
  the exception type and returns "An unexpected error occurred"; provider failures are reduced to
  `{type name}`, `HTTP <status>` or `malformed_response` before they reach `error_message`.
- **Generation responses**: `_serialize_run` removes `input_json`, `role_snapshot_json` and the
  creator columns, so a run response carries status, output, model, usage and a sanitized error only.
- **Agent context**: `LoopDocumentService.context` returns the Loop's documents, plan, tickets and
  JSON schemas; it holds no credentials and cannot reach another Loop.
- **Identifiers**: board, Loop, Ticket, document and run ids are UUIDs; the human-facing
  `AC004-DA02-003` key is derived from server-assigned sequences and reveals nothing an authorised
  reader does not already see.
- **Listing and scraping**: every list endpoint is session-gated and bounded (`limit<=500`, global
  search `max_boards=25`, `limit_per_loop=10`), the rate limiter covers the whole API, and login has
  a separate per-user and per-address throttle, so bulk extraction is slow and visible in the request
  log.
- **Login oracle**: unknown accounts verify against a dummy hash and return the same
  `invalid_credentials` answer, so existence and timing are not distinguished.
- **Sessions**: the session cookie is HttpOnly, `SameSite=Lax`, `Secure` when configured, and the
  CSRF value is the only deliberately script-readable cookie; logout and password change revoke
  sessions server-side.
- **Migration failure**: the board status `migration_failed` and its reset instruction go to the
  server log, not to a response, so no internal command path reaches a client.
- **Realtime**: discussion and card event streams are board- and card-scoped and close with the
  session; a subscriber never receives another board's events.

## Refactoring plan

### Slice 1: one authority for the scope catalogue

Findings: MEDIUM-1, LOW-2.

- **Goal**: an administrator can issue a token limited to Loop work from the settings page, and no
  actor receives a permission list it does not render.
- **Changes**: make `frontend/src/lib/types.ts` stop defining the grantable scopes; load them from
  the endpoint the server already has, or - if the list is to stay a build-time constant - derive it
  from the same source the token schema uses and delete the unused `scopes` field from
  `/api/v1/meta`. Routers, services and the token schema stay unchanged.
- **Guard**: a test in the normal `pnpm test` run that the client's grantable scope list equals the
  server's token `Scope` literal (asserted against a fixture the backend suite also checks), plus a
  backend test that `/api/v1/meta` returns no field the client never reads.
- **Size**: S - one constant, one optional field, two tests.
- **Risk**: low. The only consumer is the settings form, and a stale cached copy is harmless because
  the server rejects an unknown scope with `422`.
- **Done when**: the "New token" form offers `loops:read`, `loops:write`, `loops:generate` and
  `history:read`, still refuses to offer `loops:review`, and a scope added on the server later
  cannot silently disappear from the form.

### Slice 2: provenance without the prompt text

Findings: LOW-1.

- **Goal**: history proves which agent and which instructions produced a document without handing
  the instructions to a reader.
- **Changes**: keep the prompt in `loop_generation_runs.role_snapshot_json` for audit, but give the
  history envelope a reduced provenance record: run id, purpose, agent id and name, model, created
  and finished time, usage, and a stable hash of the prompt (`system_prompt_sha256`, the pattern the
  discussion participants already use). The history detail view shows the hash and the agent, not
  the text.
- **Guard**: a test that the history envelope contains no `role_snapshot`/`system_prompt` key and
  that `system_prompt_sha256` matches the stored prompt, run for a Loop whose documents were
  generated rather than submitted.
- **Size**: S - one projection in `loop_history.py`, one field in the history schema, one test.
- **Risk**: low. Existing history rows keep their stored snapshot; only the read projection changes,
  and a hash is still enough to prove which prompt was used.
- **Done when**: `GET /boards/{id}/history/{id}` returns provenance with a hash and without any
  prompt text, and the test above fails if the text returns.

## Status after this analysis

The same day, after the report was saved, the three findings were acted on in the working tree
(commit at analysis time `3737a9c`):

- MEDIUM-1 and LOW-2: `frontend/src/lib/types.ts` no longer holds a scope list. `GET /api/v1/meta`
  returns `token_scopes`, derived from the token `Scope` literal, and the Settings page renders the
  checkboxes from it, so the client can no longer disagree with the server. Guard:
  `tests/test_hardening.py::test_meta_lists_exactly_the_grantable_token_scopes` asserts the served
  list equals the literal, contains the four Loop scopes and excludes `loops:review`.
- LOW-1: the history envelope now carries `generation_provenance[].system_prompt_sha256` instead of
  the stored role snapshot. Guard:
  `tests/test_loop_generation.py::test_history_provenance_hashes_the_prompt_instead_of_copying_it`
  asserts the key set, the digest and that the prompt text is absent.

Verified after the change: backend `pytest` green, `ruff check app migrations tests` clean, frontend
`pnpm typecheck`, `pnpm test` (22) and `pnpm build` green, `pnpm test:e2e` 26/26.

## Open questions

- Should `loops:review` ever be grantable to a token for a headless human-in-the-loop deployment, or
  is "approval always needs a person" absolute? The refactor chose absolute; the answer decides
  whether the scope stays out of every list.
- The README still says the product has no external AI provider while Loop generation calls the
  configured agents' endpoints - is that wording a lawyer's question rather than a code one?
- Who owns the prompt wording if it becomes a selling point: should the prompts move into the same
  registry-editable role template mechanism the agents already use, so an edit is a documented
  product decision rather than a code change?
