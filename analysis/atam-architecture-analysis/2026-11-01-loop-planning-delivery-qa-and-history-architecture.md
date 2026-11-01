2026-11-01

# ATAM analysis: Loop planning, delivery, QA and history architecture

## At a glance

6 risks · 5 sensitivity points · 3 tradeoff points · 4 non-risks · provisional: yes

- An installation that already holds boards cannot move to this architecture by any supported route, so an existing user must either keep running the old version or erase every board (risk, observed, Findings F1).
- One Loop list request on a board with twenty Loops ran 124 SQL statements and took 16.7 ms locally, so the overview's cost grows with every Loop the board has (sensitivity point, observed, Findings F3).
- Approvals, staleness, readiness, QA separation and human-only gates held under adversarial tests, so the property the product is sold on is the strongest part of the design (non-risk, observed, Findings N1-N4).

## Scope and evidence

**System and version.** Tralala, commit `3737a9c` ("Loops v1"): the refactor that turns a board-owned
Kanban into App → Boards → Loops → Loop-owned planning documents, plan, Tickets, QA and history.
Evaluation purpose: decide whether the new architecture carries the product's quality goals, before
anyone builds on it.

**Evidence inspected (observed):**

- Documentation: `docs/architecture.md` (storage model, request lifecycle, cross-database
  consistency, Loop workflow, concurrency), `docs/loops.md`, `docs/database.md`, `docs/api.md`,
  `docs/decisions/0001-0009` (no decision record covers the Loop model or the schema transition).
- Code: `backend/migrations/board/versions/0008_loops.py` (492 lines, 12 `create_table`, two
  `batch_alter_table` recreations), `app/services/{loops,loop_documents,loop_plans,loop_qa,loop_history,loop_generation}.py`
  (753, 930, 1000, 799, 724 and 614 lines), `app/services/{cards,lists,search,boards,templates}.py`,
  `app/services/__init__.py` (composition root), `app/core/context.py`, `app/schemas/loops.py`,
  `app/storage/migration_manager.py`, `app/api/v1/{loops,history,cards}.py`.
- Behaviour: the 202 backend tests (25 Loop acceptance tests in `tests/test_loops.py`, 5 generation
  tests in `tests/test_loop_generation.py`), the 26 Playwright journeys, and the ruff/typecheck/build
  gates; all ran green at `3737a9c`.
- Measurement (run for this analysis, in-process `TestClient`, temporary data directory, median of
  five runs): `GET /boards/{id}/loops` with 20 Loops → **124 SQL statements, 16.7 ms**;
  `GET /boards/{id}/loops/{id}` → **10 SQL, 8.8 ms**; `GET /boards/{id}/tickets` → 4 SQL, 9.1 ms.

**Evidence not available (unknown):** who the stakeholders are, the supported release state (does any
customer run a pre-Loop version?), any numeric quality target, the expected number of Loops per
board, the production hardware, and whether the product may ever run more than one process per data
directory. Where these matter the finding below says so.

**Participants.** No stakeholder workshop. This is a repository- and measurement-based assessment
written by one agent (Copilot, Claude-family model). It must not be reported as stakeholder-approved.

## Business drivers and utility tree

**Driver D1 - an approved plan cannot be bypassed.** The Loop workflow exists so that a delivery
follows an approved analysis and RoadMap, and so that QA cannot be self-certified. Any change that
lets a caller skip a document, an approval or a QA decision destroys the reason to buy the product.
Source: `docs/loops.md`, `docs/architecture.md` "Loop workflow".

**Driver D2 - self-hosted, one process, one data directory.** `AGENTS.md` rule 8 and
`docs/architecture.md` "Consistency across databases" state that locks, rate limits and the session
secret are process-local. Deployability therefore means "one binary that starts reliably on a
customer's machine", not horizontal scaling.

**Driver D3 - source-available with paid commercial licences.** `docs/decisions/0009`. Bugs and data
loss matter commercially, not only technically; a licence customer expects to keep their data.
(mark: inferred from the licence decision; no customer evidence was available.)

