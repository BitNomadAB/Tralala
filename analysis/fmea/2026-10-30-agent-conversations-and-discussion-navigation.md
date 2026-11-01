2026-10-30

# FMEA: agent conversations and discussion navigation

Scope: the async agent work and conversation surfaces added by KAN-082 (mention jobs in ticket
comments), KAN-090 (board-first Discussions) and KAN-091 (automatic rounds on human messages).
Repository state: commit `f4bf9fb`. Analysis is repository-based; no production incident data,
usage metrics or agreed rating rubric were available.

## At a glance

12 failure modes · 3 high-severity concerns · 6 recommended actions · ratings: not rated (no
agreed severity/occurrence/detection rubric; priorities are qualitative)

- A backend restart can leave a discussion run or a mention job permanently stuck, so a user can
  never get an answer and cannot even retry (high severity, observed, F1).
- When a run is already active, an `@agents` message is accepted but silently produces no answer,
  which recreates the defect the feature was meant to fix (high severity, observed, F2).
- If the ticket event stream is unavailable, the card dialog never refreshes a running mention
  job, so the UI shows "running" indefinitely (high severity, inferred, F10).

## Scope and method

- **FMEA type:** software/service FMEA for one subsystem, not the whole platform. The earlier
  platform FMEA (`analysis/fmea/2026-10-30-ai-native-kanban-platform.md`) covers the wider system.
- **Item boundary:** `MentionService`, `CommentService` mention hook, `RunService` trigger from
  `DiscussionService.add_message`, `EventService` scopes, the two SSE endpoints, the card and
  discussion UI surfaces, and `DiscussionService.board_overview`.
- **Intended functions:**
  1. An `@agent` mention in a ticket comment produces one agent reply, retryable without
     duplicates.
  2. A human discussion message produces an answer in roundtable/autonomous mode, or when it
     mentions `@agents`/a participant in manual mode.
  3. Discussion navigation lists boards by newest activity and loads only the selected board's
     threads.
  4. Live updates arrive over SSE and the stored event log allows replay.
- **Environment:** one backend process per data directory, SQLite with WAL, in-process
  `ThreadPoolExecutor`, no broker (`AGENTS.md` rules 8 and 10).
- **Lifecycle phase:** post-implementation, pre-broader-use.
- **Rating method:** none agreed. Ratings below are qualitative (severity/exposure/detection
  descriptions) and are not scores.

## FMEA table

| ID | Function | Failure mode | Effects | Causes | Existing prevention | Existing detection | Evidence | Rating |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | Produce an agent reply / run a discussion | The process stops while a run or mention job is in flight; the row stays `running`/`paused` or `queued` | The thread cannot start a new run (409), review is refused, the mention job cannot be retried; only manual SQL recovers it | Work lives in an in-process executor; startup recovery only repairs `boards.status` | Status row in the database; per-job lock; single process | None: no stale-state indicator or reconciliation at startup | `runs.py:62,277`, `mentions.py:253-267`, `services/__init__.py:57-64`, `docs/decisions/0002` | High severity, low exposure (only on restart), no detection |
| F2 | Answer a human message automatically | The automatic round is not started because a run is active or the thread is closed, and nothing is reported | User sees the message posted but no answer; looks like the original "agents do not answer" defect | `Conflict`/`ValidationFailure` swallowed in `_auto_run` | Explicit Run round button; run state badge | Weak: the run state badge changes, but the message response carries no reason | `discussions.py:495-521` | High severity, medium exposure, weak detection |
| F3 | A mention job produces exactly one reply | The same job executes twice and inserts two agent comments | Duplicate answers in the thread | Double submit or duplicate queue call | Unique `(comment_id, agent_id)`; status `queued→running` claim; per-job lock; guarded completed update | Unique constraint and status guard; covered by a retry test | `mentions.py:342-410`, migration `0007` | Low severity, low exposure, strong detection |
| F4 | Retry a failed mention without duplicates | A retry is accepted after an answer already exists | Duplicate or confusing reply | Race between worker completion and retry | Retry refuses an answered job (409) and the answer insert is guarded by `response_comment_id IS NULL` | API returns 409; tests cover it | `mentions.py:241-277` | Low severity, low exposure, strong detection |
| F5 | Answer with the current ticket context | Context is stale or incomplete (label/checklist/comment changed after the job was queued) | Answer addresses an older state | Context is read at execution time, not at queue time | Job stores a role snapshot; context fetched right before the call | None; content differences are only visible in the answer | `mentions.py:470-560` | Medium severity, expected, no detection |
| F6 | Resolve a mentioned agent | A mentioned agent is disabled or deleted between queue and execution | Job fails with `agent_missing` / no answer | Registry state changes | Explicit enabled check at execution; retry available for failed jobs | Job status `failed` with error, `can_retry` in the API | `mentions.py:304-330,436-490` | Low severity, low exposure, good detection |
| F7 | Keep board isolation | A mention job or event is written to the wrong board database | Cross-board data leak or missing reply | Wrong board id passed to the service | Board ids resolved through `BoardDatabaseManager`; tests per board | Database FK on `card_id` | `mentions.py:168-238` | Low severity, very low exposure, strong detection |
| F8 | Serve the Discussions overview | Every board database is queried per request, so the request grows with board count | Slow first paint and server load as boards accumulate | Per-board aggregation with no cache or projection | Client caches with React Query and refreshes at 30 s | Request duration in structured logs (observed 1.19–1.54 s at ~190 boards) | `discussions.py:256-300`, E2E server log | Medium severity, high exposure at scale, good detection |
| F9 | Show truth for unreadable boards | A board that cannot be opened is reported with zero discussions and no indication | An empty-looking board hides a migration or availability problem | `NotFound`/`ServiceUnavailable` mapped to zeros | Board status is included in the response and badged in the UI | Weak: only the status badge, no per-board reason | `discussions.py:256-270` | Medium severity, low exposure, medium detection |
| F10 | Deliver live updates | SSE connection drops (proxy, sleep, auth expiry) while a mention job runs | UI keeps showing `queued`/`running`; no answer appears until the dialog is reopened | EventSource error only flips the `live` flag; no fallback refresh for mentions | Browser reconnects with `Last-Event-ID`; discussion detail polls while a run is active and not live | Discussion page has a polling fallback; the card dialog has none | `useCardEvents.ts`, `CardDialog.tsx`, `DiscussionsPage.tsx` | High severity, medium exposure, no detection in the card dialog |
| F11 | Keep events for replay | `card_events` (and `discussion_events`) grow without retention | Board files grow indefinitely; backups and restores slow down | No retention job for event logs; KAN-051 covers only activity/idempotency | SQLite WAL and bounded request size | None; no size metric | migration `0007`, `.ralph/prd.json` KAN-051 | Medium severity, certain over long time, no detection |
| F12 | Interpret a human message | `@agents` inside a quoted block or example text starts a round | Unexpected token spend and an unexpected answer | Pattern match does not distinguish prose from quotes/code | One round only; human actor only | User sees the new run and toast/round counter | `discussions.py:25-37,495-521` | Low severity, medium exposure, good detection |

