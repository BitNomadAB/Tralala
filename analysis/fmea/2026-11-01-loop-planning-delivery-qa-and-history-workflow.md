2026-11-01

# FMEA: Loop planning, delivery, QA and history workflow

## At a glance

18 failure modes · 14 high-severity concerns · 8 recommended actions · ratings: qualitative bands proposed by the analyst (no agreed rubric exists in the repository), no RPN

- Two processes started against the same data directory would both run the schema rebuild on the same board file, and nothing stops that from happening (Critical, observed absence of a lock, F11, Actions A2).
- A board created before Loops cannot be upgraded and cannot be recovered, so an installation that already holds work loses it if it adopts this version (Critical, observed, F10, Actions A1).
- The write path had already lost the completed-Loop guard on attachments and discussions before this analysis, which shows the guard is enforced per endpoint rather than once, so a new endpoint can silently reopen it (High, observed and fixed today, F9, Actions A4).

## Scope and method

**Type.** Software/process FMEA of the Loop workflow as implemented at commit `3737a9c`, covering the
path from creating a Loop to its immutable history record, plus the operations that surround it
(startup migration, generation runs, authorization of agent tokens).

**Boundary.** In scope: `backend/app/services/{loops,loop_documents,loop_plans,loop_qa,loop_history,loop_generation,cards,lists}.py`,
`backend/migrations/board/versions/0008_loops.py`, `app/storage/{migration_manager,fts}.py`,
`app/core/context.py`, the related schemas and the interfaces that reach them. Out of scope: the
discussion engine's own runs, theme handling, and the parts of the product untouched by the refactor.

**Lifecycle phase and environment.** Design and first release of the workflow; a single self-hosted
process per data directory (`AGENTS.md` rule 8), SQLite in WAL mode with a 5 s busy timeout, one
data directory holding `registry.sqlite` and `boards/{uuid}/board.sqlite`, and provider calls to a
user-configured OpenAI-compatible endpoint.

**Intended functions analysed.** (1) create and own a Loop, (2) bind an approval to what was seen,
(3) keep approvals and execution honest when inputs change, (4) publish a plan exactly once, (5)
assign stable Ticket identities, (6) decide phase entry and completion, (7) gate Loop completion on
delivery and QA, (8) write history once and never change it, (9) keep a finished Loop read-only, (10)
carry existing data forward, (11) keep one process per data directory, (12) call a provider safely,
(13) promote only a candidate built from current input, (14) keep a Ticket's approved scope stable,
(15) reserve human-only actions for humans, (16) issue a least-privilege agent token, (17) find a
completed Loop.

**Rating method.** The repository defines no severity, occurrence or detection scale, so no numeric
S/O/D and no RPN is used. Each row carries a qualitative band with the definitions used here:

- **Severity** - Critical: corrupts or loses data, or breaks the approval record the product is sold
  on. High: a workflow rule can be bypassed or a Loop can be left unable to progress. Medium:
  confusing state, or a privilege larger than intended. Low: operational noise only.
- **Control strength** - *Guarded*: enforced in the schema or by a test that fails if the rule is
  removed. *Partly guarded*: enforced in code with no test for this specific mode. *Unguarded*: no
  prevention and no detection.
- **Evidence** - *observed* (read, run, or measured in this session), *inferred*, *unknown*.

These bands are the analyst's proposal, not an agreed scale; they order the actions and are not
comparable with any other report.

## FMEA table