**Driver D4 - humans and AI agents share one service layer.** `AGENTS.md` rule 1: React, REST and
WebMCP all call `backend/app/services/`. Extending the workflow must not create a second place where
rules live.

**Utility tree (quality attribute → scenarios; importance I / difficulty D, judged from the drivers
above, not from stakeholders):**

| QA | Scenario | I | D |
| --- | --- | --- | --- |
| Integrity | QA-1 A member submits a plan approval for revisions that have changed | high | medium |
| Integrity | QA-2 A caller edits a Ticket whose scope an approved plan owns | high | medium |
| Upgradeability | QA-3 An installation with three pre-Loop boards installs this version | high | high |
| Operability | QA-4 A board fails its migration while the server starts | medium | medium |
| Performance | QA-5 A member opens a board whose Loop count is high | medium | low |
| Modifiability | QA-6 A developer adds a sixth document slot or a new gate | medium | medium |
| Security | QA-7 An agent token tries every human-only action | high | low |
| Availability | QA-8 Two generation runs are requested while a provider is slow | medium | medium |

Priorities are provisional: no stakeholder confirmed them, and D3's weight depends on the release
state, which is unknown.

## Architecture and approaches

**Ownership chain.** `boards` (registry) → `loops` (board DB) → `lists`, `cards`, `loop_documents`,
`loop_plans` → `loop_phases`, `loop_plan_items`, `loop_dependencies` → `loop_qa_cycles`,
`loop_qa_results` → `loop_history`. Every child row carries `loop_id`, and `cards` carries a
composite foreign key `(list_id, loop_id)`, so a Ticket cannot point at another Loop's column
(`0008_loops.py:469-492`).

**Single rule authority.** Six services own the workflow and form a clean import DAG
(`loops` ← `loop_plans` ← `loop_documents` ← `loop_generation`, plus `loop_qa`, `loop_history`),
composed in one place (`app/services/__init__.py:48-62`). Routers, React and WebMCP call them; the
React client re-derives only which button to show.

**Structured plan as source of truth.** The RoadMap revision carries a validated payload
(`PlanPayload`); `loop_phases`, `loop_plan_items` and `loop_dependencies` are a projection written
when a human approves the revision, in one transaction, idempotently. Ticket keys
(`<LoopPrefix><LoopSequence>-<PhasePrefix><PhaseNumber>-<TicketSequence>`) are assigned at
publication, not by the model.

**Approval binding.** `loop_approvals` stores a human decision against exact revision ids and source
hashes; `_invalidate_downstream` clears dependent approvals, marks dependants stale and supersedes
an open QA cycle, and `compute_stage` returns `replanning` so execution freezes.

**Readiness as a graph.** `loop_plans.readiness` evaluates phases, plan items and dependencies in one
place and is called by both `GET /readiness` and every completion transition, so the displayed answer
and the enforced answer cannot drift.

**Generation.** Durable `loop_generation_runs` rows with a `ThreadPoolExecutor(max_workers=2)`
(`loop_generation.py:99`), one active run per (Loop, purpose), two bounded repairs, a context-hash
check before promotion, and the provider call factored out of the discussion runtime
(`runtime.call_completion`).

**History.** Completion writes an immutable hashed snapshot plus bounded artifacts in the same
transaction and marks the Loop read-only; repeated finalization returns the existing record.

## Scenario analysis

**QA-1 - approval of stale revisions.** Source: a member. Stimulus: submit a review for revision ids
that no longer match the current documents. Environment: normal operation. Response: the server
rejects the review; no approval row is written. Measure: `409`/`422` with a stable code, zero approval
rows. Evidence: `test_review_requires_the_exact_revisions`, `test_info_changes_make_approvals_and_execution_stale`.
Result: passes.