## Priorities

High-severity concerns, independent of any aggregate score:

- **F1** — a single restart turns a usable thread into a permanently blocked one, with no UI path
  to recover. This contradicts the recovery pattern that decision 0002 established.
- **F2** — the exact user-visible symptom that motivated KAN-091 returns in a narrower case, and
  the product gives no explanation.
- **F10** — the card dialog can show a stale "running" job forever when live updates are
  unavailable, which again reads as "the agent never answers".

Medium priorities: F5 (stale context is expected but invisible), F8/F9 (overview cost and
truthfulness), F11 (unbounded logs).

Low priorities or accepted controls: F3, F4, F6, F7, F12.

## Recommended actions

| Action | Targets | Action | Gap addressed | Expected effect | Owner / status |
| --- | --- | --- | --- | --- | --- |
| A1 | F1 | Reconcile interrupted work at startup: fail `running`/`paused` runs with `stop_reason=process_restart` and reset the thread `run_state`; mark `running` mention jobs failed (retryable) and re-queue `queued` jobs | Missing recovery control | A restart no longer blocks a thread; the failure is visible and retryable | TBD |
| A2 | F2 | Return an `auto_run` outcome (`started`, `already_running`, `thread_closed`) on the message response and show a hint in the reply area | Silent skip | The user learns why no answer is coming | TBD |
| A3 | F10 | While any mention job is `queued`/`running`, poll the mentions query (for example 2 s) unless the SSE stream is live | Missing detection in the card dialog | The answer appears even when SSE is unavailable | TBD |
| A4 | F11 | Extend the retention story to both event logs (or one shared retention helper) and expose board database size in the validate endpoint | Unbounded growth and no detection | Bounded board files; observable growth | TBD (relates to KAN-051) |
| A5 | F8, F9 | Agree a latency target for `/discussions/overview`; consider a short-lived cache or a registry-side activity projection; return a reason for boards that cannot be read | Cost grows with board count; zeros hide errors | Predictable list latency; a failing board is distinguishable from an empty one | TBD |
| A6 | F5 | Record in the answer (or job payload) whether context was captured at queue time or execution time, and state the behaviour in docs | Invisible context timing | Users and reviewers can explain an answer that ignores a newer comment | TBD |

Residual risk can only be reassessed after these actions are implemented and verified with the
same qualitative basis; no numeric reduction is claimed here.

## Assumptions and open questions

- No production usage data: exposure estimates come from repository structure and the E2E data
  set (≈190 synthetic boards, one local user).
- No incident history was available; F1, F2 and F10 are derived from code paths, not from observed
  outages.
- Requirements still missing: acceptable overview latency, event retention period, whether a
  skipped automatic round should be queued or only reported.
- FMEA covers individual failure modes; combinations such as "restart during a run that is also
  paused" and adversarial behaviour are better served by a fault-tree analysis and a threat model.
  The repository's anti-reverse-engineering analysis covers the client/API exposure angle.