| ID | Function | Failure mode | Effects | Causes | Existing prevention controls | Existing detection controls | Evidence | Severity | Control |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | Create and own a Loop | A Loop is created for a board whose database is missing or mid-repair | Orphan registry row, Loop endpoints answer `404`, work is retyped | Board in `maintenance`/`error`, or a deleted board file | `BoardService.ensure_active`, `BoardService.recover()` on startup | Board status in the registry; startup log | observed (`services/boards.py`, board tests) | High | Partly guarded |
| F2 | Bind an approval to what was seen | Approval recorded for revisions the approver never opened | A plan or analysis is "approved" that nobody read; later execution inherits it | Client cache holds an older revision id; concurrent edit | Server compares exact revision ids and source hashes and rejects a mismatch | Rejection is visible; no audit of "who read what" | observed (`loop_documents.approve`, `test_review_requires_the_exact_revisions`) | Critical | Guarded |
| F3 | Keep approvals honest when inputs change | A dependent document keeps a valid approval after an upstream document changed | Execution proceeds on an invalidated plan; QA accepts work against an old analysis | Missed propagation branch in `_invalidate_downstream` | Approval pointers cleared, dependants marked stale, open QA superseded, stage forced to `replanning` | Stage and warnings on every Loop read | observed (`services/loops.py`, `test_info_changes_make_approvals_and_execution_stale`, `test_reopening_a_prerequisite_invalidates_qa`) | Critical | Guarded |
| F4 | Publish a plan exactly once | Publication writes some planned Tickets and not others, or writes them twice | Kanban diverges from the approved plan; duplicate Tickets | Interrupted request, retry, or a bug in the projection loop | One transaction for the whole publication; idempotent by plan revision; unique keys | `test_publication_is_idempotent`, unique indexes | observed | Critical | Guarded |
| F5 | Assign stable Ticket identities | Two Tickets share a Ticket key | Deep links and history point at the wrong work | Prefix collision between Loops, or a sequence reused after a plan change | Deterministic two-character Loop prefix and per-board sequence; unique partial index `ux_cards_ticket_key` | Insert fails loudly | observed (`0008_loops.py:512`, `loop_identifiers.py`, `test_ticket_keys_are_unique_and_stable`) | High | Guarded |
| F6 | Decide phase entry | A Phase waits on itself through a gate, so the Loop can never progress | Loop stuck in `in_progress`; users work around the workflow | A gate modelled as depending on its own Phase | A pre-phase gate depends only on its explicit prerequisites; phase entry adds prerequisite phases, prerequisite Tickets and own gates | Readiness response shows the blockers per Ticket | observed (`loop_plans.readiness`, `test_human_gate_blocks_only_its_downstream_phase`) | High | Guarded |
| F7 | Gate Loop completion on delivery | Delivery is accepted while Tickets are open | Record claims completion with undone work | Caller skips a Ticket, or archives an incomplete one | `open_delivery` refuses acceptance with `ticket_blocked`; archived-but-incomplete Tickets are counted in `progress` | 409 with the open list | observed (`loop_qa.accept_implementation`) | High | Guarded |
| F8 | Write history once and never change it | The history record is written twice, or edited afterwards | The record no longer proves what happened; search shows two versions | Retried finalization; a future endpoint that updates the row | One native row per Loop, immutable snapshot with content hash, idempotent return of the existing record, Loop becomes read-only | Callers receive the first record on every retry | observed (`loop_history.py`, `test_only_a_human_accepts_qa_and_completion_is_atomic`) | High | Guarded |
| F9 | Keep a finished Loop read-only | A mutation is accepted through a path that forgot the guard | A completed Loop changes after its history was written; the record and the data disagree | The guard is per endpoint; a new or retrofitted endpoint misses it | `require_mutable_card`/`require_mutable_checklist` in `services/common.py`, called from cards, checklists, attachments and discussions | None beyond the individual endpoint; no cross-endpoint test | observed - attachment delete, attachment upload and discussion create had no guard until this session; tests added today | High | Partly guarded |
| F10 | Carry existing data forward | A pre-Loop board is refused at startup and has no recovery | An installation that already holds boards cannot adopt the version without erasing them | Revision `0008_loops` refuses a populated database by design; `import_archive` accepts only `format_version == 2` | Startup guard with an actionable log line; board marked `migration_failed` | Migration report at startup and the board status | observed (`0008_loops.py:26`, `boards.py:426`, ATAM F1/F2) | Critical | Guarded against damage, unguarded for recovery |
| F11 | Keep one process per data directory | Two processes serve the same data directory at once | Concurrent DDL rebuild on the same board file; one process marks a board `migration_failed` while the other writes to it; rate limits and per-board locks stop being global | The constraint is documented only; no lock file, no PID check anywhere | None in code; `AGENTS.md` rule 8 is a written rule | The startup log shows both processes; nothing alerts | observed (no lock found in `core/config.py`, `main.py`, `storage/`) | Critical | Unguarded |
| F12 | Call a provider safely | A run stays `running` forever and blocks that purpose for the Loop | The Loop cannot generate again until someone cancels; users retry and duplicate work | A provider that never answers, or a timeout configured to 0/None | `httpx` timeout from the agent row (60 s default), two bounded repairs, one active run per (Loop, purpose), cancel/retry endpoints, startup recovery marks leftovers `interrupted` | Run status and `generation_in_progress` conflict | observed (`loop_generation.py`, `runtime.call_completion`) | Medium | Guarded |
| F13 | Promote only a candidate built from current input | A candidate computed from superseded documents becomes the current revision | Plan or analysis reflects text nobody approved, with a plausible provenance trail | Documents edited while the model works | Context fingerprint compared before promotion; mismatch marks `generation_input_changed` and keeps the output aside | Run status and the stored candidate | observed (`_promote`, `test_loop_generation.py`) | High | Guarded |
| F14 | Promote a candidate for a Loop that closes mid-run | Completion happens while a run is in flight; the run fails with a generic error and the output is dropped | Noise in the run list; a person cannot tell "closed" from "provider broke" | Loop completed between capture and promotion | `ensure_writable` refuses; the run is marked `generation_failed` | Run status, but with a message that does not name the cause | observed (`_run` exception branch) | Low | Partly guarded |
| F15 | Keep an approved Ticket's scope stable | A card endpoint edits a Ticket whose scope the approved plan owns | Delivered work no longer matches what was approved; history records a scope that was never delivered | Retrofit endpoint that updates cards without the plan check | `409 plan_change_required` on update/move/transfer; a replacement plan is the only route | Error code and the plan preview endpoint | observed (`cards.update`, `test_approved_ticket_scope_cannot_be_edited_through_a_card_endpoint`) | Critical | Guarded |
| F16 | Reserve human-only actions for humans | An agent token approves a document, confirms a human Ticket or accepts QA | The approval record no longer means a person decided | A scope grant that includes a review scope, or an ordering bug where the scope check runs first | `require_human()` runs before the scope check; `loops:review` is absent from the token scope literal | `403 human_action_required` | observed (`core/context.py`, `schemas/auth.py`, tests) | Critical | Guarded |
| F17 | Issue a least-privilege agent token | The token cannot be limited to Loop work, so an administrator grants `boards:admin` instead | An agent that only needed to draft an analysis can delete boards | The settings form ships a stale copy of the scope list | None; the server accepts the Loop scopes, the client never offers them | None | observed (anti-reverse-engineering analysis, MEDIUM-1) | Medium | Unguarded |
| F18 | Find a completed Loop | Search returns nothing although the record exists | People conclude the Loop is missing and redo the work | A history row inserted without the FTS trigger firing, or an index left behind after a restore | Insert/update/delete triggers on `loop_history_fts`, `LIKE` fallback when FTS5 is unavailable | `meta.engine` on the search response, but no consistency check | observed (`storage/fts.py`, `loop_history.search`) | Medium | Partly guarded |

