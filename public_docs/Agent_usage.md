# Agent usage

Tralala has two kinds of agent, and they are not the same thing:

| | Worker (outside) | Role agent (inside) |
| --- | --- | --- |
| Who starts it | You, from a coding agent on your machine | Tralala, during an analysis, a RoadMap, QA or a discussion |
| How it authenticates | A key you create in Settings | Nothing: it never authenticates |
| What it can do | The curated tools below, within the key's scopes | Answer a prompt; it is a reader and a discussion partner |
| What it cannot do | Change boards, approve plans, accept QA | Change a Ticket, run code, or touch the repository beyond reading it |

A role agent whose connection test found tool calling (Settings lists it as *reads repositories
with tools*) reads the board's repositories itself during an analysis or RoadMap run, through three
read-only tools that Tralala answers from the run's commit. Those are not the worker tools below and
need no key; any other role agent gets a fixed selection of files. See
[How a run reads the code](Repositories.md#how-a-run-reads-the-code).

This page is about the outside one.

## 1. Get a key

**Settings → New access key**. Any signed-in person may issue keys for their own machine; the value
is shown once and belongs to that account, so disabling the account revokes it.

Give the key what the work needs, nothing more:

| Scope | Allows |
| --- | --- |
| `boards:read` | read a board and its Loops |
| `loops:read` | read a Loop's documents, plan, readiness and Tickets |
| `cards:read` / `cards:write` | read a Ticket; assign it or move it |
| `comments:write` | comment on a Ticket |
| `discussions:read` / `discussions:write` | read a thread; ask the agents and reply |
| `loops:write` | create a Loop, write its Info while it is still speculative |
| `loops:generate` | run the analysis and the RoadMap generation |
| `history:read` | read completed Loops |

A typical coding-agent key is all of the above. A read-only reviewer needs `boards:read`,
`loops:read`, `cards:read`, `discussions:read` and `history:read`.

## 2. Connect

Two endpoints, one token, standard headers:

```text
GET  /llms.txt      public bootstrap: envelope, Loop lifecycle, rules, tool list (no ids, no data)
POST /mcp           MCP over JSON-RPC 2.0 (Streamable HTTP), Bearer token
```

```bash
export TRALALA_TOKEN="trl_..."
export TRALALA_URL="http://127.0.0.1:5173"        # or https://<host>.<tailnet>.ts.net

curl -s -X POST "$TRALALA_URL/mcp" \
  -H "Authorization: Bearer $TRALALA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

In a client that speaks MCP:

```json
{
  "mcpServers": {
    "tralala": {
      "type": "http",
      "url": "https://<your-host>/mcp",
      "headers": { "Authorization": "Bearer <your key>" }
    }
  }
}
```

`"type": "http"` names the transport, not the scheme: `https` is what you use over a tunnel or with a
certificate. `/llms.txt` is plain text at the same origin.

## 3. The tools

| Tool | Scope | What it does |
| --- | --- | --- |
| `whoami` | `boards:read` | your key, when it expires, what your scopes open, what you lack and what only a person decides |
| `list_boards` | `boards:read` | the boards you may read, by name, with status and Loop count: the way in |
| `read_board` | `boards:read`, `loops:read` | a board's Loops, the people you may assign, the agents you may ask |
| `read_loop` | `loops:read` | a Loop's overview: documents' state and size, Phases, columns, Tickets, newest notes |
| `read_document` | `loops:read` | one document's text a page at a time, or the technical analysis and RoadMap as an outline |
| `read_ticket` | `cards:read` | one Ticket with its blockers and what you may do next |
| `search_tickets` | `cards:read` | find Tickets by words: in one Loop, a board's open Loops or every active board |
| `list_tickets` | `cards:read`, `loops:read` | a board's (or a Loop's) Tickets as short rows with a summary each: choose here, then `read_ticket` |
| `write_ticket_summaries` | `cards:write` | write the short summaries the list shows, up to 100 at a time |
| `assign_ticket` | `cards:write` | assign a Ticket to a person |
| `move_ticket` | `cards:write` | move a Ticket to another column (version-checked) |
| `comment_ticket` | `comments:write` | add a comment, done or not: progress, findings, a blocker |
| `write_note` | `loops:write` | add a note to the Loop's log: baseline, checks, merge, deploy, what is open |
| `read_notes` | `loops:read` | read the Loop's notes, a page at a time |
| `create_ticket` | `cards:write`, `comments:write` | add a follow-up outside the plan while the Loop executes, keyed `<LoopKey>-UNP-<nnn>` |
| `complete_ticket` | `cards:write`, `comments:write` | finish a Ticket: your summary and evidence as a comment, then completed |
| `create_loop` | `loops:write` | open a Loop for an agreed intent (idempotent) |
| `write_info` | `loops:write` | write the Info, only while the Loop is `draft` or `analysis_review` |
| `run_analysis` | `loops:generate` | ask the analysis agent to produce a candidate |
| `run_roadmap` | `loops:generate` | ask for the RoadMap candidate |
| `write_analysis` | `loops:generate` | hand in your own analysis, in the same schema and review as a generated one |
| `write_roadmap` | `loops:generate` | hand in your own RoadMap; short Phase and Ticket ids become stable UUIDs |
| `ask_agents` | `discussions:write` | open a discussion on a Ticket and run one round |
| `read_discussion` | `discussions:read` | read a thread and each agent's position |
| `reply_discussion` | `discussions:write` | add to a thread |

Tools are filtered by the key's scopes, so a key without `loops:generate` does not see
`run_analysis` at all. Calling a tool the key may not use is refused rather than downgraded.

## 4. A session that works

```text
whoami                          -> what this key may do, when it expires, what only a person decides
list_boards                     -> pick the board; its id comes from here, never from a prompt
read_board                      -> pick the Loop
list_tickets                    -> the Tickets as short rows with a summary each: choose one
read_loop                       -> the Loop's overview: stage, documents, Phases, blockers
read_document                   -> the Info, the analysis or the RoadMap you need, a page at a time
search_tickets                  -> find a Ticket by words when you know what, not where
read_ticket                     -> read the one you are about to touch, including its version
  ... do the work ...
comment_ticket                  -> what you found or what you changed
assign_ticket / move_ticket     -> hand it on, or move it to the column that means "in progress"
complete_ticket(summary)        -> done: the summary and evidence as a comment, completed_at set
create_ticket(follow_up_of)     -> anything you found that is not this Ticket's work
write_note                      -> what belongs to the Loop: baseline, checks, merge, deploy
```

Every Ticket carries a short summary so `list_tickets` reads like a table of contents. A RoadMap
gives each planned Ticket its summary (`summary` on every Ticket in `write_roadmap`); a Ticket you
create takes one in `create_ticket`. When the list shows `summary_kind: excerpt` or `none`, or
`summary_stale: true`, write the summaries with `write_ticket_summaries`: one or two plain sentences
each, no file paths or code.

To start something new together:

```text
create_loop(intent)             -> a Loop in draft
write_info(content)             -> the agreement, written down while still speculative
run_analysis()                  -> the analysis agent produces a candidate
  or write_analysis(analysis)   -> you hand in your own, in the same structure
ask_agents(question)            -> discuss it with the role agents meanwhile
```

Then a person approves the analysis, and after it the RoadMap (`run_roadmap`, or your own through
`write_roadmap`). An agent can prepare everything and cannot take that step.

Your own analysis and RoadMap are not a second kind of document. `write_analysis` and
`write_roadmap` take the schemas `GET .../loops/{loop_id}/context` answers under `schemas` (and
`tools/list` carries them), go through the same validation as a generated candidate, get the same
rendered human view and wait for the same approval. `technical_detail` is written for engineers,
`plain_language` for a project manager; every risk, blocker, legal, security or question finding
needs the latter. In a RoadMap you may name Phases and Tickets `p1`, `t1`: they become UUIDs derived
from the Loop and the id, listed in the answer's `id_map`, so the same ids keep the same Tickets and
keys when you hand the RoadMap in again. Send `expected_info_revision_id` or
`expected_analysis_revision_id` with what you read, and a document that changed meanwhile answers
`409 document_stale`. While an analysis or a RoadMap is approved, a token cannot replace it
(`403 human_action_required`): the person requests changes or resets it first.

### Work outside the plan

A follow-up you discover while a Loop executes (`ready`, `in_progress` or `awaiting_qa`) is
`create_ticket`: a Ticket outside the plan, keyed `<LoopKey>-UNP-<nnn>`, in the Loop's first column.
It never blocks a Phase, the plan's readiness or the Loop's completion; `read_loop` lists it under
`unplanned_tickets`, and accepting the implementation names the ones still open. With
`follow_up_of`, the description starts with `Follow-up of <KEY>:` and the origin Ticket gets the
comment `Follow-up: <NEW KEY> - <title>`. Outside an execution stage the answer is
`409 plan_change_required`.

## 5. What a worker cannot do, by design

- Approve an analysis or a RoadMap, confirm a human-only Ticket, accept QA, finalize a Loop — these
  answer `403 human_action_required` even with every scope.
- Create or archive boards, change board structure, publish or edit a RoadMap, or create a
  *planned* Ticket: the plan does, after a human approves it. Work you find while executing goes
  outside the plan with `create_ticket` (below).
- Change a Ticket's approved scope, or move work between Loops.
- Complete a Ticket by moving it: a column named Done completes nothing. `complete_ticket` is the
  way, and it is offered in `read_ticket`'s `allowed_actions` only while the Ticket is ready, open
  and not a person's. A human-only Ticket answers `403 human_action_required` naming who confirms
  it; an unfinished prerequisite answers `409 ticket_blocked` with the blockers. Either way your
  summary is kept as a comment, and the refusal names its `comment_id`.
- See or change users, credentials or agent configuration.

## 6. Retries and repeats

- `create_loop` accepts an `idempotency_key`, so a retried create returns the first Loop instead of a
  second one.
- `write_info` with identical content returns the existing revision (`deduplicated: true`).
- `comment_ticket` and `ask_agents` treat an identical call from the same actor within five minutes
  as a retry and return the original object; so does `complete_ticket` with the same summary and
  evidence (`deduplicated: true`). A Ticket somebody already completed answers
  `already_completed: true` and keeps your summary as a comment.
- `create_ticket` asked for the same Ticket again (same Loop, title, description, priority and
  origin) answers the first one (`deduplicated: true`) for a day.
- `move_ticket` is version-checked: send the version you read, and a `409 version_conflict` means
  someone else moved it first — re-read rather than retrying blindly.

## 7. The REST API is still there

Anything that is not a tool — search, checklists, activity, readiness, exports, backups, board
settings — is `/api/v1/...` with the same key, documented in [API.md](API.md). `/llms.txt` is the
short version an agent can read without being told anything.

The catalogue is decided on the server: `/mcp` advertises only the tools the key may use, and a key
acts as its own agent identity, owned by the person who issued it.
