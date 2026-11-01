2026-10-30

# ATAM Architecture Analysis: myboards-after-mentions-and-discussion-automation

The evaluation covers the repository state at commit `f4bf9fb` (agent mentions in ticket
comments, board-first Discussions navigation and automatic answers in discussions). It is
repository-based and provisional: no stakeholder workshop or business targets were available.

## At a glance

3 risks · 3 sensitivity points · 2 tradeoff points · 2 non-risks · provisional: yes

- A backend restart can leave a discussion or a mention job permanently stuck, so a team loses the
  ability to get answers until someone edits the database (risk, observed, F1).
- The board-first Discussions overview reads every board database on each request; with ~190
  boards one request took ~1.2 s in the E2E data set, and the page refreshes it every 30 s while
  visible (sensitivity point, observed, F4).
- In manual threads an `@agents` message starts one round, but when another run is already active
  the request is silently accepted without an answer, which looks like the original bug again
  (risk, observed, F2).

## Scope and evidence

- **System boundary:** the FastAPI service layer, per-board SQLite databases, registry database,
  React client and the in-process executors. Deployment is explicitly one backend process per data
  directory (`AGENTS.md` rule 8).
- **Sources inspected:** `AGENTS.md`, `docs/architecture.md`, `docs/database.md`, `docs/api.md`,
  `docs/decisions/0002-multi-database-consistency.md`, `backend/app/services/{discussions,runs,
  mentions,events,__init__}.py`, `backend/app/api/v1/{discussions,cards,streaming}.py`,
  `backend/migrations/board/versions/0007_comment_mentions.py`,
  `frontend/src/features/discussions/{DiscussionsPage.tsx,useDiscussionEvents.ts}`,
  `frontend/src/features/cards/{CardDialog.tsx,useCardEvents.ts}`, the backend test suite and the
  Playwright suite.
- **Evidence labels:** repository behaviour is *observed*; latency figures come from the local E2E
  log (*observed*, one machine); business priorities and targets are *unknown*.
- **Participants:** none; the analysis is provisional and the open questions in the last section
  list what stakeholders must confirm.

## Business drivers and utility tree

The product is a self-hosted, AI-native Kanban where agents discuss tickets but never execute
changes. Repository-derived drivers:

- Keep every board's data independent and recoverable.
- Let humans get an answer from agents without reading internals.
- Stay operable on a single process with no broker.

| Attribute | Scenario (abbreviated) | Importance | Difficulty | Basis |
| --- | --- | --- | --- | --- |
| Availability / operability | S1: restart during a run or mention job | high | medium | docs/decisions/0002 promises explicit recovery states |
| Performance | S2: open Discussions with 200 boards | medium | medium | new fan-out endpoint, no target agreed |
| Usability | S3: human asks a question in a thread | high | low | the reported defect that motivated KAN-091 |
| Modifiability | S4: add a rule for ticket comments | medium | low | AGENTS.md "one service layer" |
| Security | S5: agent credentials and board access | high | low | AGENTS.md security invariants |

## Architecture and approaches

- **Service layer and composition root.** `Services` wires `DiscussionService`, `RunService`,
  `MentionService` and `EventService`; optional collaborators are attached after construction
  (`backend/app/services/__init__.py:44-55`), the same pattern already used for discussion runs.
- **Async work without infrastructure.** Both `RunService` and `MentionService` own an in-process
  `ThreadPoolExecutor` and use a database row as the status channel
  (`backend/app/services/runs.py:62`, `backend/app/services/mentions.py:112-124`). This honours
  "no new infrastructure" and the single-process rule.
- **Two event scopes.** `EventService` writes `discussion_events` or `card_events` and derives the
  subscriber key from the event row; one publish path serves both SSE endpoints
  (`backend/app/services/events.py:96-154`, `backend/app/api/v1/streaming.py`).
- **Board-first navigation.** `DiscussionService.board_overview` aggregates
  `MAX(last_activity_at)`, `discussion_count` and `open_count` per board database
  (`backend/app/services/discussions.py:256-300`); the client loads threads only for the selected
  board.
