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

Withdrawing an approval is the heavier action, and the dialog offers it as the red *Reset* button in
the bottom-left corner of the Analysis and RoadMap tabs — available for a draft as well as for an
approved document. It is not a rejection: a rejection keeps the text and asks for changes, while a
reset clears it. Any approval behind the text is superseded and kept as history, the scope's documents
are replaced by an empty draft, and every approval that depended on them is cleared — so a reset
analysis has to be generated again before a RoadMap can be. Because the text is retired rather than
edited, the button asks for confirmation first.

## Approval boundaries

| Action | Who | Endpoint |
| --- | --- | --- |
| Write Info | Signed-in person, or a worker token while the Loop is `draft` / `analysis_review` | `PUT …/documents/info` |
| Approve or reject analysis | Signed-in person | `POST …/reviews/analysis` |
| Approve or reject RoadMap (publishes Tickets) | Signed-in person | `POST …/reviews/roadmap` |
| Reset a scope: clears the documents and any approval behind them | Signed-in person | `POST …/reviews/{scope}/reset` |
| Confirm a human-only Ticket | Signed-in person | `POST …/cards/{card_id}/confirm` |
| Accept implementation | Signed-in person | `POST …/completion` |
| Accept QA and finalize | Signed-in person | `POST …/qa/decision` |

Info is the intent a person and their worker agree on, so the worker that agreed it may write it —
but only while the Loop is still speculative (`draft` or `analysis_review`). Once planning has
started a new Info revision would invalidate approvals, so the edit returns
`403 human_action_required` for a token and stays a person's decision.

Agents may generate candidates, move eligible Tickets, record results and comment. An agent token
is rejected with `403 human_action_required` for every other action in the table, even when it holds
the scope. WebMCP registers inspection, generation and permitted Ticket tools, never these decisions.

## The agent and its repository context

Generation runs on a chosen agent, and the agent's role prompt is the first part of the prompt
(followed by the purpose contract and the JSON schema); the whole composed text is what the run
snapshots. The built-in `analytics_agent` role is written for turning Info into a structured
analysis and for investigating a codebase.

Which agents work on a Loop is decided one level up, on the **Board**: *New board* and *Edit board*
list every agent as a checkbox (`agent_ids`), and the Loop's *Agent* dropdown offers those agents
only. A board that lists none keeps the old behaviour — any enabled OpenAI-compatible agent — so a
board created before this selection existed still generates. The server enforces the same rule: a
run that asks for an agent the board does not list is rejected with `422 agent_not_on_board`, and the
default pick is the first board agent by name.

Inside that set a Loop can remember one agent per purpose (**Loop agents** on the Loop header):
analysis, RoadMap and QA. The stored choice only fills in the default of the next run and shows as
`Default (<agent name>)`; the run dialog can still deviate for a single run, and a stored agent that
is no longer available falls back to the board default.

Which code that agent may look at is decided on the same dialog: the repositories from
**Settings -> GitHub repositories** (`repository_ids`). A repository can serve several boards, and a
board can list several. The token behind each repository is read-only and sealed, and an agent sees
only the repositories of the boards it serves.

A run is one background call, so the document dialog shows the step it is on — *Reading Info data*,
*Analysing repository*, *Generating analysis* (or *RoadMap*) — in a second panel beside the dialog
(inline at the top of the dialog on a narrow screen). A step is only marked done when it produced what
its name promises: the repository step is marked *skipped* when the board links no enabled repository
("no code was sent to the model") and *warned* when a repository could not be read, while the line
under it names the commit and file count it did get — `acme/app @ abc123de, 34 files`,
`acme/app · unavailable (unauthorized)`, or *no enabled repository is linked to this board*. A green
tick there used to claim the model had seen code it never received. The same panel is where a failure
appears: the step that failed is marked, carries the provider's own answer as JSON, and stays on
screen until it is dismissed. *Generate* is locked and glows for the duration, so the same document
cannot be started twice by accident. The red *Reset* button at the bottom-left corner clears the
analysis or the RoadMap — an approved one as well as a draft — and asks first, because the text is
retired rather than edited.

## Board profiles and organisation profiles

Role templates carry a scope. **Board profiles** answer inside one board and are what a board selects
(`agent_ids`) and a Loop may run on. **Organisation profiles** work across the whole installation
because their job is the overview no single board can give:

| Profile | Job |
| --- | --- |
| Coordinator | Overview of every board and Loop, moderation of agents and tasks, a recommendation of which profile should answer a discussion thread |
| Architect | The whole set of registered repositories: each one's technology and purpose, how they interact, and what a change across boards actually touches |

Neither is offered as a board agent: the selection in *Edit board* lists board profiles only, and the
server refuses the rest with `422 agent_scope_organisation`. Their input is the registry itself — the
board list, the Loop overviews and the whole repository list — which is also why they live in
`registry.sqlite` next to the roles and agents they reason about. The Architect expects one read-only
token that reaches every repository; the token guide in the repository dialog describes that variant.

Every role prompt describes a job, not one board or installation. An agent learns what it is working on
from the request that asks it: a generation run states the board and the Loop, and a discussion round or
a mention states `Loop: <name> (<key>)`, `Ticket: <title>` and `Ticket id: <uuid> (key: …)` on top of the
thread. The shared discussion preamble tells the agent to use those identifiers and never to invent one
it was not given.

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

A database that predates Loop ownership cannot be converted in place. Startup stops with an
actionable message, the board is marked `migration_failed`, and the board page offers a retry and
the export archive. Reset development data explicitly:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.dev_reset            # lists what would be removed
..\.venv\Scripts\python.exe -m app.dev_reset --confirm  # erases it
```

The command names the data directory, keeps the session secret and is never run automatically.
