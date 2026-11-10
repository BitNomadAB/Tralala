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

## The Loop page

The Loop page shows the Loop's name as its title, its key and stage under it with how many Tickets
are done, and one line on what the Loop waits for ("Waits for you to approve the analysis", "2
Tickets ready to start"). Beside it sits at most one primary button, the person's next decision:
**Approve analysis** or **Approve RoadMap** opens that document on the Plan tab, because an
approval binds to the revisions on screen and the header approves nothing unseen; **Accept work**
and **Finalize Loop** open the completion dialog. Everything else is in the quiet **Loop actions**
menu: **Edit Loop**, **Loop agents**, **Finalize Loop** (when it is not the primary button),
**Save columns as template**, **Board activity**, **Export board** and **Cancel Loop**. A completed
Loop greys out what would change it ("The Loop is read-only").

Three tabs follow, each kept in the address (`?tab=kanban`, `?tab=plan`, `?tab=notes`), so a link
opens the same view:

- **Kanban**: the Loop's columns and their Tickets. A column's heading is its name with its count;
  **Rename column** and **Archive column** sit in its quiet menu, and **Add card** and **Add
  column** are quiet controls at the end.
- **Plan**: **Planning documents** (**Info**, **Analysis**, **RoadMap**; `?doc=` names the one
  shown, by default the one the stage is about). The plan's Tickets are on the **Kanban**; the
  Loop's header names the human Tickets that hold a Phase up, and a Ticket shows what it waits for.
- **Notes**: the Loop's log of notes ([Notes](#notes)).

`?card=<card_id>` opens a Ticket over any tab ([The Ticket view](#the-ticket-view)).

A Ticket on the Kanban shows the first line of its face: the title in two lines at most, its plain
summary muted under it, and a bottom row with the key, *Needs input* or *Blocked* only when it
waits (the reason on hover), *Needs a person* for a person's task, *Unplanned* for a Ticket outside
the plan, *QA*, the priority and the due date when set (red when overdue), *done* with a check once
it is completed, and the owner's initials on the right. Labels, checklists and comment counts are
in the Ticket, not on the card.

## The five documents

| Slot | Author | Purpose |
| --- | --- | --- |
| `info` | A person, or their worker through `write_info` while the Loop is `draft` or `analysis_review` | Notes, requirements, links, constraints and the desired outcome. Once planning has started only a person edits it, and a new revision makes the approvals built on it stale. |
| `analysis_ai` | Tralala's analysis agent (`run_analysis`), or your worker through the same candidate route (`write_analysis`, `POST …/candidates`) | Structured technical findings with stable ids, evidence sources, assumptions and options. |
| `analysis` | A connected worker, the Loop's analysis agent, or rendered by the server | A decision brief for the person who decides: can it be done, what stands in the way, for and against, what to decide, a recommendation. Written from `analysis_ai`; no ids, paths or code. |
| `roadmap_ai` | Tralala's RoadMap agent (`run_roadmap`), or your worker through the same candidate route (`write_roadmap`) | Validated structured plan: numbered Phases, planned Tickets, dependencies and human gates. |
| `roadmap` | A connected worker, the Loop's RoadMap agent, or rendered by the server | The plan's goal in one line, what is true when it is done; the review shows the Phases and Tickets under it and counts them. Written from `roadmap_ai`. |

Every revision is immutable. The current revision and the approved revision are separate pointers,
and an approval is a recorded human decision bound to exact revision ids and content hashes. A
candidate from a worker is not a second kind of document: it has the same schema, validation,
human view and review as one Tralala's agent writes, and nobody approves it but a person.

The Loop is the plan. Nothing a worker plans or logs is a file in a repository: the intent is the
Info, the plan is the RoadMap and its Tickets, progress is a comment on a Ticket, what belongs to
the Loop as a whole is a note, and work found along the way is a Ticket outside the plan.

A person and a model read differently, so the analysis and the RoadMap each have two views: the
technical one (`analysis_ai`, `roadmap_ai`), complete and unchanged, and a short **brief** for the
person who decides. The analysis brief is a sign, read in the order a decision is made:

| Part | Field | Limit |
| --- | --- | --- |
| In short | `verdict` (`yes`, `yes_with_conditions`, `no` or `unclear`) and `verdict_line` | the line in at most 20 words, on one line |
| Why | `obstacles`: business, technical, security, legal, people and time; only obstacles that exist | at most 3 |
| What you decide | `decisions`: each a question to the person | at most 5, each on one line |
| How big | `size`: `small`, `medium` or `large`, and why | one sentence |
| For and against | `pros` and `cons` | at most 3 each |

Every item holds at most 140 characters. The brief also keeps a sentence why (`verdict_reason`),
the highlights and a recommendation, which the sign does not show. A question reads like "Do we
keep the addresses of people who never confirm, and if so, for how long?". The RoadMap brief is
its goal alone (`goal`): what is true when the plan is done, in one line of at most 20 words. The
review shows the Phases and their Tickets under it and the number of Tickets beside it, so the brief
repeats none of them; a RoadMap brief written before the goal shows only its summary. The brief is
the revision's payload, and its Markdown rendering is the revision's text.

Each item of an analysis brief names the findings it rests on (`finding_ids`); those ids carry the
traceability and are never shown in the text. Every brief is checked before it is stored: together
the items of an analysis brief name every finding of category risk, blocker, legal, security,
question or decision and no id the technical analysis lacks, a RoadMap brief's goal is one line of
at most 20 words, and the text of either holds no finding id (`F01`, `[F01]`), other id, file path
or code. A new analysis brief is held to the sign
first: one that breaks a limit is refused with `422 brief_invalid`, one message per field and rule
("Brief, obstacles: 4 items, at most 3."), and the content problems of the same brief follow them,
so one round fixes everything. A brief that keeps the sign but breaks coverage, an id or the
wording is `422 brief_rejected` with every problem named by its field. A brief stored before the
sign existed is read as it is and never checked again.

Who writes the brief: a connected worker, which may hold its organisation's own sources, policies
and decisions, gives it as `brief` with `write_analysis` or `write_roadmap`, or later with
`write_brief`; then no board agent is asked. Otherwise each new `analysis_ai` or `roadmap_ai` is
first rendered from its structure (provenance `rendered`), and the Loop's analysis or RoadMap agent
writes the brief in a run of its own (purpose `analysis_human` or `roadmap_human`): it gets the Info
and the technical revision, no repository, and answers the brief's JSON schema, which shows the size
and the verdict line as required. An analysis brief's request ends with the ids of the findings its
items must name, so the model checks a list instead of working it out. A brief that breaks
a rule is sent back once with the problems named; if it still breaks one, the run fails with
`brief_invalid` (the sign) or `brief_rejected` and the rendered view stays. A board without an enabled agent keeps the rendered
view. The scope cannot be approved while that run is queued or running
(`409 generation_in_progress`); an approved scope is not rewritten by a token until a person
requests changes or resets it. A person may rewrite a brief at any time, and writing a brief never
approves it: a new brief needs a new review.

On the Plan tab, **Analysis** switches between **For people** (the brief) and **For AI** (the
technical analysis). The brief has its own **For you | Raw text**. For you is the sign, in order:
**In short** (the verdict and its line), **Why** (each obstacle with its level), **What you
decide** (each question, with the findings it rests on as small chips that name them), **How big**
and **For and against**. Raw text holds the findings as they were written and the technical
analysis as JSON. The brief ends with **Approve analysis** and the line naming what it approves
("Approves revision 3 of this analysis, written from technical revision 2."); **Request changes**
sits under it with an optional feedback field.

**RoadMap** is reviewed the way a Ticket is read, so its switch is **For you | Raw text** instead
of For people and For AI. For you is **In short** (the brief's goal and the number of Tickets; the
plan's own summary when nobody wrote a brief) and one section per Phase (*Phase 2 · Sign-in*, its Ticket count and its objective) with
a row per Ticket: the title, its summary, the key, *Needs a person*, where the work is done and
what it waits for. A row opens to the Ticket's face (the steps, **Why it is needed**, **If we skip
it**, **Pro and con**), read only; a Ticket written without a face shows its objective, with its
acceptance criteria behind **More**. Raw text is the technical RoadMap with the plan as JSON. The
decision is **Approve RoadMap · 3 Tickets**, with the count of what it publishes and the line
"Revision 2 of 7 Nov 2026. Approving publishes its 3 Tickets to the Kanban." under it, beside
**Request changes**.

**Regenerate RoadMap**, beside them, writes the RoadMap again from the approved analysis, with the
text in the feedback field as the run's instructions ("One person does the work; there is no legal
team."), also after the RoadMap was approved and its Tickets published. The approved plan stays in
force until the new RoadMap is approved; until then its revision shows *Needs a new review*. When
the new plan is published, every Ticket of the earlier plan that it leaves out and nobody has
touched (never moved or edited, nobody assigned, not completed, and no comment, checklist,
attachment, note or discussion on it) is removed from the Kanban. A Ticket somebody worked on stays,
and the Loop's activity names which were removed and which were kept. Ticket keys are never used
twice, so the new plan's keys go on from the old ones.

A document carries a label: *Written by* its author, or *Rendered from the structure*. A revision
written before briefs existed still shows as Markdown, labelled *Earlier format*. **Rewrite for
people** starts the board agent's run again for
the current technical revision; when it cannot, it says why (*Approved: request changes or reset to
rewrite*, *Writing for people...* while a run is on). While one runs, the tab says so and approval
waits for it.

Once the plan executes (`ready`, `in_progress`, `awaiting_qa`), a person or a worker may still add
a Ticket *outside the plan*: it is keyed `<LoopKey>-UNP-<nnn>`, carries an **Unplanned** badge, is
listed in readiness (`unplanned`), and never blocks
a Phase or the Loop's completion; accepting the implementation names the ones still open. A Loop
whose plan is not executing refuses a new Ticket with
`409 plan_change_required`; a Loop without a plan yet takes one without a key.

Changing an input invalidates what depended on it: a new Info revision makes the analysis pair and
both RoadMap views stale, the Loop moves to `replanning`, and execution transitions are rejected
with `409 plan_change_required` until a replacement plan is approved.

Withdrawing an approval is the heavier action: **Reset analysis** and **Reset RoadMap** are the
red buttons beside each review, on the left of its decision. Both are available for a draft as well as for an approved document. A
reset is not a rejection: a rejection keeps the text and asks for changes, while a reset clears it.
Any approval behind the text is superseded and kept as history, the scope's documents are replaced
by an empty draft, and every approval that depended on them is cleared — so a reset analysis has
to be generated again before a RoadMap can be. Because the text is retired rather than edited, a
reset asks for confirmation first (**Reset and clear**).

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

In the Ticket view the rail shows the state under the column (*Ready*, *Needs input* or *Blocked*,
with what holds it up), and **Work is done** under Details says where the work is done (*In the
code base*, *Outside the code base*, *Not decided*). **Mark as waiting** in the actions row, or
*Mark as waiting…* in the rail, asks what it waits for (*A decision*, *Information*, *Access*, *A
third party*) and why (required, at most 500 characters). A worker marks one with
`set_ticket_wait` when it cannot go on without an answer. **Clear the wait** is a person's: a token
can neither clear nor replace a wait (`403 human_action_required`), and **Mark complete** stays off
while one is open ("Clear the wait first"). The Kanban card shows *Needs input* or *Blocked*.

## A Ticket's face for people

Every Ticket a RoadMap plans ends with its **face**: what a person reads of it by default. It is a
fixed template, the same for every writer (a RoadMap handed in by a worker, one written by the
Loop's RoadMap agent, a worker's Ticket outside the plan and a person's edit):

| Field | What it says | Limit |
| --- | --- | --- |
| `summary` | what the Ticket means | at most 20 words |
| `why` | why it is needed | at most 3 sentences |
| `if_skipped` | what happens if we skip it | at most 3 sentences |
| `pros` | for | at most 3 points |
| `cons` | against | at most 3 points |
| `steps` | what will be done, concretely | 1 to 5 steps |

Every field is plain text for a person: no code fence, code span, file path, file name, UUID, id or
code symbol (`snake_case`, `camelCase`, `()`, `::`, `->`). A step names what changes for the person,
never where in the code: "Under each open question, put an answer field and a Go on without my
answer button." keeps the template, "Add QuestionList to BriefView.tsx." breaks it. A Ticket that
needs more than five steps is split into another Ticket when the RoadMap is written. Files, tables,
routes and symbols belong in the acceptance criteria and the evidence, which stay text for the AI.

The server holds every writer to the template and counts words and sentences itself; nothing
judges the text with a model. A face that breaks it is refused with `422 face_invalid`, one message
per Ticket, field and rule ("Ticket t3, steps: 7 items, at most 5. Split the Ticket into two."). The
Loop's RoadMap agent is sent the messages back and repairs its answer; a worker fixes its payload
and hands the RoadMap in again. Approving the RoadMap publishes each Ticket with its face.

A person changes a face in the Ticket (**Edit** beside *What will be done*): the fields with live
counters, saved whole with the Ticket's version, each refusal shown under its field. A token never
changes a face (`403 human_action_required`); it writes a new RoadMap revision instead. A Ticket
written before the face existed keeps its description, marked "Written before Tickets had a plain
summary.", until someone writes one.

## The Ticket view

A Ticket opens as a dialog over the Kanban (`?card=`), and **Open as page** shows the same view on
a page of its own, `/boards/{board_id}/loops/{loop_id}/tickets/{card_id}`, with the breadcrumb
Board / Loop / Phase / key and **Back to the board**. Nothing is a form until you click it.

- **The head**: the key with **Copy key**, the Phase, the title as a heading (a click edits it) and
  the summary under it. The actions: **Start work** while the Ticket sits in the first column (it
  makes you the owner when nobody owns it and moves it to the next column) or **Mark complete**
  (off, with the reason on hover, while it waits or earlier work comes first), then **Mark as
  waiting**, **Comment**, **Add file**, and **More actions** (**Copy link**, **Ask the agents**,
  **Mark incomplete** for a completed Ticket, **Archive**).
- **What will be done**, with **For you | Raw text**. For you is the face: the steps as a numbered
  list ("3 of 5"; at five, the line says a Ticket that needs more is split), then sections that
  expand: **Why it is needed**, **If we skip it**, **Pro and con** ("2 for, 1 against", in two
  columns) and **Your notes**. Raw text is everything the agent wrote, as it is: **Summary for
  AI**, **Description** (the Markdown source; **Edit description** opens it with Write and Preview),
  **Accepted when**, **Evidence** and **Plan entry** (the RoadMap's entry for the Ticket). The
  choice lasts while the view is open.
- **Files**: a drop zone and **Add file**; [API.md](API.md#attachments) lists the kinds a Ticket
  takes.
- **Activity**, with the tabs **Comments** (Ctrl+Enter sends), **Discussions** with their count
  ([Ask the agents](#ask-the-agents)), **History** (what happened, one row each) and **Work** (the
  summary and the completion with its evidence that a coding session recorded). **Ask the agents**
  sits in Activity's head.
- **The rail**: the column as a menu, the state with *Mark as waiting…* or the wait with **Clear
  the wait**, **Confirm human action** for a Ticket only a person can do, **Details** (Owner,
  Phase, Work is done, Depends on, Priority, Due, Labels, Created; each value turns into its control
  on a click and saves itself) and **More** (Checklists, Copy link, Archive).

When someone else changed the Ticket since it was opened, a write answers "Someone changed this
Ticket. Reload to see it." A completed, cancelled or archived Loop shows the view read only, with
Comment and Copy link; its Discussions tab still lists what was discussed, without Ask the agents.

### Your notes

**Your notes** is what people wrote on the Ticket in their own words: each note with its author and
date, a field to add one ("Written by you, never by an agent."), and Edit and Delete on the notes you
wrote. A note holds up to 4 000 characters. Your coding agent reads them: `read_ticket` carries them
as `person_notes`, apart from the plan, and no key can write, edit or delete one. Only the author
changes a note, an edit names the version it read, and a completed, cancelled or archived Loop, like
an archived board, takes no note.

## Ask the agents

A discussion is a question to the board's agents about one Ticket. It belongs to that Ticket and
opens inside it. The agents advise; a person decides, and nothing a discussion says changes the
Ticket.

### Asking

**Ask the agents** sits in the head of a Ticket's **Activity** and under its **More actions**. The
dialog asks one thing and one choice: the **Question**, and the **Agents** that can answer on the
board, each with its role, all chosen to begin with (at most 12). **Ask** opens the discussion at
once with "Agents are answering · round 1 of 3" while the chosen agents answer their first round
in the background; the sign and the rows fill in as they answer. If the round cannot start, the discussion opens anyway and says "The agents
could not start answering". On a board where no agent can answer the dialog says "No agent can
answer on this board. Add one in Settings → Agents and select it on the board.", offers **Open
Settings** and keeps Ask off. A Ticket of a completed, cancelled or archived Loop offers no Ask the
agents.

Activity's tab **Discussions** carries the count, between Comments and History. Each row shows the
state while the agents answer, otherwise Tralala's verdict, or "No answer yet"; the question; who it
waits for ("Waits for your decision", "Waits for the agents", "Waits for you to resume") or the
decision with who took it ("Vetoed by Mike"); and a line such as "3 agents · 2 for · 1 against ·
round 2 of 3 · asked by Mike · Nov 8, 2026". Discussions that wait for your decision come first,
then those the agents are answering, then the decided ones, each newest first. A Ticket without one
reads "No discussion yet. Ask the agents what they think."

### The discussion

A row opens the discussion in the Ticket's dialog over the Kanban. **Back to the Ticket** returns
to the Ticket, and **Open as page** shows the same view on a page of the Ticket, with the
breadcrumb Board / Loop / Ticket / question. The question is the heading, with a line under it:
"Asked by Mike · 3 agents · round 2 of 4".

- **The sign** comes first: Tralala's verdict as one word (**Yes**, **Yes, with conditions**,
  **No** or **Unclear**) and one sentence of at most 20 words that counts who stands where and
  names nobody ("The participants differ: 1 for going ahead, 1 against and 1 cannot tell."). Under
  it, by name, who cannot tell yet and who has not answered, and the faint line "Tralala's summary
  of the answers after round 2. A suggestion, never a decision: you decide below." No model writes
  the sign: fixed rules count the answers.
- **Who stands where**, with **For you | Raw text**. For you is one row per agent: its role, its
  position, its one recommendation and how confident it is. **Details** opens what that agent
  named **For**, **Against**, under **Conditions** and as **Open questions**. An agent that
  answered outside the agreed shape reads "Answered in prose only", one that has not answered "No
  answer yet", and one the round could not reach "No answer from Cy: the agent could not be
  reached."
- Under the rows, sections that open with a click: **Conditions to accept if you go ahead** and
  **Open questions**, each point with who said it, and **Rounds**: one line per round with who asked
  or replied before it, how many answered and the verdict after it.
- **Your reply** and **Ask again**: one message, which the agents answer in a new round. While
  they are answering, the reply waits ("The agents are answering. Reply once they are done.").
- **The rail**: **Status** in the words of the sign ("Waits for your decision · after round 2",
  "Agents are answering · round 2 of 3", "Paused", "Approved by Mike", "Vetoed by Mike", "Rework
  requested by Mike", "Stopped by Mike", "No answer yet"), **Facts** (Ticket, Asked by, Agents,
  Rounds, Tokens, Started) and **More** (Copy link, and Pause, Resume or Stop the run while one is
  under way).

What an agent writes for you is held to limits the server counts, never a model: the
recommendation is one sentence of at most 20 words; For, Against, Conditions and Open questions
hold at most three points each, a point at most 140 characters; and none of them holds a file name
or path, code or an id. An answer that breaks a limit goes back to its agent once, with every
finding named; one that still breaks it is kept as written and reads "Answered in prose only". The
agent's reasoning has no such limit, because it is the agents' side: the other agents read it, and
you find it in Raw text.

**Raw text** holds what the agents wrote, as it is and unstyled on purpose: the **Transcript**
(every message with its author, role, round and time), **Answers · JSON** and the **Runs** with
their codes, tokens, budgets, elapsed time and stop reasons.

### Rounds: Ask again, Let them talk it out, Stop

A discussion has three rounds unless it was opened with another number, and never more than four.
**Ask again** is one round. **Let them talk it out** lets the agents answer each other: "The
agents answer each other for up to 2 rounds and stop when they agree or when the budget is spent."
Its **Options** set the **Rounds** (the rounds left, at most four), a **Token budget** and a **Time
budget in seconds**; an empty field means the server's default. **Start** begins.

While the agents talk, the sign opens with "Agents are answering · round 2 of 3" and "2 of 3 agents
have answered this round", **Stop** takes the place of the decision buttons, and **More actions**
holds **Pause while they talk** or **Resume**. When a run ends without agreement, a line under the
sign says why: "The budget ran out", "The agents repeated themselves, so the run stopped", "No
agent could be reached", "Stopped by Mike", "Rounds used up" or "The run broke off when the server
restarted". Let them talk it out is off, with the reason on hover, while the agents answer, once
no round is left and once the discussion is decided.

### Your decision

**Approve**, **Request rework** and **Veto** are a person's decision; a key is refused
(`403 human_action_required`). They are off, with the reason on hover, until there is an answer to
decide on, and while the agents answer Stop takes their place. Request rework and Veto ask for an
explanation. A decision
is recorded on the discussion only and never changes the Ticket: what follows from it is yours to
do. After Request rework, Ask again starts the next round; Approve and Veto close the discussion.

### The inbox

**Discussions** in the main navigation is an inbox over every board that is not archived (an
archived board is read-only, so its discussions are read on its Tickets): **Waits for your
decision**, **Agents are talking** and **Decided**, each with its count and newest first. A row
shows the verdict (or the round while the agents talk), the question, when it last moved (or the
decision with who took it) and a line such as "SES-1-PH01-001 · Session expiry · Platform · 3 agents
· 2 for · 1 against · round 2 of 4". A row opens the discussion as a page of its Ticket. A cancelled
discussion is not listed, and a discussion starts from a Ticket, never from the inbox. The
dashboard's **Waits for you** lists the discussions that wait for your decision after the Loops,
each with **Open discussion**.

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
`403 human_action_required` for every other action in the table, even when it holds the scope.
Two writes are a person's too, although they decide nothing: changing a Ticket's face (a token
writes a new RoadMap revision instead) and writing, editing or deleting a note on a Ticket (the
person's own words). WebMCP registers inspection, generation and permitted Ticket tools, never
these decisions.

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

Inside that set a Loop can remember one agent per purpose (**Loop agents** in the **Loop actions**
menu): analysis, RoadMap and QA. The stored choice only fills in the default of the next run and
shows as `Default (<agent name>)`; the agent menu beside **Generate** can still deviate for a single
run, and a stored agent that is no longer available falls back to the board default.

Which code that agent may look at is decided on the same dialog: the repositories from
**Settings -> Repositories** (`repository_ids`), read from GitHub or from a mirror of any allowed
HTTPS Git host ([Repositories.md](Repositories.md)). A repository can serve several boards, and a
board can list several. The token behind each repository is read-only and sealed, and an agent sees
only the repositories of the boards it serves. An agent whose connection test found tool calling
reads that code itself during an analysis or RoadMap run; any other agent gets a fixed snapshot
([How a run reads the code](Repositories.md#how-a-run-reads-the-code)).

A run works in the background, so the Plan tab shows what it is doing, in a second column beside
the documents on a wide screen and under the button that started it otherwise: the run's steps in plain
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
for the duration, so the same document cannot be started twice by accident.

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
`after_loop_completed: true`, which the Ticket view shows as "written after the Loop was
completed".

Legacy material is stored with `source_kind = imported_legacy`, `conformance = legacy_unvalidated`
and its original bytes. It is never converted into an active Loop, never creates Tickets and never
counts as a verified QA result; every view labels it
`Imported legacy reference - may not follow the current standard`.

## Search

Every search result keeps the Loop context of the Ticket it points at: it names the Loop and opens
that Loop's page with the Ticket showing over it, never an inferred default Loop. A discussion does
the same through its Ticket ([Ask the agents](#ask-the-agents)).

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
