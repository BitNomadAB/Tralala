# Onboarding

Tralala is installed and you are signed in as `admin`. This is what to do next, in the order that
avoids going back: make the account yours, bring in one person, connect one agent, connect one
repository, then run one Loop end to end. Each section is short on purpose; the why lives in
[Architecture.md](Architecture.md) and the rules in [Loops.md](Loops.md).

```text
1 account -> 2 people -> 3 agent -> 4 repository
   -> 5 one Loop: Info -> Analysis -> RoadMap -> Execution -> QA -> Finalize
   -> 6 habits
```

## 1. Make the administrator account yours

**Settings → Your password.** Enter the current password (from `<data>/.bootstrap-password` on a
fresh install) and a new one of at least 8 characters. Every other session is signed out, including
yours, so sign in again. The change also deletes `<data>/.bootstrap-password`: it is a delivery
mechanism, not a credential, and Settings tells an administrator as long as it is still there.

Nothing else on this page is required to start working. The theme kits, backups and appearance
settings can wait.

## 2. Bring in one other person

1. **Settings → Users → New user** creates the account with a username and an initial password.
   Choices: `member` (everything except user and credential administration) or `admin`.
2. Or press the **invitation link** icon next to the account: it shows `/enrol?token=…` once. Send
   it through a channel you trust; the person chooses their own password and is signed in. You never
   learn it. The link expires after `TRALALA_INVITE_TTL_HOURS` (default 72) or when replaced.
3. Switching a person to `member` or `admin` takes effect immediately, and both roles see every board
   today — private boards are a separate feature, not a setting.

Tralala sends no e-mail. Delivery is yours.

## 3. Connect one agent

Two different things are called "agent". Do the first one if you want AI help inside Tralala; the
second if you want your own coding agent to drive Tralala.

### 3a. A role agent, so Loops can be analysed and discussed

1. **Settings → Agents → New agent.**
2. Name it, pick a **role template** (the factory list includes Lead Developer, QA Engineer,
   Security Engineer, Architect, Project Manager…), and set the **connection**. The two choices are
   different things, not two ways to say the same:

   | Connection | What sits on the other end | What the role decides |
   | --- | --- | --- |
   | `openai_compatible` | A model endpoint you point at. It has no tools or memory of its own. | Everything: Tralala sends the role prompt and the conversation, and the model answers as that role. |
   | `a2a` | An agent that already runs outside Tralala, with its own tools, memory and job. | Only how it answers inside this board. It arrives with its own way of working. |

   A local model is fine — private and loopback addresses are allowed on purpose.
3. Paste the provider **API key** if the endpoint needs one. It is sealed with a key derived from your
   session secret and never shown again; the list only says `has_api_key` plus a hint.
