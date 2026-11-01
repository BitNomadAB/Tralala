2026-10-30

# Anti-reverse-engineering analysis: mentions, discussions and client build

Code state: `f4bf9fb` (working tree clean at analysis start). Code author: Copilot (same model
family as this review; the repository has no independence rule, so the author wrote and reviewed
under the repository rules). Reviewer: Copilot agent in VS Code.

Scope: the surfaces added or changed by KAN-082 (mentions in ticket comments), KAN-090 (board-first
Discussions) and KAN-091 (automatic rounds), plus the production client build. Earlier, wider
findings are in `analysis/anti-reverse-engineering-analysis/2026-10-30-self-hosted-web-client-and-rest-api.md`.

## At a glance

3 findings · CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 3 · VERIFIED 3 · PLAUSIBLE 0

- A token that is allowed to read discussions and nothing else can list every board's name,
  status and discussion volume through the new overview endpoint (LOW · VERIFIED · LOW-1).
- Opening a card downloads the full configuration of every enabled agent, including endpoint,
  model and credential hint, although the mention autocomplete only needs a name and a role
  (LOW · VERIFIED · LOW-2).
- Failed mention events store and stream another copy of the user's comment text, which the client
  already has, and keep it in an event log with no retention (LOW · VERIFIED · LOW-3).

## Scope

Read: `AGENTS.md`, `docs/architecture.md`, `docs/api.md`, `docs/database.md`,
`backend/app/api/v1/{discussions,cards,boards,agents,streaming}.py`,
`backend/app/services/{mentions,events,discussions,agents,subresources}.py`,
`backend/app/schemas/{subresources,discussions,agents}.py`,
`frontend/src/features/{cards/CardDialog.tsx,cards/useCardEvents.ts,discussions/DiscussionsPage.tsx}`,
`frontend/src/lib/{api.ts,providers.ts,mentions.ts}`, and the existing client build guard.

Ran: `pnpm run build` (guard passed) and
`python scripts/scan_build.py frontend/dist` → 0 SECRET, 0 LEAK, 4 REVIEW (all local provider
preset URLs, see Clean areas). No production or shared environment was contacted.

Skipped: native clients and delivered devices (none exist); WebMCP tool registration was checked
only for the new pages.

## Product and core value

A self-hosted, single-organization Kanban where humans and AI agents discuss tickets. Roles: user
session (admin/all scopes), API tokens with explicit scopes, and AI agents acting through tokens.
Core value a competitor could want: the role prompts, the orchestration and consensus rules, and
the ticket history. All of it lives on the server behind one REST API.

## Exposure map

| Surface | Path | What an outsider gets | Status |
| --- | --- | --- | --- |
| Web client bundle | `frontend/dist` | Routes, UI text, provider presets, request field names | Checked, clean |
| Discussion overview | `api/v1/discussions.py` `/discussions/overview` | Board names, status, discussion counts, last activity | Finding LOW-1 |
| Ticket event stream | `api/v1/cards.py` `.../events` | `agent_started/completed/failed` payloads including answer text and, on failure, the source comment | Finding LOW-3 |
| Mention job list/retry | `api/v1/cards.py` `.../mentions` | Job status, agent name/role, provider error string | Checked, clean |
| Agent list for autocomplete | `api/v1/agents.py` `/agents?enabled=true` | Full agent configuration and credential hint | Finding LOW-2 |
| Discussion message + auto-run | `api/v1/discussions.py` `.../messages` | Human message, run row, agent answers | Checked, clean |
| Error responses | all new endpoints | Stable codes and caller-owned ids | Checked, clean |
| Client storage | cookies | `HttpOnly` session cookie + CSRF cookie; no tokens in storage | Checked, clean |
| SSE authentication | both stream endpoints | Scope check before streaming; replay limited to one scope id | Checked, clean |

## Findings

| ID | Severity | Category | Finding in one sentence | Location | Verdict | Slice |
| --- | --- | --- | --- | --- | --- | --- |
| LOW-1 | LOW | ORACLE / LEAK | The overview endpoint discloses every board's name, status and discussion volume with only `discussions:read`, bypassing the `boards:read` gate that `/boards` uses. | `backend/app/api/v1/discussions.py:27-34` | VERIFIED | 1 |
| LOW-2 | LOW | LEAK | The card dialog downloads full agent records (base URL, model, timeout, credential hint, last test message) to build a name/role autocomplete. | `frontend/src/features/cards/CardDialog.tsx:59-62`, `backend/app/services/agents.py:243-255` | VERIFIED | 2 |
| LOW-3 | LOW | LEAK | Failed and completed mention events persist and stream `mentioned_content` and the full answer text in addition to the comment id, duplicating data the client can fetch. | `backend/app/services/mentions.py:436-490,371-435` | VERIFIED | 3 |

### LOW-1 [ORACLE / LEAK]: discussion overview reveals board metadata behind another scope

- Location: `backend/app/api/v1/discussions.py:27-34` uses `ctx.actor.require("discussions:read")`;
  `BoardService.list` (`api/v1/boards.py:16-28`) requires `boards:read`. The overview returns
  `board_name`, `status`, `discussion_count`, `open_count` and `last_activity_at` for every board
  in the registry.
- Outsider scenario: an actor holding `discussions:read` but not `boards:read` calls
  `GET /api/v1/discussions/overview` and learns the full board inventory, which boards are archived
  or failing, and how much discussion activity each has. The same actor cannot call
  `GET /api/v1/boards`. Repeated calls reveal growth over time, a business volume metric.