## Priorities

Priority follows severity first, then how weak the control is. A guarded Critical row is not
downgraded: F2, F3, F4, F15 and F16 are the product's promise and deserve an explicit review even
though they currently hold.

1. **F10, F11** - Critical with no recovery or no control at all. F11 is the only row where a routine
   operational act (a second process, an overlapping container restart) can corrupt a board file
   that the refactor now rebuilds instead of merely extending.
2. **F9, F1, F13, F17** - a guard that is applied per endpoint (F9), an ownership check that depends
   on a healthy registry (F1), a promotion guard that protects data but not people (F13), and a
   privilege decision made by omission (F17).
3. **F2, F3, F4, F5, F6, F7, F8, F15, F16** - Critical or High, currently guarded by a test or a
   constraint. No action beyond keeping the guards alive; these are listed so that a future change
   that removes a test is recognised as removing the control.
4. **F12, F14, F18** - Medium/Low: bounded inconvenience, no data loss.

## Recommended actions

**A1 (F10) - decide and build the data path.** Owner: repository owner (the decision), TBD (the
work). Decide whether any installation holds pre-Loop data; if yes, accept `format_version == 1`
archives in the importer and convert them into a Loop with the old Lists and cards, or ship a
one-off conversion command. Record the decision in `docs/decisions/`. Expected effect: removes the
only row that can lose a customer's data. Tradeoff: the conversion must choose the Loop name, key
prefix and columns, which is a product decision. Residual risk: a converted board still needs a
human to review its first plan. Status: decided on 2026-11-01 - the owner confirmed the product is
unreleased with no installation data, so `docs/decisions/0010-loop-schema-transition-and-development-reset.md`
records the refusal and the release requirement that a conversion path or a documented statement
must replace it before the first public release. The board page now shows the state, a retry and the
export link.

**A2 (F11) - make the single-process rule enforceable.** Acquire an exclusive lock file inside the
data directory at startup (create with `O_EXCL`, containing the PID, released on shutdown) and refuse
to start with an actionable message when it is held. Expected effect: F11 becomes impossible rather
than documented, and an overlapping restart fails loudly instead of damaging a board. Cost: one small
module plus a test that a second process exits non-zero. Residual risk: a stale lock file after a
crash needs a documented override. Status: done on 2026-11-01 - `app/storage/process_lock.py` takes
an OS file lock at startup, `Services.initialize` acquires it before any migration, and
`tests/test_hardening.py::test_a_second_process_cannot_use_the_same_data_directory` proves a second
process is refused and that the directory is usable again afterwards.

**A3 (F17, and the scope catalogue) - one authority for grantable scopes.** Serve the list from the
server (or generate the client constant from the same source) and add a test that the client list
equals the token scope literal. Expected effect: least-privilege tokens become possible, so the
`boards:admin` workaround disappears. Status: done on 2026-11-01 - `/api/v1/meta` serves
`token_scopes` from the token `Scope` literal, the Settings page renders it, and
`tests/test_hardening.py::test_meta_lists_exactly_the_grantable_token_scopes` holds it (also the
first slice of the anti-reverse-engineering plan).