- **Automatic answers.** `DiscussionService.add_message` starts one background round when the
  thread mode is roundtable/autonomous or the message contains `@agents` or a participant name;
  only human actors trigger (`backend/app/services/discussions.py:25-37,411-521`).
- **Ticket mentions.** `CommentService.create` saves the comment, then `MentionService.queue`
  resolves enabled agents from the registry and writes jobs in a separate board transaction
  (`backend/app/services/subresources.py:430-437`, `mentions.py:168-238`).

## Scenario analysis

**S1 — Restart during in-flight work (availability/operability).**
Stimulus: the process stops while `discussion_runs.status = 'running'` or
`comment_mention_jobs.status` is `queued`/`running`. Expected response: after restart the thread is
usable and the work can be retried or is marked failed. Observed: startup calls only
`board.recover()`, which repairs `maintenance` board rows and nothing else
(`backend/app/services/__init__.py:57-64`). The run row stays `running`; `_prepare` refuses a new
run and review is refused while the row is active (`runs.py:36,277`). Mention jobs stay
`queued`/`running`; retry refuses both (`mentions.py:253-267`), so the only exit is manual SQL.
Response measure: none agreed; a reasonable target is "zero permanently blocked threads after a
restart". Result: **risk**.

**S2 — Open Discussions with ~200 boards (performance).**
Stimulus: a user opens `/discussions`; React requests `/discussions/overview` and repeats it every
30 s while the list is visible. Expected response: the board list appears quickly. Observed: each
request opens and queries every board database (193 boards in the E2E data set); the E2E log shows
1.19–1.54 s per request on this machine, and three requests occurred within a short window during
a test. Response measure: unknown (no agreed target). Result: **sensitivity point**, not a proven
risk without a target.

**S3 — Human asks a question (usability).**
Stimulus: a human posts a message in a manual thread containing `@agents`. Expected: one round runs
and the participants answer. Observed: `_auto_run` starts `rounds=1, background=True`; the Playwright
journey asserts the round counter advances from 0 to 1 after Send. If a run is already active or
the thread is closed, `Conflict`/`ValidationFailure` are swallowed and the message is stored with
no run and no hint (`discussions.py:508-521`) — the user cannot tell why nothing happened.
Result: partly **non-risk** (happy path observed), partly **risk** (silent skip, F2).

**S4 — Add a rule for ticket comments (modifiability).**
Stimulus: a future rule must apply to every comment (for example retention or moderation).
Expected: change one code path. Observed: comments are inserted by `CommentService.create` and again
by `MentionService._complete` with its own activity entry (`mentions.py:378-410`); the agent reply
does not pass through `CommentService`. Result: **sensitivity point**.

**S5 — Board isolation and credential handling (security).**
Stimulus: a user mentions an agent in a comment or a discussion. Expected: no path from user text
to the filesystem, no credential exposure, no agent-triggered loop. Observed: agent ids come from
the registry, jobs live in the board database, provider keys are decrypted only inside
`runtime.call_agent`, new endpoints require `cards:read`/`discussions:read`, and auto-run accepts
only human actors (`mentions.py:168-238`, `discussions.py:505`). Result: **non-risk** under the
stated assumptions.

## Findings