**QA-2 - editing an approved Ticket's scope.** Source: a member or agent token. Stimulus: `PATCH` a
Ticket that an approved plan owns. Environment: normal. Response: refused with `plan_change_required`
and the plan is unharmed; a replacement plan is the only route. Measure: `409`, unchanged Ticket
scope, no `loop_approvals` change. Evidence: `test_approved_ticket_scope_cannot_be_edited_through_a_card_endpoint`,
`test_moving_to_a_done_column_does_not_complete`. Result: passes.

**QA-3 - installing over an existing installation.** Source: an administrator upgrading a
self-hosted instance. Stimulus: start this version against data written by the previous release.
Environment: three boards with Lists and cards. Response expected: the boards come up with their
data, or a documented conversion path exists. Measure: zero lost boards. Response observed: startup
marks each board `migration_failed`, and the only documented remedy is
`python -m app.dev_reset --confirm`, which erases boards, backups and the registry; the export
archive of the old release is rejected because `import_archive` requires `format_version == 2`
(`boards.py:426`). Result: **fails** (F1).

**QA-4 - a board fails its migration at startup.** Source: the migration manager. Stimulus: one board
raises during upgrade. Environment: startup. Response: the other boards serve normally, the failed
board is marked `migration_failed`, mutations on it are blocked, the report is logged and
`POST /boards/{id}/migrate` retries. Measure: the process still starts; other boards answer `200`.
Evidence: `test_migrations.py`, `migration_manager.py:258-264`. Result: passes for the isolation part,
but the retry can never succeed for a pre-Loop database (F1), so the operator sees a permanently
broken board (F2).

**QA-5 - a board with many Loops.** Source: a member opening a board. Stimulus: `GET /boards/{id}/loops`.
Environment: 20 Loops, one process, WAL. Response: the loop overview renders. Measure: latency and
statement count. Observed: 124 statements, 16.7 ms median (≈6 statements per Loop, because
`LoopService.serialize` resolves documents, approvals, plan totals, QA cycle and progress per Loop).
Result: passes at 20 Loops; cost is linear with no batching, so the measure at 100+ Loops is unknown
(F3).

**QA-6 - adding a document slot or a gate.** Source: a developer. Stimulus: add a sixth slot and a
new gate type. Environment: development. Response: change five places (the `DocumentKind` literal in
`schemas/loops.py` and in `services/loops.py:25`, the renderers, the approval scopes, the UI tabs) and
one Alembic revision. Measure: number of files. Observed: at least five files plus a migration.
Result: acceptable but sensitive (F4).

**QA-7 - an agent token attempts a human-only action.** Source: a bearer token. Stimulus: approve a
document, confirm a human Ticket, accept QA. Environment: normal. Response: `403 human_action_required`
regardless of the scopes the token holds, because `require_human()` runs before the scope check and
`loops:review` is absent from the token scope literal. Measure: zero approvals written by an agent.
Evidence: `test_agents_cannot_approve`, `test_only_a_human_accepts_qa_and_completion_is_atomic`.
Result: passes.

**QA-8 - two generation runs while the provider is slow.** Source: two members. Stimulus: start
analysis generation for two Loops. Environment: a provider that answers slowly. Response: both runs are
accepted as durable rows, at most two execute, the queue drains; a second request for the same
(Loop, purpose) is refused with `409`. Measure: no lost run, no request thread blocked for the
provider's timeout. Evidence: `loop_generation.py:99,304`, `test_loop_generation.py`. Result: passes;
throughput is capped at two concurrent provider calls per installation, which is a deliberate bound
(F6).

## Findings

