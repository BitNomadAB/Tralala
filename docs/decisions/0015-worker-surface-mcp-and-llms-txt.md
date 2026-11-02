# 0015 — A curated worker surface at `/mcp`, described publicly at `/llms.txt`

- **Status:** accepted
- **Date:** 2026-11-02
- **Context:** Role templates and agent snapshots ([0001](0001-role-template-vs-agent-snapshot.md)),
  WebMCP as an adapter ([0004](0004-webmcp-adapter.md)), board agent membership
  ([0012](0012-board-agent-membership.md)), organisation-wide profiles
  ([0013](0013-organisation-wide-agent-profiles.md))

## Problem

The work on a Board is done by a person and by an agent outside the installation — a developer's
coding agent with a terminal, a git checkout and its own tools. The local role agents are readers:
they are invoked by a run, they read documents and code, and they answer in a discussion. They never
authenticate and never change a Ticket.

That external worker had no usable entry point. It could call REST, but:

- nothing told it what the product is, which ids to read first, or which invariants hold, and the
  OpenAPI schema is authenticated, so a URL alone revealed only an empty SPA shell;
- `/llms.txt` fell through to `index.html` with a `200`, so an agent that probed the convention got
  HTML and believed it had succeeded;
- a token is its own agent actor holding neither `users:admin` nor `agents:read`, so it could not
  look up the person a Ticket should be assigned to;
- the only curated capability list was the browser's WebMCP adapter, which is invisible to a
  headless agent and contains structure-changing tools (`create_board`, `create_list`,
  `archive_card`) that a worker should not have.

## Decision

1. **One catalogue, several transports.** `backend/app/services/agent_tools.py` defines the worker
   surface once: name, description, JSON Schema, required scope, and a handler that calls the same
   services as REST. `/mcp` serves it as MCP tools and `/llms.txt` summarises it. The browser WebMCP
   adapter stays a separate, UI-contextual surface for a person's own session; unifying it on this
   catalogue is left for later. No transport owns a business rule; all of them go through the service
   layer, so authorization, version checks and workflow gates are the ones REST already enforces.
2. **Seven tools, all about reading and tracking.** `read_board`, `read_loop`, `read_ticket`,
   `assign_ticket`, `move_ticket`, `comment_ticket`, `ask_agents`. Absent by design: board and list
   creation, Ticket creation, archiving, document writing, generation and every human decision. The
   narrowness is expressed as a tool list rather than as new scopes, because `cards:write` covers
   both "move this Ticket" and "create or archive one"; a scope cannot state that boundary, a
   catalogue can.
3. **`POST /mcp` speaks MCP over JSON-RPC 2.0 (Streamable HTTP).** `initialize`, `tools/list`,
   `tools/call` and `ping`; notifications answer `202`; `GET /mcp` answers `405` because the server
   has no messages to push. Every method is authenticated, including `initialize`, and `tools/list`
   is filtered to the scopes the token holds so a worker never even sees a capability it may not
   use. Refusing a tool is a JSON-RPC error (`-32602`); a tool that fails returns `isError: true`
   with the API error code in its text, so `version_conflict` and `human_action_required` reach the
   model as data it can act on.
4. **`GET /llms.txt` is public and boring.** It names the envelope, the Loop lifecycle, the rules
   that never change, the tool list and the REST equivalents, and contains no ids, no data and no
   secrets. It is served at the origin, above the SPA fallback, in nginx and in the Vite dev proxy;
   a probe of an unknown path that happens to be a convention must not answer with HTML.
5. **`GET /boards/{board_id}/actors` closes the assignment gap.** A token cannot read `/users`
   (`users:admin`) or `/agents` (`agents:read`, not grantable to tokens), so the board publishes two
   lists: `people` (enabled humans, assignable) and `agents` (enabled board profiles, askable,
   honouring the board's selection). It carries ids and names only — no endpoint, model or
   credential hint.
6. **The version belongs to the server, not the prompt.** `move_ticket` accepts a column id or name
   and reads the Ticket version itself, retrying once if another writer wins; `assign_ticket` reads
   the version for the caller. Optimistic concurrency stays a server rule — the tool stops a model
   from having to carry a number it does not own.

## Consequences

- A URL plus a token is enough: `/llms.txt` explains the contract, `/mcp` lists what the token may
  do, and every call lands on the same authorization path as the UI.
- The Board becomes the coordination log between a person and their worker: the Ticket is the task,
  a comment is progress, the column is state, and a discussion is where the local agents are asked.
  A worker needs no repository file of its own to know what to do next.
- The local agents keep their role: readers and discussion partners. Nothing here lets a role agent
  authenticate, and nothing here lets a worker approve a plan, confirm human work or accept QA.
- A future capability is a catalogue entry plus a handler, not a new endpoint, a new transport and a
  new client. Adding one is also the moment to decide, explicitly, that a worker may have it.
- The browser adapter still defines its own UI-contextual tools. That is a known duplication: they
  call the same REST client, so they cannot break a rule, but they can list a tool the worker
  catalogue would not allow. Unifying them on this catalogue is the next step, not a promise made
  here.

## Alternatives considered

- **MCP only in the browser, through WebMCP.** WebMCP lives in `navigator.modelContext`; a headless
  or desktop agent never sees it. It stays useful where it needs no secret — the browser already has
  the person's session — but it cannot be the worker's only door.
- **REST only, with `/openapi.json` as the manual.** Complete, but it describes endpoints, not
  intent: it cannot say "read the Info before you move a Ticket", that only a person may approve a
  plan, or that a Ticket is done when `completed_at` is set rather than when a column is named Done.
- **A new scope set for workers.** `cards:move`, `cards:assign`, … would multiply the authorization
  matrix and still not describe intent to a model. The catalogue is the smaller, more readable place
  for "and nothing more".
- **Making `analysis`/`roadmap` generation a worker tool.** Rejected for now: generation produces a
  document candidate that a person approves. A worker that wants a written analysis can ask for one
  once that flow is designed; until then it asks a question in a discussion.