- Today the scenario is theoretical for API tokens: `Scope` in `backend/app/schemas/auth.py:9-11`
  does not allow `discussions:read` on a credential, so only a full user session (which holds every
  scope) reaches the endpoint. The check is still inconsistent with `/boards` and becomes an
  exposure the moment discussion scopes are granted to tokens.
- Why tests miss it: tests used the all-scope user session; no test exercised a narrow token on the
  new endpoint.
- Verdict: VERIFIED.

### LOW-2 [LEAK]: card dialog downloads full agent configuration

- Location: `frontend/src/features/cards/CardDialog.tsx:59-62` queries `api.listAgents({enabled:true})`;
  `AgentService.serialize` (`services/agents.py:243-255`) returns the whole row minus the sealed key,
  including `base_url`, `model`, `timeout_seconds`, `api_key_hint`, `last_test_message` and
  `last_tested_at`. The dialog uses only `name` and `role_template_name`.
- Outsider scenario: any script that runs on the page (injected or a malicious extension) can read
  every agent's provider endpoint and credential hint from the query cache while a card is open.
  The secret itself never leaves the server, so the value is configuration knowledge, not a token.
- Why tests miss it: no response-shape test for the autocomplete surface; the Settings page
  legitimately needs these fields, so the same endpoint serves both.
- Verdict: VERIFIED.

### LOW-3 [LEAK]: event payloads duplicate comment content

- Location: `backend/app/services/mentions.py` stores `content` on `agent_completed`
  (`:371-435`) and `mentioned_content` on `agent_failed` (`:436-490`) in `card_events`, and the SSE
  stream sends the same payload (`api/v1/cards.py` event stream). The client only uses the event as
  an invalidation hint and refetches the comment.
- Outsider scenario: someone allowed to read a card's event stream or history receives a duplicate
  copy of comment text through a second surface with no retention, so text deleted from
  `comments` can remain in the event log. The same person can already read the comment, so the
  exposure is retention and data minimization, not new access.
- Why tests miss it: tests assert the payload shape, not the minimum field set.
- Verdict: VERIFIED.

## Clean areas

- Client bundle: `scan_build.py frontend/dist` → 0 SECRET, 0 LEAK. The 4 REVIEW hits are the
  provider presets (`http://127.0.0.1:8080`, `:11434`, `:9001`, `http://localhost` in router
  internals) which are product UI data, not internal hosts. No source maps; the client build guard
  passes.
- Mention job list and retry: board-scoped queries, UUID ids, only the caller's own card; the
  role snapshot is not returned (only its SHA-256) and the provider key is never serialized.
- Discussion messages and auto-run: actor identity comes from the session; auto-run accepts only
  human actors, so agent-authored messages cannot trigger loops; no client-supplied numbers or
  permissions are trusted.
- Error responses on the new endpoints: stable codes (`conflict`, `not_found`, `validation_failed`)
  with ids from the caller's own resource; no file paths, driver text or stack traces.
- SSE: both streams check scopes first and replay only the requested thread/card; disconnect
  unsubscribes in `finally`.
- Prompts and role text stay server-side; responses expose only role names and a hash.
- No listing of other users, tokens or credentials; no sequential identifiers.

## Refactoring plan

### Slice 1: scope the discussion overview like the board list

- **Goal:** a token without board access can no longer enumerate boards or their activity.
- **Findings covered:** LOW-1.
- **Changes:** require `boards:read` in `discussion_board_overview` in addition to
  `discussions:read` (or read boards through a method that enforces it). Document the scope pair in
  `docs/api.md`.
- **Guard:** an API test that issues a token with `discussions:read` only and expects `403` from
  `/discussions/overview`, plus a positive test with both scopes.
- **Size:** S.
- **Risk:** tokens that were issued for discussions only stop seeing the overview; document the
  change. UI sessions are unaffected.
- **Done when:** the negative test passes and the API docs name both scopes.

### Slice 2: agent directory projection for autocomplete

- **Goal:** a card view receives only what the mention list shows: id, name and role name.
- **Findings covered:** LOW-2.
- **Changes:** add a small directory endpoint (for example `GET /agents/directory`) or a
  `fields=summary` projection in `AgentService.serialize`, and use it from `CardDialog`. Keep the
  full endpoint for Settings.
- **Guard:** a response allowlist test for the directory shape.
- **Size:** S.
- **Risk:** none for Settings; the card dialog must handle the smaller shape.
- **Done when:** the dialog request returns no endpoint, model or credential fields.

### Slice 3: keep event payloads to ids and status

- **Goal:** the ticket event stream carries only what a client needs to refetch, with no duplicate
  content, and event rows stay small.
- **Findings covered:** LOW-3.
- **Changes:** drop `content` and `mentioned_content` from the recorded and published payloads
  (keep `comment_id`, `response_comment_id`, `agent_id`, `agent_name`, `error`, counters); update
  the frontend, which already refetches. Include `card_events` in the retention work (KAN-051).
- **Guard:** a test that asserts the allowlisted event payload keys, and the retention test once
  the policy exists.
- **Size:** S.
- **Risk:** external consumers that read text from the stream would need to refetch; document it.
- **Done when:** the payload test passes and the SSE frames contain no comment text.

## Open questions

- Is `discussions:read` intentionally enough to see board names in this single-organization
  deployment? If yes, record it as an accepted decision instead of a finding.
- Should deleted comments disappear from event history, or is an audit copy intended? That decides
  between trimming payloads and adding retention.
- Legal questions about prompt protection are for a lawyer; the analysis only covers technical
  exposure.


