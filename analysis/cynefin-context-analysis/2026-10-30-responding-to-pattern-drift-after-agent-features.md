2026-10-30

# Cynefin Context Analysis: responding to pattern drift after agent features

## At a glance

Context: Complicated with a Complex strand · confidence: medium · review point: after the next
increment or when first real usage data arrives

- A restart can permanently block a discussion or a mention job, which is a known failure with a
  known fix from decision 0002; it needs deliberate repair rather than more experimentation
  (Complicated, observed, Context assessment).
- How people expect agents to answer in conversations is still emerging: the last two increments
  were reactions to "why does nobody answer?", so further policy changes should be small,
  observable probes rather than another large behavioural change (Complex, observed, Recommended
  response).
- Board-first navigation moved per-request cost from the browser to one server fan-out across all
  board databases, and the acceptable latency has never been stated; a measured probe is needed
  before caching or a projection is chosen (Complicated, inferred, Open questions).

## Decision or situation

- **Decision in scope:** how to respond to the divergences found after KAN-082 (mentions), KAN-090
  (board-first discussions) and KAN-091 (automatic answers) — repair first, probe first, or keep
  adding features.
- **Owner:** the project's maintainer (single-developer, self-hosted product). Not confirmed by a
  stakeholder interview.
- **Affected parties:** the maintainer, the humans using the board, and the AI agents whose runs
  and replies are stored.
- **Desired outcome:** the documented architecture rules keep holding, users can rely on agent
  answers, and a restart never leaves silent, unusable state.
- **Time horizon:** days, not weeks; all changes so far shipped in one day and the code base is
  still small.

## Evidence and perspectives

Observed:

- `AGENTS.md` states one service layer, board isolation, registry authority, no new infrastructure
  without a decision, and single-process deployment.
- `docs/decisions/0002` promises explicit recovery states for cross-database operations. Startup
  recovery only handles `boards.status = 'maintenance'` (`services/__init__.py:57-64`); discussion
  runs and mention jobs are not reconciled.
- The two most recent user requests were both about the same symptom: "no agent answers". The
  product now has three ways to trigger replies (Run round, Run autonomously, automatic round on
  a human message with mode/mention conditions), which is a wide behavioural surface.
- The board-first overview was added after the thread list was perceived as slow; its cost was not
  measured before implementation (observed: 1.19–1.54 s at ~190 boards afterwards).
- `MentionService` writes agent replies directly, so the "comment" resource has two writers
  (`mentions.py:378-410`, `subresources.py:383-437`).

Inferred:

- The maintainer values fast, visible increments and is willing to adjust behaviour after trying
  it. That makes small probes cheap.
- Real usage is currently one local board and one user; scaling data comes from synthetic E2E
  boards, not production load.

Unknown:

- Acceptable latency and retention targets.
- How many simultaneous thread views users keep open.
- Whether users want an explicit "busy, try again" signal or queued automatic replies.

Perspectives:

- **Maintainer/architecture view:** keep the rules intact, especially recovery and the service
  boundary.
- **User view:** "I asked a question, nobody answered" is the failure that matters; the mechanism
  is secondary.
- **Operability view:** silent stuck state is worse than a visible error.

## Context assessment

Best-supported hypothesis: **Complicated**, with one **Complex** strand.

- **Complicated — async recovery, comment duplication, event retention, overview cost.** Cause and
  effect are knowable: a restart leaves a `running` row because nothing reconciles it; the retry
  endpoint refuses that state by design; the fix follows an existing decision. Analysis and
  targeted repair are appropriate, and more than one sound option exists (fail vs re-queue).
  Confidence: high for recovery and duplication; medium for retention policy (needs a target).
- **Complex — conversation behaviour and adoption.** Why people do not get answers cannot be
  predicted from the repository: the last two increments were responses to observed surprises,
  and the interaction between mode, mention, active run and closed thread creates emergent
  behaviour. Safe-to-fail probes with observation are appropriate. Confidence: medium.
- **Clear — migrations, tests, API envelope.** Established practice works; keep it and watch for
  exceptions (for example a new table escaping the migration test).
- **Chaotic — no.** Nothing is unstable enough to require action before analysis; the system is
  testable and the failures are reproducible.
- **Disorder — no.** The parts can be separated as above, and the maintainer has stated priorities
  in the handover and PRD.

Alternative hypothesis: one could call the whole situation **Complex** because the product is
young. That would overstate uncertainty for recovery, which has a known cause and a documented
remedy, and would delay a cheap repair.

## Recommended response

**Complicated parts — analyse, then apply good practice (in this order):**

1. Reconcile interrupted async work at startup, following decision 0002: fail `running`/`paused`
   runs with a visible reason, reset thread `run_state`, and make stuck mention jobs retryable.
   Bound: one query per board at startup; verify with a restart test.
2. Route agent replies through `CommentService` so the comment resource has one writer.
3. Add `card_events` to the retention decision (KAN-051) instead of leaving a second unbounded
   log.

**Complex strand — probe, sense, respond:**

- Probe A: return `auto_run` status on the message response and show a short hint ("a run is
  already active" / "thread closed") in the reply area. Observe whether the "no answer" reports
  stop.
- Probe B: if they do not, consider queueing the automatic round instead of skipping it. Bound it
  to one queued round per thread and a visible state.
- Decision criteria: no further "why no answer" reports; no unexpected automatic run during an
  active run; token usage stays understandable to the user.

**Clear parts — keep established practice:** Alembic revisions, API envelopes, pytest/Playwright
gates; monitor for a new table or endpoint escaping the documented rules.

Constraints and rationale: repairs are reversible and cheap, while behavioural changes affect
perceived agent reliability and token spend. Doing the repair first removes a confounder before
judging the conversation probes.

## Reassessment

Indicators that confirm the assessment:

- The recovery fix removes the only way a thread can become permanently unusable.
- The conversation probes change observable user reports, not only code.

Indicators that challenge it:

- More than one user reports confusion about mode/mention semantics; the Complex strand then
  deserves a dedicated design probe (for example mode simplification).
- Overview latency grows with board count beyond the agreed target; move the overview question to
  a measured performance analysis with a target.

Review point: after the next increment, or when the first real (non-synthetic) usage data or a new
"agents do not answer" report arrives.

## Open questions

- What latency is acceptable for the Discussions board list at 100 and 500 boards?
- Is a visible "a run is already active" hint enough, or should the automatic reply be queued?
- How long should run, mention and event history be kept?
- Is a manual SQL repair after a crash ever acceptable, or is automatic reconciliation required?
