# Loops: planning, delivery and history

A Loop is one feature or coherent change initiative inside a Board. It owns its Kanban, its
columns, its Tickets and its planning documents. A Board is the container; the Board's SQLite
database is the storage boundary.

```
Board
  Loop: Email verification
    Draft -> Analysis review -> Planning -> RoadMap review -> Ready -> In progress
      -> Awaiting QA -> Completed
    Kanban: Backlog | Todo | In progress | Review | Done
    Phases: planning groups that appear in the RoadMap and on Tickets, never as columns
```

## The five documents

| Slot | Author | Purpose |
| --- | --- | --- |
| `info` | A person only | Notes, requirements, links, constraints and the desired outcome. Agents may read it and never write it. |
| `analysis_ai` | Agent or submitted candidate | Structured technical findings with stable ids, evidence sources, assumptions and options. |
| `analysis` | Rendered by the server | Plain-language decision support derived from `analysis_ai`, with a traceability block. |
| `roadmap_ai` | Agent or submitted candidate | Validated structured plan: numbered Phases, planned Tickets, dependencies and human gates. |
| `roadmap` | Rendered by the server | Human-readable plan whose Phases and Ticket keys are the same as the structured plan. |

Every revision is immutable. The current revision and the approved revision are separate pointers,
and an approval is a recorded human decision bound to exact revision ids and content hashes.

Changing an input invalidates what depended on it: a new Info revision makes the analysis pair and
both RoadMap views stale, the Loop moves to `replanning`, and execution transitions are rejected
with `409 plan_change_required` until a replacement plan is approved.

## Approval boundaries

| Action | Who | Endpoint |
| --- | --- | --- |
| Write Info | Signed-in person | `PUT …/documents/info` |
| Approve or reject analysis | Signed-in person | `POST …/reviews/analysis` |
| Approve or reject RoadMap (publishes Tickets) | Signed-in person | `POST …/reviews/roadmap` |
| Confirm a human-only Ticket | Signed-in person | `POST …/cards/{card_id}/confirm` |
| Accept implementation | Signed-in person | `POST …/completion` |
| Accept QA and finalize | Signed-in person | `POST …/qa/decision` |

Agents may generate candidates, move eligible Tickets, record results and comment. An agent token
is rejected with `403 human_action_required` for every action in the lower half of the table, even
when it holds the scope. WebMCP registers inspection, generation and permitted Ticket tools, never
these decisions.

## Identities

```text
<LoopPrefix><LoopSequence>-<PhasePrefix><PhaseNumber>-<TicketSequence>
AC004-DA02-003
```

Prefixes are the first two normalized alphanumeric characters of the name (`LP`/`PH` when the name
has none, `X` padding for a single character). Keys are allocated transactionally by the server,
frozen after allocation and unique inside the Board; renaming a Loop, Phase or Ticket does not
change an existing key.

## Readiness and human gates

`GET …/readiness` returns every Phase with its state (`pending`, `active`, `complete`) and every
planned Ticket with `ready`, `blockers`, `human_action_required` and `downstream_phase_numbers`.

A Phase is entered when its prerequisite Phases are complete, its prerequisite Tickets are
completed and its own pre-phase gates are confirmed. A gate is available as soon as its own
prerequisites are met and never waits for the Phase it protects, so the common shape

```text
Phase 2 (complete) -> human gate -> Phase 6
Phase 3, 4, 5 keep running in parallel
```

works without a deadlock. Moving a Ticket into a column called `Done` completes nothing:
`completed_at` is only set by an explicit completion that passes the same readiness rules.

## QA handover

Accepting implementation records the decision and asks whether QA was performed. If it passed
outside Tralala, a human attestation is captured and the Loop is finalized in the same transaction.
Otherwise the Loop moves to `awaiting_qa` and one QA Task is created (or reused) with two views
built from the same scenario ids: an agent view with setup, steps and evidence, and a human view of
short numbered steps.

Scenario outcomes are `passed`, `failed`, `blocked`, `not_run` or `not_applicable`. A failed,
blocked or not-run scenario prevents acceptance; `not_applicable` needs an explicit human waiver.
Finalization stores an immutable snapshot and returns the existing record on every retry.

## History

Completed Loops live in `loop_history` inside their Board database: envelope, documents, plan,
delivery dispositions, human decisions, QA evidence, generation provenance (agent, model and a
`system_prompt_sha256` rather than the prompt itself) and an asset manifest,
plus a content hash. `GET /boards/{board_id}/history` searches a derived text projection with FTS5
(or `LIKE` when FTS5 is unavailable).

Legacy material is stored with `source_kind = imported_legacy`, `conformance = legacy_unvalidated`
and its original bytes. It is never converted into an active Loop, never creates Tickets and never
counts as a verified QA result; every view labels it
`Imported legacy reference - may not follow the current standard`.

## Discussions and search

A discussion and every search result keep the Loop context of the Ticket they point at. A thread
carries `loop_id`, `loop_key`, `loop_name` and `ticket_key`, and opens
`/boards/{board_id}/loops/{loop_id}?card={card_id}`, so the Loop page shows the Ticket that the
conversation is about instead of an inferred default Loop.

## Clean schema transition

A database that predates Loop ownership cannot be converted in place; the reasoning and the
release requirement that follows from it are recorded in
[decisions/0010](decisions/0010-loop-schema-transition-and-development-reset.md). Startup stops with
an actionable message, the board is marked `migration_failed`, and the board page offers a retry and
the export archive. Reset development data explicitly:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.dev_reset            # lists what would be removed
..\.venv\Scripts\python.exe -m app.dev_reset --confirm  # erases it
```

The command names the data directory, keeps the session secret and is never run automatically.
