2026-11-01

# Cynefin context analysis: adopting the Loop workflow after the refactor

## At a glance

Context: Clear for the way work is delivered, Complicated for the upgrade and cost decisions, Complex for whether the five-document workflow actually fits a real team, Disorder for the release question · confidence: medium · review point: when the owner answers whether any installation already holds pre-Loop data, and after the first two real Loops are delivered with the new workflow

- The rules the product is sold on already behave predictably and are covered by tests, so the next Loop can be run as ordinary practice instead of being re-litigated (Clear, observed, Recommended response 1).
- Three gaps - no upgrade path for existing board data, no cap on the per-Loop read cost, and a stale token scope list - can each be analysed and fixed with known techniques, so they should be settled by decision and evidence rather than by experiment (Complicated, observed, Recommended response 2).
- Whether humans and agents work better with five documents, approvals and phase gates is only knowable by running a couple of real Loops and watching what people actually do, which is what should be probed next (Complex, inferred, Recommended response 3).

## Decision or situation

**Decision in one sentence.** After the Loop refactor, should the Loop workflow be adopted as the
standard way Tralala's work is planned, delivered and recorded, and how should the team treat the
gaps the reviews found?

**Decision owner.** The repository owner (BitNomad AB), who commissions the work and holds the
licensing and release decisions. Known from `docs/decisions/0009` and this session's request.

**Affected parties.** Anyone who runs an installation (their data and upgrade path), the humans who
will approve documents and confirm human Tickets, the agent tokens that will generate and move work,
and whoever maintains `backend/app/services/` next.

**Boundary.** The Loop workflow as it now exists at commit `3737a9c`: documents, approvals,
publication, readiness, QA, history, and the interfaces that reach them (React, REST, WebMCP). Out of
scope: the discussion engine, themes, and the wider product roadmap beyond this refactor.

**Desired outcome.** A way of working that holds the product's core promise (an approved plan cannot
be bypassed) while remaining usable, maintainable and safe for existing installations.

**Time horizon.** The next release decision, and the first two real Loops delivered through the new
workflow - the earliest point where usage evidence can exist.

## Evidence and perspectives

**Observed (repository and measurements):**

- The workflow rules behave as designed under adversarial tests: approval binding to exact
  revisions, staleness propagation, frozen execution in `replanning`, human-only gates, atomic
  publication, idempotent finalisation. 202 backend tests and 26 Playwright journeys pass at
  `3737a9c`; `ruff`, `tsc`, the production build and the client build guard are clean.
- One rule authority is real: routers, React and WebMCP call `backend/app/services/`; the React
  client only decides which control to show.
- The refactor shipped without a `docs/decisions/` record for the Loop model or for the
  "no data migration" cut, although `AGENTS.md` rule 10 asks for a documented decision when a
  requirement changes the system's shape.
- `GET /boards/{id}/loops` with 20 Loops ran 124 SQL statements in 16.7 ms locally (measured for
  the ATAM analysis in this session). No paging exists on that endpoint.
- The settings page cannot issue a token with any `loops:*` or `history:read` scope
  (anti-reverse-engineering analysis, MEDIUM-1).
- A pre-Loop board cannot be migrated in place and the previous release's export archive is rejected
  (`format_version == 2` only), so no supported data path exists (ATAM F1/F2).

**Inferred:**

- Nobody has yet used the Loop workflow for a real delivery: the acceptance tests exercise the API,
  and the e2e suite drives the UI, but no repository evidence shows a Loop carried from Info to
  history by people doing actual work. Usage evidence therefore does not exist yet.
- The owner's attention is on architectural quality ("håller en bra standard"), not on a live
  incident: the request that produced this analysis asked for four evaluations of the refactor.

**Perspectives that differ or are missing:**

- The owner's own priority order (release readiness vs. feature depth vs. internal dogfooding) is not
  recorded anywhere; `docs/decisions/` shows past decisions but not a current priority.
- No customer or operator voice exists in the repository. Whether anyone would be harmed by the
  missing upgrade path depends on a release fact nobody has written down.

**Unknown:**