| ID | Type | Finding in one sentence | Scenarios / QA | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| F1 | risk | No supported path carries existing board data into this schema | QA-3 | `0008_loops.py:26`, `boards.py:426`, `dev_reset.py` | high (observed) |
| F2 | risk | A pre-Loop board is permanently `migration_failed` with no recovery other than erasing the installation | QA-3, QA-4 | `migration_manager.py:258`, `dev_reset.py` | high (observed) |
| F3 | sensitivity point | The Loop overview resolves each Loop with about six statements, so its cost is linear in Loops and unbounded by paging | QA-5 | measurement above, `loops.py:648-677` | high (measured) |
| F4 | sensitivity point | A new document slot or approval scope must be added in several literals and renderers that are not derived from one source | QA-6 | `schemas/loops.py:16`, `services/loops.py:25`, `loop_documents.py` renderers | medium (code reading) |
| F5 | tradeoff point | Storing the structured payload beside the rendered Markdown buys server-side truth and costs storage and a second thing to keep consistent | QA-1, QA-6 | `loop_documents.py` (`payload_json` + `content`), `docs/architecture.md` | medium |
| F6 | tradeoff point | A single two-worker executor keeps one process bounded but caps generation throughput per installation | QA-8 | `loop_generation.py:99` | high (observed) |
| F7 | sensitivity point | QA and generation depend on each other and the cycle is closed by attribute assignment in the composition root, not by the constructor | QA-6 | `services/__init__.py:56-58` | high (observed) |
| F8 | tradeoff point | Publishing a plan materialises every planned Ticket at approval time, which makes readiness cheap but forces a replacement plan for any scope change | QA-2, QA-6 | `loop_plans.py` publication, `test_approved_ticket_scope_cannot_be_edited_through_a_card_endpoint` | high (observed) |
| F9 | sensitivity point | Two copies of the same enumerations live in the backend (schema literal and service tuple), and each addition must touch both | QA-6 | `schemas/loops.py:16-21` vs `services/loops.py:25` | high (observed) |
| F10 | sensitivity point | Readiness is recomputed on every completion transition and on every Loop read, so a change in the graph evaluator affects correctness and latency at once | QA-2, QA-5 | `loops.py:721`, `loop_plans.readiness` callers | medium |
| N1 | non-risk | Approval, staleness and QA separation hold under adversarial tests | QA-1, QA-7 | Loop acceptance tests | high (observed) |
| N2 | non-risk | Ownership is enforced in the schema, not only in code, so a cross-Loop reference is impossible | QA-2 | `0008_loops.py:469-492` (composite FK, unique keys) | high (observed) |
| N3 | non-risk | One rule authority: routers, React and WebMCP add no second copy of the workflow | QA-1, QA-6 | `docs/architecture.md` "Loop workflow", import graph | high (observed) |
| N4 | non-risk | Startup migration isolates a broken board so the rest of the installation serves | QA-4 | `migration_manager.py`, migration tests | high (observed) |

**Risk theme A - the schema transition (F1, F2).** The specification chose a clean cut: a populated
database is refused rather than converted. That is defensible while the product is unreleased, and it
is what the specification asked for, but it is not recorded as a decision and it closes every data
path: no in-place migration, and the previous release's export archive is rejected by
`import_archive`. An installation that already holds boards therefore cannot adopt the version at
all. Because `docs/decisions/` has no entry for the Loop model or this cut, a reader cannot tell
whether the omission was deliberate. This is the only finding that can lose a customer's data, which
is why it is first.

**Risk theme B - unbounded per-entity work in the read path (F3, F10).** `LoopService.serialize` is
convenient: every caller gets a complete Loop. The cost is that a list of N Loops runs ~6N
statements, and readiness is recomputed wherever a Loop is read. At 20 Loops the measured 16.7 ms is
harmless; the architecture has no paging on `/loops`, so nothing stops a board from growing into a
slow page, and there is no test or budget that would notice.

**Risk theme C - enumeration literals instead of derived types (F4, F9).** The five document kinds
and four approval scopes exist as a Pydantic `Literal` in `schemas/loops.py`, a tuple in
`services/loops.py`, and renderer/UI switches. Adding a slot is a five-file edit with no compiler
help across the tuple and the UI. Cheap to fix while the workflow is small.

**Risk theme D - composition by attribute (F7).** `loop_qa.history`, `loop_qa.generation`,
`loop_generation.qa`, `loop.plans` and `loop.cards` are attached after construction. A unit test or a
future caller that builds a service directly gets `AttributeError` at the first call instead of a
type error, and the QA ↔ generation cycle is invisible in the import graph, so a reviewer cannot see
it.