| ID | Type | Finding | Scenarios / attributes | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| F1 | risk | A restart leaves `running` discussion runs and `queued`/`running` mention jobs without recovery, permanently blocking runs, review and retry. | S1; availability, operability | `services/__init__.py:57-64`, `runs.py:277`, `mentions.py:253-267`, `docs/decisions/0002` | high |
| F2 | risk | An automatic round that cannot start is swallowed without feedback, so the user again sees an unanswered message with no explanation. | S3; usability, operability | `discussions.py:495-521` | medium |
| F3 | risk | `card_events` adds a second unbounded event log; retention (KAN-051) and future export/backup work must now cover both logs, or board files grow forever. | S1; storage, operability | `migrations/board/versions/0007_comment_mentions.py`, `events.py:96-120`, `.ralph/prd.json` KAN-051 | medium |
| F4 | sensitivity point | `/discussions/overview` performs one database read per board per request (1.19–1.54 s at ~190 boards) with no cache and a 30 s client refresh. | S2; performance | `discussions.py:256-300`, E2E server log | high |
| F5 | sensitivity point | Mention replies bypass `CommentService` and duplicate the comment insert and activity rules, so a future comment rule can miss agent replies. | S4; modifiability | `mentions.py:378-410` vs `subresources.py:383-437` | high |
| F6 | sensitivity point | Every open thread/card SSE stream polls its queue through the shared anyio worker pool once per second, so concurrency is bounded by the thread pool (~40 by default). | S2; performance | `api/v1/streaming.py:40-75`, `useDiscussionEvents.ts`, `useCardEvents.ts` | medium |
| F7 | tradeoff point | Two durable event tables give clean per-scope replay and board isolation, at the cost of duplicated schema and duplicated retention/export work. | S1, S4 | `events.py`, `0006_discussion_events`, `0007_comment_mentions` | high |
| F8 | tradeoff point | In-process executors keep the no-broker/single-process rule, but work is lost on restart and the system cannot scale out. | S1; availability, deployability | `runs.py:62`, `mentions.py:112`, `AGENTS.md` rules 8 and 10 | high |
| F9 | non-risk | Board isolation and registry authority hold for mentions: agent resolution comes from the registry, jobs and comments stay in the board database, no user text reaches a path. | S5; security | `mentions.py:168-238`, `subresources.py:430-437` | high |
| F10 | non-risk | New endpoints enforce scopes and auto-run accepts only human actors, so agent messages cannot create loops. | S5; security | `api/v1/discussions.py`, `api/v1/cards.py`, `discussions.py:505` | high |

Risk themes:

- **Interrupted async work (F1, F8).** The single-process executor is a deliberate tradeoff, but
  the missing reconciliation turns a crash into a permanent state for the affected thread.
- **Silent degradation (F2, F3).** Both hidden work and growing logs fail quietly until someone
  looks at the database.
- **Per-board fan-out (F4, F6, F7).** Board isolation is preserved, but request cost and stream
  concurrency now scale with the number of boards and open views.

## Recommendations and open questions

1. **Reconcile async state at startup (F1).** Mark `discussion_runs` in `running`/`paused` as
   `failed` with `stop_reason=process_restart`, reset the thread `run_state` to `idle`, and mark
   `comment_mention_jobs` in `running` as `failed` (retryable) or re-queue `queued` jobs. This
   follows decision 0002's "explicit recovery state" pattern and costs one query per board at
   startup. Benefit: availability; cost: a small startup pass over every board.
2. **Report a skipped automatic round (F2).** Return an explicit `auto_run` field (for example
   `started`, `already_running`, `thread_closed`) on the message response and show it in the reply
   area, or record a `run_skipped` event. Benefit: usability; cost: one response field and a UI
   hint.
3. **Decide retention for both event logs (F3, F7).** Extend KAN-051 to cover `card_events` too,
   or introduce one retention helper used by both scopes. Benefit: bounded board files.
4. **Measure and bound the overview (F4).** Set a target for `/discussions/overview` with the
   product owner, then consider a short-lived in-process cache (for example 5 s) or a registry-side
   projection updated on discussion activity. A cache must be invalidated on activity, so the
   projection has the cleaner tradeoff if the target cannot be met.
5. **Route agent replies through `CommentService` (F5).** Give `CommentService` an internal method
   that accepts an explicit author, so retention, moderation or notification rules stay in one
   place. Benefit: modifiability; cost: a small refactor of `MentionService._complete`.
6. **Validate SSE concurrency assumptions (F6).** Confirm the intended number of simultaneously
   open thread/card views; if it can approach the worker-pool size, consider one shared event
   fan-out instead of one queue poll per stream.

Open questions for stakeholders:

- What are the availability and recovery expectations after a backend restart (is manual SQL
  acceptable in any case)?
- What is the acceptable latency for the Discussions board list at 100/500 boards?
- How long should run/mention history and event logs be kept?
- Should an automatic reply be attempted again when a run is already active, or is a visible
  "busy" hint enough?