**A4 (F9) - test the read-only rule across every card-scoped endpoint, not per endpoint.** Add one
table-driven test that walks every mutating route which takes a card id (comment, checklist item,
attachment upload/delete, discussion create) against a completed Loop and expects `409 loop_read_only`.
Expected effect: a newly added endpoint that forgets `require_mutable_card` fails the suite.
Status: done on 2026-11-01 - `tests/test_loops.py::test_read_only_guard_covers_every_card_scoped_mutation`
walks sixteen mutating routes (card update/move/archive/confirm, comment create/update/delete,
checklist and item create/update/delete, attachment upload/delete, discussion create) and requires
`409 loop_read_only` from every one.

**A5 (F18) - check the search index against the table.** Add a test that the number of `loop_history`
rows equals the number of `loop_history_fts` rows after a completion and after a legacy import, and
rebuild the index when they differ. Expected effect: a silently empty search becomes a failing test.
Status: done on 2026-11-01 - `ensure_fts` compares `loop_history` with `loop_history_fts_docsize` and
rebuilds on a mismatch, and `tests/test_loops.py::test_history_search_index_recovers_from_drift`
empties the index side and checks that the record is searchable again.

**A6 (F14) - name the cause when a run loses its Loop.** Catch `loop_read_only`/`loop_not_found`
before the generic branch and record `error_code = "loop_closed"` with a message that says the Loop
closed. Expected effect: a person reading the run list can tell an operator decision from a provider
failure. Status: done on 2026-11-01 - such a run now fails with `error_code = loop_closed` and
the Loop's own message; `tests/test_loop_generation.py::test_a_run_that_loses_its_loop_names_the_reason`
cancels the Loop mid-run and asserts the code.

**A7 (F12) - refuse a nonsensical timeout.** Validate `timeout_seconds` on the agent connection at
save time (already bounded above; require > 0) and cap the total wall time of one generation run.
Expected effect: a zero-timeout agent cannot pin a run in `running`. Status: closed without a change on 2026-11-01 -
`schemas/agents.py` already constrains `timeout_seconds` to `ge=1, le=600`, so a zero timeout cannot
be saved; the wall-time cap is left open because the provider timeout already bounds a run.

**A8 (F1) - make the invariant visible.** When a Loop endpoint finds the board database missing, log
it as an integrity event (a Loop row exists without its database) rather than only returning `404`,
so the condition is detectable in operations. Expected effect: F1 stops being silent. Status: done on
2026-11-01 - `BoardDatabaseManager.open` logs a `board_database_missing` integrity event before it
answers `404`.

No action is recommended for F2, F3, F4, F5, F6, F7, F8, F13, F15 and F16 beyond keeping their tests:
the controls are enforced in the schema or by a test that fails if the rule is removed. They remain in
the table so that a future change removing a control is a visible decision.


## Status after this analysis

Applied the same day (2026-11-01) after the owner confirmed the product is unreleased and holds no
production data: A1, A2, A4, A5, A6 and A8 are implemented; A3 was already done; A7 needed no change.
Rows F11 and F18 moved from unguarded/partly guarded to guarded, F7 and F14 keep their behaviour but
now fail loudly instead of silently. Verified with the full backend suite, `ruff`, frontend
`typecheck`/`test`/`build` and the 26 Playwright journeys.

## Assumptions and open questions

**Assumptions made (all marked inferred unless stated):**

- A board holds tens of Loops and hundreds of Tickets, not thousands (observed only for the 20-Loop
  measurement in the ATAM analysis; the production shape is unknown).
- The primary threat to the read-only rule is a *new* endpoint, not an attacker (inferred from the
  fact that the two gaps found today were both retrofits, not adversarial paths).
- Provider endpoints answer within the configured timeout in normal use (unknown; no operational data).

**Open questions.**

1. Does any installation hold pre-Loop data? Decides whether A1 is a release blocker (unknown; only
   the owner can answer).
2. Is running a second process a realistic scenario (containers restarting, a reverse proxy retry, a
   developer starting `uvicorn` twice)? If it is never realistic, A2 is cheap insurance rather than a
   priority; if it is realistic, F11 outranks everything else here.
3. How should a Loop whose board file disappeared be resolved - recreate an empty board, or surface it
   for manual repair? Needed before A8 can do more than log.
4. Who owns the residual-risk decision for F10 if the answer to question 1 is "no installation yet"?
   A written decision makes the residual risk deliberate rather than forgotten.

**Complementary analyses this FMEA does not replace.** A security threat model for the provider call
and the agent-token surface (the anti-reverse-engineering analysis in this session covers the exposure
side, not adversarial sequences), and a fault-tree or dependency analysis for combinations such as
"migration failure during an overlapping restart" (F10 and F11 together), which this row-by-row
method cannot evaluate.
