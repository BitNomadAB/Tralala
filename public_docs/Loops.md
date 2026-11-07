# Loops: planning, delivery and history

A Loop is one feature or coherent change initiative inside a Board. It owns its Kanban, its
columns, its Tickets and its planning documents. A Board is the container; the Board's SQLite
database is the storage boundary.

```text
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
| `info` | A person, or their worker through `write_info` while the Loop is `draft` or `analysis_review` | Notes, requirements, links, constraints and the desired outcome. Once planning has started only a person edits it, and a new revision makes the approvals built on it stale. |
| `analysis_ai` | Tralala's analysis agent (`run_analysis`), or your worker through the same candidate route (`write_analysis`, `POST …/candidates`) | Structured technical findings with stable ids, evidence sources, assumptions and options. |
| `analysis` | A connected worker, the Loop's analysis agent, or rendered by the server | A decision brief for the person who decides: can it be done, what stands in the way, for and against, what to decide, a recommendation. Written from `analysis_ai`; no ids, paths or code. |
| `roadmap_ai` | Tralala's RoadMap agent (`run_roadmap`), or your worker through the same candidate route (`write_roadmap`) | Validated structured plan: numbered Phases, planned Tickets, dependencies and human gates. |
| `roadmap` | A connected worker, the Loop's RoadMap agent, or rendered by the server | A brief of the plan: what happens in each Phase and when it is done, your own part, what could block it. Written from `roadmap_ai`. |

Every revision is immutable. The current revision and the approved revision are separate pointers,
and an approval is a recorded human decision bound to exact revision ids and content hashes. A
candidate from a worker is not a second kind of document: it has the same schema, validation,
human view and review as one Tralala's agent writes, and nobody approves it but a person.

The Loop is the plan. Nothing a worker plans or logs is a file in a repository: the intent is the
Info, the plan is the RoadMap and its Tickets, progress is a comment on a Ticket, what belongs to
the Loop as a whole is a note, and work found along the way is a Ticket outside the plan.

A person and a model read differently, so the analysis and the RoadMap each have two views: the
technical one (`analysis_ai`, `roadmap_ai`), complete and unchanged, and a short **brief** for the
person who decides. The analysis brief answers what that person asks: can it be done (`yes`,
`yes_with_conditions`, `no` or `unclear`, with one sentence why), the highlights in two or three
sentences, what stands in the way (business, technical, security, legal, people and time; only
obstacles that exist), up to five points for and five against, what a person must decide (as
questions) and a recommendation. The RoadMap brief says what happens in each Phase and when it is
done, the reader's own part (every Ticket a person must do) and what could block the plan. The
brief is the revision's payload, and its Markdown rendering is the revision's text.

Each item of a brief names the findings it rests on (`finding_ids`), or the Phases and Tickets
(`phase_ids`, `ticket_ids`); those ids carry the traceability and are never shown in the text.
Every brief is checked before it is stored: together its items name every finding of category risk,
blocker, legal, security, question or decision (a RoadMap brief: every Phase exactly once, every
Ticket a person must do), it names no id the technical revision lacks, and its text holds no
finding id (`F01`, `[F01]`), other id, file path or code. A refusal is `422 brief_rejected` with
every problem named by its field.

Who writes the brief: a connected worker, which may hold its organisation's own sources, policies
and decisions, gives it as `brief` with `write_analysis` or `write_roadmap`, or later with
`write_brief`; then no board agent is asked. Otherwise each new `analysis_ai` or `roadmap_ai` is
first rendered from its structure (provenance `rendered`), and the Loop's analysis or RoadMap agent
writes the brief in a run of its own (purpose `analysis_human` or `roadmap_human`): it gets the Info
and the technical revision, no repository, and answers the brief's JSON schema. A brief that breaks
a rule is sent back once with the problems named; if it still breaks one, the run fails with
`brief_rejected` and the rendered view stays. A board without an enabled agent keeps the rendered
view. The scope cannot be approved while that run is queued or running
(`409 generation_in_progress`); an approved scope is not rewritten by a token until a person
requests changes or resets it. A person may rewrite a brief at any time, and writing a brief never
approves it: a new brief needs a new review.

The Analysis and RoadMap tabs switch between **For people** and **For AI**. For people shows the
brief's sections, each item with a *Where does this come from?* disclosure listing the findings (or
the Phases and Tickets) by title from the technical revision, and a label: *Written by* its author,
or *Rendered from the structure*. A revision written before briefs existed still shows as Markdown,
labelled *Earlier format*. **Rewrite for people** starts the board agent's run again for the current
technical revision; when it cannot, it says why (*Approved: request changes or reset to rewrite*,
*Writing for people...* while a run is on). While one runs, the tab says so and approval waits for
it.

Once the plan executes (`ready`, `in_progress`, `awaiting_qa`), a person or a worker may still add
a Ticket *outside the plan*: it is keyed `<LoopKey>-UNP-<nnn>`, carries an **Unplanned** badge, is
listed under **Outside the plan** in the RoadMap tab and in readiness (`unplanned`), and never blocks
a Phase or the Loop's completion; accepting the implementation names the ones still open. A Loop
whose plan is not executing refuses a new Ticket with
`409 plan_change_required`; a Loop without a plan yet takes one without a key.

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

## Who does the work, and a Ticket's state

Tralala never does the work and never looks as if it does. Its own agents keep the board in order
and write decision support (an analysis, a RoadMap, a discussion); a person always owns a Ticket,
and a coding agent is a tool in that person's session, not a system that picks Tickets and moves
on by itself. So no field, label, count or text names an agent as the one who does a Ticket.

Three questions stay apart, and a fourth answer is computed from them:

- **Where the work is done** (`workplace`): `codebase` (in a repository, so it can be taken in a
  coding session), `outside` (another system or the world outside) or `unknown`, which every
  Ticket created before the field existed reads.
- **What it waits for** (`waiting_for`): `nothing`, `decision`, `information`, `access` (a system,
  key, account, setting or machine) or `third_party` (a supplier, a customer, a lawyer, ...), with
  a short reason and who set it when. Anyone who may edit the Ticket sets a wait; the person who
  answers clears it, and a Ticket that waits is not completed (`409 ticket_waiting`).
- **Its area**: labels. A board created without a template starts with Development, Architecture,
  UX, QA, Security, Operations, Documentation, Data, Product, Business, Economy, Legal, Support,
  Communication and Research (`TRALALA_DEFAULT_LABELS`); existing boards keep theirs.
- **Its state**, never stored or set by hand: `needs_input` when it waits for a decision,
  information or access; `blocked` when an earlier Ticket, Phase or pre-Phase gate is unfinished or
  it waits for a third party; `ready` otherwise. `needs_input` wins over `blocked`, because a person
  can answer now. A completed Ticket has none.

`human_action_required` stays apart: it says the task itself is a person's, and such a Ticket can
be ready. Two lists follow: work for a coding session (`workplace` codebase, `state` ready, not a
person's task), and what needs a person (`needs_person`: needs input, or ready and a person's task).
The RoadMap gives each planned Ticket its starting workplace, wait and labels; the plan describes,
it never assigns.

In the Ticket dialog, **Where and what it waits for** shows the state, sets **Where the work is
done** and marks a wait (**Mark as waiting**: what it waits for and why). A worker marks one with
`set_ticket_wait` when it cannot go on without an answer. **Clear the wait** is a person's: a token
can neither clear nor replace a wait (`403 human_action_required`), and **Mark complete** stays off
while one is open. The Kanban card shows *Needs input* or *Blocked*.

## Approval boundaries

| Action | Who | Endpoint |
| --- | --- | --- |
| Write Info | Signed-in person, or a worker token while the Loop is `draft` / `analysis_review` | `PUT …/documents/info` |
| Approve or reject analysis | Signed-in person | `POST …/reviews/analysis` |
| Approve or reject RoadMap (publishes Tickets) | Signed-in person | `POST …/reviews/roadmap` |
| Reset a scope: clears the documents and any approval behind them | Signed-in person | `POST …/reviews/{scope}/reset` |
| Confirm a human-only Ticket | Signed-in person | `POST …/cards/{card_id}/confirm` |
| Clear (or replace) a Ticket's wait | Signed-in person | `POST …/cards/{card_id}/wait/clear` |
| Accept implementation | Signed-in person | `POST …/completion` |
| Accept QA and finalize | Signed-in person | `POST …/qa/decision` |

Info is the intent a person and their worker agree on, so the worker that agreed it may write it —
but only while the Loop is still speculative (`draft` or `analysis_review`). Once planning has
started a new Info revision would invalidate approvals, so the edit returns
`403 human_action_required` for a token and stays a person's decision.

A worker token may write the Info while the Loop is speculative, hand in or ask for candidates and
briefs, set a wait on a Ticket that waits for nothing, move and complete eligible Tickets, add
Tickets outside the plan, write notes, record QA results and comment. It is rejected with
`403 human_action_required` for every other action in the table, even when it holds the scope. WebMCP registers inspection, generation and permitted Ticket tools, never these decisions.

## The agent and its repository context

Generation runs on a chosen agent, and the agent's role prompt is the first part of the prompt
(followed by the purpose contract and the JSON schema); the whole composed text is what the run
snapshots. The built-in `analytics_agent` role is written for turning Info into a structured
analysis and for investigating a codebase.

The schema's field order is the order the model writes in, so it puts evidence before judgement:
an analysis lists its findings before its recommendation. When the agent's connection test found
that its provider takes a JSON schema as the answer's format (`supports_json_schema`), the run also
sends the schema that way and the provider keeps the answer to it; other providers get the schema in
the prompt only, and an answer that does not validate is sent back for repair as before.

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
**Settings -> Repositories** (`repository_ids`), read from GitHub or from a mirror of any allowed
HTTPS Git host ([Repositories.md](Repositories.md)). A repository can serve several boards, and a
board can list several. The token behind each repository is read-only and sealed, and an agent sees
only the repositories of the boards it serves. An agent whose connection test found tool calling
reads that code itself during an analysis or RoadMap run; any other agent gets a fixed snapshot
([How a run reads the code](Repositories.md#how-a-run-reads-the-code)).

A run works in the background, so the document dialog shows what it is doing in a second panel
beside the dialog (inline at the top of the dialog on a narrow screen): the run's steps in plain
words, grouped by stage — *Reading the Loop's documents*, *Reading the repository*, *Writing the
analysis* (or *RoadMap*), *Checking the answer* and *Saving*. The list grows while the run works:
which documents it read, which repository it opened or which fixed selection it sent, every file the
model read and every search it made, the model's own notes beside them, each repair round ("The answer
broke a rule: … — asked the model to fix it") and every limit the run reached. It stays on the run
afterwards, so a person can read how an analysis was made. A stage is only ticked when it produced
what its name promises: the repository stage is *skipped* when the board links no enabled repository
("no code was read") and *warned* when a limit applied. The same panel is where a failure appears: the
stage that failed is marked, the last step says what was not saved and why, the provider's own answer
is shown as JSON, and the panel stays on screen until it is dismissed. *Generate* is locked and glows
for the duration, so the same document cannot be started twice by accident. The red *Reset* button at the bottom-left corner clears the
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
planned Ticket with `ready`, `blockers`, `human_action_required`, `downstream_phase_numbers`,
`workplace`, `waiting_for` and `state`.

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

## Notes

A Loop keeps a log of notes for what belongs to the Loop and to no single Ticket: the
baseline the work started from, the checks that passed, a merge or a deploy, what is still
open. A person writes one in the Loop page's **Notes** panel and a worker with `write_note`;
`read_loop` carries the newest five, each cut to 500 characters, and `read_notes` pages through
the rest. Notes are
appended and never edited, a completed Loop takes none, and finalizing a Loop copies every
note into its history snapshot, where the history search finds them.

## History

Completed Loops live in `loop_history` inside their Board database: envelope, documents, plan,
delivery dispositions, human decisions, QA evidence, generation provenance (agent, model and a
`system_prompt_sha256` rather than the prompt itself) and an asset manifest,
plus a content hash. `GET /boards/{board_id}/history` searches a derived text projection with FTS5
(or `LIKE` when FTS5 is unavailable).

A completed Loop is read-only: its documents, plan, Tickets' fields, checklists, attachments and QA
take no writes (`409 loop_read_only`), and a Ticket in it is not completed again. The one exception
is comments on its Tickets. As long as the board exists and is not archived, a person or a worker
may still comment on any of its Tickets, done or not, and edit or delete a comment by the usual
rules, so a later Loop can point back at the work it replaced ("superseded by L-7"). The same holds
for a cancelled or archived Loop; an archived board refuses the comment (`409 board_archived`).

The history snapshot is the record of the Loop as it was completed: a later comment never changes
it or its content hash, and `GET /boards/{board_id}/history/{history_id}` answers the comments as
they were at completion. The live Ticket shows every comment, and one written (or last edited) after the Loop was completed carries
`after_loop_completed: true`, which the Ticket dialog shows as "written after the Loop was
completed".

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