- Whether the product is released and whether any installation holds pre-Loop data.
- How many Loops a real board will hold, and what "fast enough" means to the owner.
- Whether agents or humans will do the bulk of the planning work in practice.

**Constraint that matters for the response pattern:** each remaining gap is cheap now and expensive
after release; the workflow's usability can only be learned by using it. Those two facts pull in
different directions and are the reason this situation is not one context.

## Context assessment

**1. Delivering work through the Loop workflow - Clear (high confidence).** Once a plan is approved,
the sequence is mechanical: generate or write the candidate, review it, approve exact revisions, let
publication create Tickets, complete Tickets when readiness allows, accept implementation, run QA,
accept QA, and the Loop closes with an immutable record. Cause and effect are stable, the rules are
enforced server-side and covered by tests, and a competent person needs no investigation to follow
them. Appropriate response: **sense, categorize, respond** - use the practice as it is, keep the
verification gates that already exist (`pytest`, `ruff`, `typecheck`, `pnpm build`, `test:e2e`), and
watch for exceptions rather than redesigning the flow. The alternative hypothesis, that the workflow
is still Complicated because nobody has run it, is partly right and is separated out below as its own
aspect rather than being allowed to blur this one.

**2. The upgrade path for existing installations - Complicated (high confidence).** The cause is
known and traceable: revision `0008_loops` refuses a populated database, and `import_archive` rejects
the previous `format_version`. The options are enumerable and comparable - accept and convert
version-1 archives in the importer; write a one-off conversion command that reads a pre-Loop board
file and writes the new schema; or declare that no installation exists yet and record the cut as a
decision. Which option is right depends on facts (release state, customer data) plus judgement about
how much conversion code the project wants to own. Appropriate response: **sense, analyze, respond** -
decide with the owner, write the decision down, and prove it with a test that an old board arrives
with its Lists and cards. This is not a place for experimentation: a wrong probe here destroys data.

**3. Whether the workflow fits real work - Complex (medium confidence).** The five documents,
approval boundaries, phase gates and QA handover were designed against a specification; how they feel
in a real delivery depends on interactions nobody can predict - how much an analysis document wants to
grow, whether a plain-language twin is written or rubber-stamped, whether a pre-phase gate blocks a
team for a day, whether generation produces usable candidates on this codebase. Patterns will only be
visible in retrospect. Appropriate response: **probe, sense, respond** with two bounded, reversible
probes (below), not with a large redesign of the workflow.

**4. The per-Loop read cost - Complicated, moving toward Clear (medium confidence).** The number is
measured and the cause is visible in `LoopService.serialize`; whether it matters is a decision about
an acceptable opening time for a board. Once a budget exists, the fix (summary projection or paging)
is a known technique with a test to hold it. Appropriate response: state a target, then treat it as
ordinary engineering.

**5. The release question - Disorder (medium confidence).** Whether the missing upgrade path is the
most urgent item depends on a fact the repository does not hold: has the product shipped, and does
someone's data predate Loops? Until that is answered, the priority between "fix the upgrade path" and
"use the workflow for real" cannot be settled honestly, and different reasonable people will order
them differently. Appropriate response: decompose - answer the release fact first, then re-assess
items 2 and 3 against it.

**6. Nothing here is Chaotic.** No incident, no instability, no harm accumulating while analysis
continues. Acting first would be the wrong response: the temptation to "just ship and see" is exactly
what item 2 warns against.

## Recommended response

**1. For the Clear part - keep the practice, do not re-open it.** Run the next piece of work as a
real Loop in this installation, with the existing verification gates unchanged. Watch for three
exceptions only: a document that must be regenerated repeatedly (a sign the schemas ask the wrong
question), a phase gate that blocks work it should not, and an approval that people confirm without
reading. Track those as observations, not as rework; the Clear practice is only in question if the
exceptions become the norm.

**2. For the Complicated parts - decide, document, prove.**

- Upgrade path: ask the release question (§Open questions 1), then either accept and convert
  version-1 export archives or record the "no migration" cut as a decision. Either way write
  `docs/decisions/` entry and a test. Rationale: reversible, cheap now, unrecoverable later. Risk:
  conversion code must choose Loop defaults (name, key prefix, columns), which is a product decision
  the specification postponed, so the owner has to make it, not a developer.
