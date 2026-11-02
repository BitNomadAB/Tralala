# 0013 — Organisation-wide agent profiles and a seed file for role templates

- **Status:** accepted
- **Date:** 2026-11-01
- **Context:** Agents and role templates ([0007](0007-accounts-sessions-and-keys.md)), board agent
  membership ([0012](0012-board-agent-membership.md)), repository access
  ([0011](0011-repository-access-for-analysis-agents.md))

## Problem

Every agent in Tralala works on a board. Two jobs have no single board to work on:

- someone has to keep the whole set of boards and Loops coherent, notice work that collides or is
  stuck behind an approval nobody owns, and say which agent profile should answer a discussion
  thread;
- someone has to look at **all** registered repositories at once, understand what each one is and
  what it is built with, and know which ones can safely change together.

Neither fits a board agent: a board agent sees one board's code and one board's Loops. Both need the
installation-level picture, which is exactly what `registry.sqlite` holds.

Separately, the factory role prompts lived as Python literals, so adding or revising a profile was a
code change and there was no single file that said which profiles an installation starts with.

## Decision

1. **Two organisation-wide profiles are seeded: Coordinator and Architect.** The Coordinator takes
   the overview across boards, moderates agents and tasks, and recommends which profile should answer
   a thread; the Architect builds the picture of every repository, its technology, its purpose and
   how repositories interact, and judges from evidence.
2. **Role templates gain a `scope`**: `board` or `organisation` (registry revision `0011_role_scope`).
   Existing templates become `board`, which is what they were. `organisation` profiles are not
   selectable as board agents: `agent_ids` on a board rejects them with `422 agent_scope_organisation`,
   the board pickers list only board profiles, and the Loop generation candidate list excludes them.
   Generation itself refuses an organisation profile as well, both when a run names one
   (`422 agent_scope_organisation`) and when the default pick would otherwise choose one, so a board
   that lists no agents still runs on a board profile.
   An operator who wants one creates an agent in **Settings -> Agents**, where the scope is shown.
3. **Organisation profiles live where the whole picture lives.** Role templates, agents and
   credentials were already registry data; this decision states the rule instead of leaving it
   implicit: what an agent needs to see decides its scope, and a whole-installation view is registry
   data. A board export therefore still never carries a profile that outlives it.
4. **The profiles ship as a seed file:** `backend/app/seeds/role_seeds.json`, loaded and validated by
   `services/role_defaults.py` at import. Every installation seeds the same set, a new profile is a
   data change, and a broken seed (missing key, duplicate key, unknown scope, unresolved placeholder)
   fails startup instead of quietly seeding an incomplete set. That is deliberate: an installation
   that starts with half the profiles would fail later and less clearly. The suite loads and validates
   the same file (`tests/test_role_seeds.py`) before a release.
   The file lives in `app/seeds/`, not `app/data/`, because `data` is ignored by both git and the
   container build.
5. **The Architect needs one read-only token that covers the organisation.** Tralala cannot grant
   GitHub-side coverage; it can only document the recipe and report what it can see. The repository
   dialog's guide gained the organisation variant (same fine-grained token, *Repository access* =
   *All repositories*, `Contents: Read-only`), and the Architect prompt says to state plainly when a
   registered repository is unreadable instead of guessing.

## Amendment — prompts name the context, not the installation

A role prompt is a job description, not a letter. It is written once and reused for every Loop, every
ticket and every installation, so it must not name the product, a board or a Loop: those change per
call and a hard-coded name would be wrong the moment the prompt is reused elsewhere or the product is
renamed or white-labelled.

The factory prompts therefore refer softly ("the Loop you are asked about", "one existing ticket",
"this installation", "every repository registered here") and the identifiers arrive with the request:

- a discussion round and a mention job state `Loop: <name> (<key>)`, `Ticket: <title>` and
  `Ticket id: <uuid> (key: …)`,
- a generation run states the board and the Loop as well,
- the shared preamble says the message names the ticket, its Loop and the installation, and that the
  agent must never guess an identity it was not given.

`RoleTemplateService.seed_defaults` reconciles the **factory copy** of every built-in on startup and
only follows a rewritten prompt into an installation when the stored prompt still equals that factory
copy. A customized built-in keeps its own text — the operator's edits are never overwritten — and
*restore defaults* now yields the current factory prompt rather than the one from first install.

## Consequences

- The question "which agents may touch this board" keeps one answer (board profiles), and "who sees
  everything" has a separate, explicit answer (organisation profiles).
- A discussion can now be routed by role instead of by whoever is at hand: the Coordinator's
  recommendation names a profile, not a person, and a human still decides.
- The Architect's usefulness depends on the token: with an organisation-wide read token it can
  compare repositories; without it, it must say what it could not see. Its analysis is advice; the
  repository work itself still happens per board.
- Adding a profile is now editing a JSON file. An unedited built-in follows the seed on upgrade;
  a customized built-in keeps its own prompt and only its factory copy moves, and `scope` is
  reconciled for built-ins.
- A prompt never has to be revised because a board, a Loop, an installation or the product name
  changed: it is told those when it is asked. What changes per call is data, not prompt text.
- Prompt text is duplicated nowhere: the shared discussion preamble lives once in the seed file and
  is expanded into the roles that use it.

## Alternatives considered

- **A third board per "organisation" with its own Loop.** Would give the profiles a board to live on,
  but a board is a data boundary with its own database; making one hold every other board's overview
  would duplicate state and put an export boundary in the wrong place.
- **Keep prompts in Python and just add two roles.** Smallest change, but preserves the code-change
  requirement the user asked to remove, and leaves no reviewable file that lists the seeded set.
- **Second SQLite database for organisation profiles.** Splits the agent and role model in two for no
  gain: they already live in the registry, which every board-level decision already reads.
- **A new scope per agent instead of per role template.** The scope describes the job, not the
  instance; two Coordinators are still Coordinator-scoped, and a role edit should not have to be
  repeated per agent. An agent's scope therefore follows its role template (an override does not
  change it).