**On the tradeoff points (F5, F6, F8).** None is a defect. F5 and F8 buy the property the product is
sold on (server-side truth, frozen approved scope) at the cost of duplicated storage and a
replacement-plan workflow; F6 bounds a self-hosted process at the cost of throughput. They are
recorded so that a future change does not remove the cost without noticing the benefit.

## Recommendations and open questions

**R1 (F1, F2).** Decide and document the upgrade story before this version is offered to any
existing installation. Cheapest honest option: a `docs/decisions/` record that states "pre-Loop data
is not migrated; the supported path is export with the previous release, then import" - and then make
that path real by accepting `format_version == 1` archives (convert them in the importer) with a test
that an archived pre-Loop board arrives as a Loop containing the old Lists and cards. Quality
attribute: upgradeability. Cost: one importer branch plus a conversion test; risk: the conversion
must decide Loop defaults (name, key prefix, columns), which is exactly the decision the
specification postponed.

**R2 (F1, F2).** Give the operator a readable remedy in the UI for a `migration_failed` board: the
board list shows the state, the reason, and links to the export of the last backup so nothing is lost
by trying. Quality attribute: operability. Cost: one component plus a hint string.

**R3 (F3).** Add paging or a summary projection to `GET /boards/{id}/loops` and keep the heavy
`documents`/`plan` payload for `GET /boards/{id}/loops/{id}`. Quality attribute: performance. Cost:
one schema plus one frontend query; risk: the overview currently shows badges derived from those
fields, so the summary must carry exactly what the list renders. Add a test that the statement count
per request stays below a fixed budget for a fixture of 25 Loops.

**R4 (F4, F9).** Derive the document kinds and approval scopes from one tuple and generate the
literals and the renderer dispatch from it. Quality attribute: modifiability. Cost: small refactor
with no schema change.

**R5 (F7).** Replace the QA ↔ generation attribute cycle with a constructor argument on one side, or a
small callable passed in, so the dependency is visible and a half-built service cannot exist.
Quality attribute: modifiability. Cost: one constructor signature.

**R6 (F10).** Keep readiness in one evaluator (already true) and add a test that a phase transition
and `GET /readiness` agree for a published plan, so a future optimisation cannot make the shown
answer differ from the enforced one. Quality attribute: integrity. Cost: one test.

**Status after this analysis (2026-11-01).** The owner confirmed the product is unreleased with no
installation data, which turns R1 into a decision rather than a conversion: it is recorded as
`docs/decisions/0010-loop-schema-transition-and-development-reset.md` with the release requirement
that a conversion path (or an explicit statement) replaces the refusal before the first public
release. R2 is implemented as a `migration_failed` banner with a retry and the export link. R3 is
implemented as a batched overview: `GET /boards/{id}/loops` now issues 11 statements for 5, 10 or 25
Loops (was 124 for 20) and `test_loop_overview_cost_does_not_grow_with_the_number_of_loops` holds the
budget. R4 derives `DOCUMENT_KINDS`, `LOOP_STAGES` and `APPROVAL_SCOPES` from the Pydantic literals.
R5 replaces the QA/generation attribute cycle with `LoopWorkflowLinks`, bound once in the composition
root. R6 is covered by `test_readiness_shown_and_readiness_enforced_agree`. F5, F6 and F8 stay as
recorded tradeoffs.

**Open questions for the stakeholders.**

1. Does any installation already run a pre-Loop version, and is the product released? If yes, R1 is a
   release blocker, not a cleanup.
2. How many Loops should one board be expected to hold, and what is the acceptable time to open a
   board? Without a number, F3 cannot be judged.
3. Is one process per data directory permanent? If a shared coordination store ever becomes
   acceptable, the readiness and generation bounds could change shape.
4. Who confirms the quality priorities in the utility tree? This assessment prioritised from the
   repository's own rules; a stakeholder view may weigh operability above integrity.