- Scope catalogue: make one authority for grantable scopes and remove the client copy. Rationale:
  without it an administrator must over-grant `boards:admin`, which is a silent privilege expansion.
- Read cost: set an explicit budget for opening a board (for example "under 100 ms with 50 Loops"),
  then enforce it with a test. Do not optimise before the budget exists; the measurement exists, the
  target does not.

**3. For the Complex part - two bounded probes with a defined observation.**

- **Probe A: one real Loop on the product itself.** Bound: one small, genuinely useful change (for
  example the upgrade-path decision's first slice), one Loop, at most one week, no changes to the
  workflow mid-Loop. Observe: how many document revisions before approval; whether the plain-language
  twin was written by a person or generated and accepted unread; how often a pre-phase gate fired;
  where people left the workflow to do something manually. Decision criterion: if more than one
  document needed three or more revisions, or a gate blocked work it should not have, the document
  schemas or the gate model need a change before wider use. Downside is bounded: one Loop, one week,
  and the workflow can be adjusted afterwards because no customer depends on it yet.
- **Probe B: agent-generated candidate quality on this codebase.** Bound: three generation runs for
  one analysis purpose against the configured agent, no planning approval until a human has read the
  output. Observe: how many schema repairs each run needed, how many findings a person deleted or
  rewrote, whether the plain-language rule produced real text. Decision criterion: if a person must
  rewrite more than half the findings, generation is a drafting aid rather than a plan author, and
  the UI and the docs should say so. Downside: a handful of provider calls and some minutes.

Do not combine the probes: A tests human use of the workflow, B tests generation quality, and
conflating them makes both unreadable.

**4. For the Disorder part - answer the fact, do not guess it.** One question to the owner decides
the order of everything else. Until then, treat the upgrade path as release-blocking rather than as
backlog, because the cost of being wrong in that direction is small (some work pulled forward) and
the cost of the opposite is a customer's data.

## Reassessment

**Review points.** (a) Immediately after the owner answers whether the product is released and whether
any installation holds pre-Loop data - that moves item 5 out of Disorder and re-orders items 2 and 3.
(b) After Probe A completes - that is the first real evidence about whether the workflow is Clear in
practice or still Complicated. (c) Before the next release, whatever the release state.

**Indicators that would move a part into another context.**

- Clear → Complicated: two consecutive Loops need changes to the workflow rules themselves, or a
  document kind is added for the second time in a month.
- Complicated → Complex: the upgrade-path decision keeps reopening after each analysis because new
  facts appear (for example, customers already ran the previous release with real data and each has a
  different shape of usage).
- Complex → Clear: Probe A and a second Loop follow the same path with no rule changes, and people
  stop asking where to record something.
- Complex → Chaotic would require an incident: a published plan producing wrong Tickets in a
  customer's board, or a Loop that cannot be completed because readiness deadlocks. Neither exists
  today, and `test_only_a_human_accepts_qa_and_completion_is_atomic` plus the readiness gate tests
  are the alarm that should fire first.

**What would change this assessment.** An answer that an installation already runs a pre-Loop version
does not change the domain labels, it changes the urgency inside them: item 2 becomes the only thing
that matters until it is solved. Evidence that people abandon the workflow after the first Loop would
move item 3's probe from "tune the schemas" to "question the five-document model", which is a
different, larger decision than the one analysed here.

## Open questions

1. Is the product released to anyone, and does any installation hold boards created before Loops? Only
   the owner can answer; it decides whether the upgrade path is release-blocking or cleanup.
2. What is an acceptable time to open a board, and how many Loops should a board be expected to hold?
   Needed to turn the measured 124 statements / 16.7 ms into a judgement.
3. Who approves a Loop in practice - the same person who wrote the Info document, or a second person?
   If it is the same person, the approval boundary is a ritual rather than a control, and the
   workflow should say so honestly.
4. How much of the planning work should agents do in the first months: drafting candidates that a
   person rewrites, or authoring plans that a person reviews? The answer decides whether Probe B's
   outcome is a failure or an expected result.
