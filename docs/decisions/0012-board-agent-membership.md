# 0012 — A board selects the agents that work on it

- **Status:** accepted
- **Date:** 2026-11-01
- **Context:** Loops, agent identity, repository access ([0007](0007-accounts-sessions-and-keys.md),
  [0011](0011-repository-access-for-analysis-agents.md))

## Problem

A Loop's generation runs on an agent chosen in that Loop's dialog. Every agent in the installation
is offered for every board, which means:

- a person cannot tell which agents are meant to work on this board and which belong to another
  board or another team,
- an analysis can silently run on an agent the board's owner never intended (wrong role prompt,
  wrong model, wrong provider credential),
- which code an agent may read is a board decision (repositories, `0011`), while which agent reads it
  is not — the two belong together.

## Decision

**A board lists the agents that work on it**, as a many-to-many link (`board_agents`), mirroring the
repository links of `0011`:

1. **Selection lives on the board.** `POST`/`PATCH /boards` take `agent_ids`, every `BoardOut`
   returns them, and the create/edit dialogs show them as checkboxes. An unknown id is rejected with
   `404 agent_not_found` before anything is written.
2. **An empty selection means "any enabled agent".** Boards created before this change keep working
   without a migration step deciding for them, and a single-agent installation never has to click
   anything. A non-empty selection is a restriction.
3. **The restriction is enforced by the service, not the UI.** Generation resolves its agent through
   `LoopGenerationService._resolve_agent`, which rejects an agent the board does not list
   (`422 agent_not_on_board`) and prefers a listed agent when the caller expressed no preference.
   The Loop dialog narrows its dropdown with the same rule, so the UI and the API agree.
4. **Links are registry data, like the agents themselves.** They are not copied into a board
   database or a board export, and deleting an agent detaches it from every board (`ON DELETE
   CASCADE`) instead of leaving a dangling selection.
5. **Agents are not "owned" by a board.** One agent may work on several boards, and an agent's
   identity, connection, credential and role stay registry-level, editable in one place.
6. **A Loop may remember one agent per purpose.** Board revision `0009_loop_agent_preferences` stores
   `analysis`/`roadmap`/`qa` → `agent_id` in the *board* database, because that is where the Loop
   lives; it holds no foreign key, since a board database must not depend on registry rows. The
   preference only seeds the default of the next run (`Default (<agent name>)`), an explicit
   `agent_id` on the run still wins, and a preference that no longer resolves (deleted agent, or the
   board dropped it) falls back to the board default rather than blocking generation. Setting it
   needs `boards:write`, so it stays a governance action while generation itself is `loops:generate`.

## Consequences

- The Analytics agent's access is now fully described by the board: *these* repositories, *these*
  agents. That is the pair a person reviews before a Loop generates.
- A board whose only listed agent is disabled cannot generate. The dialog says so ("No board agent
  can generate") and the API answers `422` with the agent's state, which is a clearer failure than
  running on somebody else's agent.
- Role templates stay shared. Selecting an agent does not copy a prompt; the run snapshot still
  records the role text that was actually used (`AgentService.role_snapshot`).
- A per-Loop agent assignment (a different agent per phase) is deliberately not built. It would need
  a rule for every transition; the board selection covers "who may work here at all".

## Alternatives considered

- **One agent per board (a column).** Rejected for the same reason as in `0011`: the second agent
  arrives immediately (an analyser and an implementer), and re-modelling a column into a table later
  costs a migration and a data copy.
- **Required selection.** Rejected: existing boards would have to be backfilled with a guess, and a
  fresh installation would not be able to create its first board before configuring an agent.
- **Per-Loop assignment only.** Rejected for this slice: it answers "who does this Loop" but not
  "who may touch this board", and it duplicates the same decision once per Loop.
- **A dedicated scope per agent-board pair.** Not needed while board access is already authorized
  through the registry; the selection narrows execution, it does not grant access.