4. Press **Test connection** — before you save. It asks the endpoint which models it serves *and*
   sends one tiny real completion, so a wrong model name fails here instead of in a generation an hour
   later. Nothing is stored until the test is green, the reported model names become suggestions in
   the model field, and the raw answer is shown as JSON so the same block serves every provider.

   The test also finds out whether the model calls tools, and the agent list in Settings then says
   *reads repositories with tools* or *no tool calling*. The first kind reads a board's repositories
   itself during an analysis or RoadMap, as much as the request needs; the second gets a fixed
   selection of files (see section 4). Test again after you change the model.

   A model on the machine that runs Tralala is `http://host.docker.internal:<port>/v1` from inside
   the container, not `127.0.0.1`; see
   [Reaching a model that runs on the host](Installation.md#reaching-a-model-that-runs-on-the-host).
   A model running on your own machine or network — `http://192.168.0.10:8080` — usually has no key:
   tick **This endpoint needs no key** and nothing is sent, in the test or in a generation. The known
   local presets tick it for you; hosted providers keep it unticked and cannot be saved without one.

   Leave **Temperature** and **Maximum answer length (tokens)** empty unless you know you need them:
   empty sends neither, so the provider's own defaults apply and a provider that refuses either one
   still answers. **Timeout** starts at 180 s, because a reasoning or local model can need minutes for
   a structured answer; the connection test keeps its own limit of 30 s per call.
5. Make it work on the board: open the board and choose **Edit board → Agents**. An agent a board does
   not list is never asked on that board; leaving every box unchecked means "any enabled board
   profile", which is fine for a single-agent install. A Loop can narrow that further in its own
   agent settings.

An agent is a reader and discussion partner: it never authenticates, never moves a Ticket and never
changes code.

### 3b. A worker key, so your own coding agent can read and update Tralala

1. **Settings → New access key.** Name it, pick scopes, create. The token is shown once.
   For a coding agent take `boards:read`, `loops:read`, `cards:read`, `cards:write`,
   `comments:write`, `discussions:read`, `discussions:write`; add `loops:write` and
   `loops:generate` if it should open Loops and hand in or ask for analyses and RoadMaps.
2. Point the agent at `<your URL>/mcp` with `Authorization: Bearer <key>`. `<your URL>/llms.txt`
   tells it the rest. The full walkthrough, every tool and its scope are in
   [Agent_usage.md](Agent_usage.md).
3. The key belongs to your account: disable the account and it stops. Revoke it under the same list
   when a laptop is retired, and check `last_used_at` if you are unsure which key is which.

## 4. Connect one repository (optional, but it is what makes analysis concrete)

1. Create a **fine-grained GitHub token** with *Contents: read* for that repository only (a public
   repository needs none).
2. **Settings → Manage repositories → New repository**: provider *GitHub*, name,
   `https://github.com/your-org/your-repo`, optional branch, and the token. It is stored sealed and
   never shown again.
3. **Test access** proves the token works before you rely on it.
4. Assign it to the board: open the board → **Edit board → Repositories**. A board may have several;
   the analysis agents read only what is assigned, and the repository page shows which board uses
   which repository.
5. Optional: point the analysis at the part that matters. A selected repository shows **Focus
   paths** and **Exclude paths**, one glob per line relative to the repository root: `docs/**` reads
   only the documentation, `docs/archive/**` under exclude leaves old pages out. Both empty reads the
   whole repository. At most 20 globs of 200 characters each; no absolute paths and no `..`.

Without a repository the analysis still works from the Info you write; with one it cites files and
revisions, which is what makes the RoadMap reviewable.

A repository on another Git host (a closed network, a self-hosted server) uses the provider
*Git over HTTPS*: Tralala keeps a mirror of its main branch and fetches it before every run, once
the operator has listed the host in `TRALALA_REPOSITORY_HOSTS`. [Repositories.md](Repositories.md)
has the whole procedure, the token recipe for other hosts and a troubleshooting table.

What an analysis can see depends on the agent. An agent that *reads repositories with tools* lists,
reads and searches the repositories at the run's commit itself, as often as it needs, within limits
the operator sets ([How a run reads the code](Repositories.md#how-a-run-reads-the-code)). Any other
agent gets a fixed selection that is **bounded on purpose**: at most 200 files and 200 KB of text
per repository, with build output, dependencies, lock files, binaries and images skipped, plus a
list of every file so the model knows what exists. Either way, a file the model could not read is a
file the analysis must list under *open questions* instead of guessing. After a run, the Loop's
**Plan** tab shows which commit each analysis was
based on and how many files it covered — "based on acme app @ abc123de, 12 files" — and the run's
steps say what the model read. A repository that could not be read appears there with its reason
(`unauthorized`, `not_found`, `rate_limited`, `too_large`, `timeout`).

## 5. Run one Loop end to end

A **Board** is a project; a **Loop** is one feature or coherent change inside it. Create a board
(**New board**), then a Loop inside it (**New Loop** — a name and a broad goal are enough).

The dashboard lists what **Waits for you** first: every Loop whose next step is your decision, with
a button that opens it. Under it come **Your boards**, and an archived board sits apart under
**Read only**: it can be opened and read, restored or deleted from its menu, and nothing on it
waits for you. A Loop page has three tabs: **Kanban** (its columns and Tickets), **Plan**
(the Info, the analysis and the RoadMap, and the Phases with what holds them up) and **Notes**. The
one button beside the Loop's name is your next decision; everything else is under **Loop actions**.

### The order of work inside a Loop

| Step | Who | What happens |
| --- | --- | --- |
| 1. Info | you, maybe with your coding agent | Write the intent: what to build and why. This is the input everything else is derived from. |
| 2. Analysis | the analysis agent or your coding agent, approved by you | Generate or hand in a technical analysis; on the **Plan** tab read the brief **For people**; **Approve analysis**. Approval binds to that exact revision. |
| 3. RoadMap | the RoadMap agent or your coding agent, approved by you | A structured RoadMap: numbered Phases and planned Tickets, each with its plain face; **Approve RoadMap · N Tickets** publishes every Ticket at once. |
| 4. Execution | you, with your coding agent as a tool in your session | Move Tickets through the Loop's columns, assign them, comment progress. Readiness shows what blocks a Phase. |
| 5. QA | the QA agent, accepted by you | Ask for a QA Task (scenarios, agent view and human view); **accept implementation**, then **accept QA**. |
| 6. Finalize | you | The Loop is finalized: an immutable, hashed snapshot lands in History and the Loop becomes read-only. |

Three rules that keep this honest:

- **A person decides.** Approving or resetting the analysis and the RoadMap, editing the Info once
  planning has started, confirming a human-only Ticket, clearing a Ticket's wait, accepting the
  implementation and QA and finalizing are human actions. A token cannot perform them, whatever
  its scopes.
- **Changing Info invalidates approvals.** Edit the intent after planning and the Loop returns to
  `replanning`; the dependent approvals go stale and execution stops until you approve a replacement.
- **A column named Done completes nothing.** Completion is the acceptance decision, not a move.

### Where to talk instead of writing

Every Ticket can have **discussions**: ask the agents a question about it, read where they stand,
let them answer again, then decide ([Ask the agents](#ask-the-agents) below). A discussion is
capped at four rounds, with a token and time budget per run, so a question cannot quietly spend the
afternoon. Use one when you want the agents' opinion before you settle the plan; use `@Agent` in a
comment when you want one answer next to the work.

### Plan with your coding agent

Your first Loop goes best with the coding agent you already use, connected with the key from
section 3b. The agent is a tool in your session: it reads, drafts and records, and you decide.
Tralala's own agents keep the board in order and write decision support; none of them takes a
Ticket off your hands.

1. **Agree the intent in your session**, then ask the agent to open the Loop and write its Info.
   It may do that while the Loop is a draft or its analysis is in review; **Info** on the Loop's
   **Plan** tab shows the revision it wrote, and **Write or revise Info** lets you change it. Once
   planning has started only a person edits the Info.
2. **Analysis.** The agent hands in its own analysis, or asks the Loop's analysis agent for one.
   Open **Analysis** on the **Plan** tab (the button beside the Loop's name takes you there):
   **For people** is the brief for you, **For AI** the technical analysis. The brief reads like a
   sign: **In short** (can it be done, in one line), **Why**, **What you decide** (each question on
   one line), **How big** and **For and against**; its **Raw text** holds the findings as the
   agent wrote them. **Approve analysis** at the end of the brief, or **Request changes**;
   **Rewrite for people** asks for a new brief when the one you have does not help you decide.
3. **RoadMap.** The same again: the agent hands in or asks for a RoadMap, and you read it the way
   you read a Ticket. **For you** is **In short** and one section per Phase, with a row per Ticket
   that opens to its steps and its reasons; **Raw text** is the technical RoadMap.
   **Approve RoadMap · N Tickets** publishes every Ticket with its key onto the Loop's Kanban.
4. **Work the Tickets.** Tell the agent which Ticket to take, or let it list the ready ones that are
   done in the code base. Open a Ticket to see what the agent sees ([Read a Ticket](#read-a-ticket)
   below). When the agent cannot go on without you it marks the Ticket as waiting, with the
   reason; so can you, with **Mark as waiting**. Answer in a comment and press **Clear the wait**:
   only a person clears one, and **Mark complete** stays off until the wait is cleared.
5. **Keep the plan in the Loop.** The agent comments progress on the Ticket, completes it with a
   summary and its evidence, adds what it finds outside the plan as a follow-up Ticket (marked
   **Unplanned**), and writes the baseline, the checks, a merge or a deploy as a Loop note. Nothing
   it plans or logs is a file in your repository.

### Read a Ticket

A Ticket opens over the Kanban. **Open as page** shows the same Ticket on a page of its own, and
**Copy link** under **More actions** copies its address. What you read first is written for you:

1. The title and, under it, what the Ticket means in one line.
2. **What will be done**: the steps, numbered, at most five. They say what changes for you, never
   where in the code; a Ticket that needs more is split into two when the RoadMap is written.
3. Under the steps, sections that open with a click: **Why it is needed**, **If we skip it**,
   **Pro and con**, and **Your notes**: your own words on the Ticket, which your coding agent reads
   and never writes.
4. **Raw text**, beside **For you**, holds what the agent wrote, as it is: **Summary for AI**,
   **Description**, **Accepted when**, **Evidence** and the **Plan entry**. **Edit description**
   opens the description with **Write** and **Preview** and **How to format** (Ctrl+B, Ctrl+I,
   Ctrl+K for a link; the key of another Ticket of the Loop becomes a link to it).

The buttons under the title are the work: **Start work** makes you the owner when nobody is and
moves the Ticket to the next column, **Mark complete** finishes it, then **Mark as waiting**,
**Comment** and **Add file**. The column on the right shows where the Ticket stands: its column, its
state (*Ready*, *Needs input* or *Blocked*, with what holds it up), and **Details**: Owner, Phase,
**Work is done** (*In the code base*, *Outside the code base*, *Not decided*), Depends on,
Priority, Due, Labels and Created; click a value to change it. Further down are **Files** (drop
files on the section or use **Add file**: a specification, a log, a sample, a screenshot; the agent
reads the text ones) and **Activity** with **Comments**, **Discussions**, **History** and **Work**.
**Edit** beside
*What will be done* changes the steps and the reasons; Tralala holds them to the same short
template a RoadMap is held to ([A Ticket's face for people](Loops.md#a-tickets-face-for-people)).

A Ticket of a completed Loop still takes comments, so a later Loop can say that it replaced the
work; such a comment is marked "written after the Loop was completed".

### Ask the agents

When you want a second opinion on a Ticket, ask the board's agents. **Ask the agents** sits in the
head of the Ticket's **Activity** and under **More actions**.

1. Write the **Question** and keep or untick the **Agents** (each with its role). **Ask**: the
   agents answer one round, and the discussion opens inside the Ticket. A board where no agent can
   answer sends you to **Settings** to add one.
2. Read the **sign** first: Tralala's verdict (**Yes**, **Yes, with conditions**, **No** or
   **Unclear**) and one sentence on how the answers stand. It is a suggestion, never a decision.
3. **Who stands where** has one row per agent with its position and one recommendation; **Details**
   opens its points for and against, its conditions and its open questions. Below them,
   **Conditions to accept if you go ahead**, **Open questions** and **Rounds**. What the agents
   wrote at length is in **Raw text**.
4. Want more? Write in **Your reply** and press **Ask again** for one more round, or **Let them talk
   it out** to let the agents answer each other for a few rounds; **Stop** ends a run.
5. Decide: **Approve**, **Request rework** or **Veto**. The decision is recorded on the discussion
   and changes nothing on the Ticket; what follows is yours to do.

The Ticket's **Discussions** tab lists its discussions and what each waits for. **Discussions** in
the main navigation gathers every board's discussions: what waits for your decision, where the
agents are talking, and what was decided; the dashboard's **Waits for you** lists the ones that
wait for you. More in [Ask the agents](Loops.md#ask-the-agents).

## 6. Day two: the habits that matter

- **Boards are cheap, Loops are the unit of work.** One Loop per coherent change; do not park a
  backlog of unrelated Tickets in a Loop you already approved.
- **Write the Info as if someone else will read it.** The analysis and the RoadMap are only as good
  as that paragraph.
- **Watch readiness, not the column name.** **Phases and readiness** on the Loop's **Plan** tab and
  `GET /boards/{id}/loops/{loop_id}/readiness` explain every blocker.
- **Let your worker comment as it goes.** A Ticket with the findings in it is worth more than one
  that looks finished.
- **Backups are automatic** (every 24 h, newest 10 kept). Take one before an upgrade anyway; the
  commands are in [practical_commands.md](practical_commands.md).

## If something looks wrong

[Troubleshooting.md](Troubleshooting.md) covers the generated password, throttling, a stuck
migration, a board that will not delete, and an agent that is not reachable. Security defaults and
what only you can decide: [Security_defaults.md](Security_defaults.md).
