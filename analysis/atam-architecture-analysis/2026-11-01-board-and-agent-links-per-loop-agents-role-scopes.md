2026-11-01

# ATAM Architecture Analysis: board and agent links, per-loop agents, role scopes

## At a glance

5 risks · 2 sensitivity points · 2 tradeoff points · 3 non-risks · provisional: yes

- Creating a board writes the board, then its repository and agent links in a second transaction, so a failure in between leaves a board that silently analyses nothing (risk · observed · F2).
- The dashboard list still opens every board database three times per board, which will dominate the board screen as soon as an installation has many boards (risk · inferred · F1).
- The role templates now ship as a seed file that is validated when the process starts, so a typo in that file stops the installation instead of quietly seeding an incomplete set (tradeoff · observed · F5).

## Scope and evidence

Delta evaluation of the architecture changes made since the 2026-11-01 ATAM of the Loop refactor:
registry revisions `0007`-`0011`, board revision `0009`, board↔repository and board↔agent links,
per-Loop agent preferences, role scopes and the role seed file.

Evidence read: `AGENTS.md` (architecture rules), `docs/architecture.md`, `docs/loops.md`,
`docs/decisions/0011`, `0012`, `0013`, the services `boards.py`, `agents.py`, `loop_agents.py`,
`loop_generation.py`, `repositories.py`, the routers, the migrations `registry/0007`-`0011` and
`board/0009`, and the test modules `test_board_agents.py`, `test_loop_agents.py`,
`test_role_seeds.py`. Ran: `pytest`, `ruff`, frontend `typecheck`/`test`/`build`, `test:e2e`, and the
local dev instance.

No stakeholder was available, so priorities below are repository-derived candidates and this
evaluation is provisional. Not measured: latency or statement counts on a large installation (the
board-count claim is inferred from the code path, not from a run with hundreds of boards).

## Business drivers and utility tree

Drivers from `AGENTS.md` and the decision records: self-hosted single-process deployment, one service
layer for every interface, a board as the storage boundary, credentials that never leave the registry
sealed, and a product that stays cheap to change (12 roles, six migrations and several endpoints in one
day).

| Attribute | Scenario (source → stimulus → response) | Priority basis |
| --- | --- | --- |
| Modifiability (high) | A developer adds a role profile or a generation purpose → one seed edit plus one service change → all suites stay green | The repository changed shape three times in one day; cheap change is the stated reason for the service layer |
| Security (high) | A token with `boards:read` calls every read endpoint → no credential, prompt or other board's configuration leaks | Scopes are enforced server-side by invariant; agents are first-class callers |
| Operability / reliability (high) | An operator upgrades a registry with customized roles → the upgrade keeps roles, agents and their links, and a failure leaves a marked board rather than silence | Migration Manager exists because upgrades are expected to run unattended |
| Performance (medium) | Opening the board dashboard with many boards → the page answers in bounded time | Single-process, per-request board opens; the dashboard is the entry screen |
| Governance (medium) | An administrator selects agents for a board → organisation profiles are refused, and every run names the agent and role snapshot it used | Profiles were added for cross-board oversight; mixing scopes would defeat that |

## Architecture and approaches

| Decision | Evidence | Rationale |
| --- | --- | --- |
| Links (board↔repository, board↔agent) are registry rows with cascades | `registry/0009`, `registry/0010` | Board metadata is registry data; one resource serves many boards |
| Board payloads carry `repository_ids` and `agent_ids`, read in one extra query per list | `services/boards.py::_repository_ids_by_board`, `_agent_ids_by_board` | Avoids per-board queries for the links themselves |
| Link writes happen after the board row exists, in their own transaction | `services/boards.py::create`, `update` | The board database must exist before a board can be configured; ids are validated first |
| Per-Loop agent preference is board-database data without a registry foreign key | `board/0009`, `services/loop_agents.py` | A board database must not depend on registry rows; a stale preference falls back |
| Enforcement sits in services, not routers or UI | `AgentService.validate_ids`, `LoopGenerationService._resolve_agent` | Interfaces call the same functions (invariant 1) |
| Role templates carry a scope and are seeded from JSON | `registry/0011`, `app/seeds/role_seeds.json`, `services/role_defaults.py` | Data change instead of a code change; scope decides board eligibility |
| Generation resolves agent = explicit → Loop preference → board default | `services/loop_generation.py::_resolve_agent` | Predictable precedence, one place to change it |

## Scenario analysis

| Scenario | Expected response | Response measure | Evidence and reasoning |
| --- | --- | --- | --- |
| Add a thirteenth role profile | Edit the seed file, restart, role is present with its scope | One file changed, no test edits | Observed: 12 roles load from JSON; `test_role_seeds` pins the count |
| Board with 3 repositories and 2 agents | `POST /boards` writes links, `GET /boards` returns both lists | Response includes both, statement count constant in the number of boards for the links | Observed: `test_board_agents`, `test_repositories` |
| Upgrade a registry from `0010` | Roles, agents, tokens and links survive; `scope` appears with `board` default | No data loss; `alembic_version` at `0011` | Observed for fresh databases only; **no upgrade-with-data test exists** (F3) |
| A token asks for a Loop's agents | Reads the preference under `loops:read` | 200 with ids | Observed against the dev instance |
| Organisation profile as a board agent | `422 agent_scope_organisation`, nothing written | One error code, no partial state | Observed: service check before the write |
| Dashboard with 40 boards | Page renders | Time and statement count | Not measured; the code path opens three statements per board (F1) |

## Findings

| ID | Type | Finding | Scenarios / attributes | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| F1 | Risk | The board list runs three count queries per board, so dashboard cost grows with board count | Performance, operability | `services/boards.py::_counts` called from `serialize` for every row | Medium (inferred from code, not measured) |
| F2 | Risk | Board links are written in a second transaction, so a crash between the two leaves a board that analyses nothing | Reliability, data integrity | `services/boards.py::create` (`insert_board`, then `set_board_links`/`set_board_agents`) | High (observed) |
| F3 | Risk | No test covers a registry upgrade from `0010` with customized roles, agents and links | Operability, data integrity | `tests/test_migrations.py` covers `0008`→head for repositories only | High (observed) |
| F4 | Sensitivity point | `AgentService.validate_ids` issues one query per id, and the loop-preference write validates each purpose | Performance (write path) | `services/agents.py::validate_ids` | High (observed) |
| F5 | Tradeoff point | Validating the seed at import makes a malformed file a hard startup failure, which is safe but couples startup to a data file | Reliability vs safety | `services/role_defaults.py::_load` raises `RuntimeError` | High (observed) |
| F6 | Sensitivity point | Scope eligibility is decided by the role template an agent points at, so deleting a template detaches agents and silently makes them board-eligible again | Governance | `services/agents.py::delete` sets `role_template_id = NULL`; `validate_ids` treats a missing template as `board` | Medium |
| F7 | Non-risk | Organisation profiles cannot reach a board: enforcement is in the service and covered by tests | Governance | `test_role_seeds.py::test_an_organisation_profile_is_not_a_board_agent` | High |
| F8 | Non-risk | A stale Loop preference falls back instead of failing the run | Reliability | `test_loop_agents.py::test_a_preference_for_a_deleted_agent_falls_back` | High |
| F9 | Non-risk | Board list link lookups stay constant (two queries) regardless of board count | Performance | `_repository_ids_by_board`, `_agent_ids_for_boards` | High |

Risk themes: **upgrade safety** (F3, F5) and **per-row work that scales with data** (F1, F4).

## Recommendations and open questions

1. **Add an upgrade-with-data test for `0011`** (F3): build a registry at `0010`, insert a customized
   built-in role and an agent pointing at it, upgrade to head, then assert the prompt, the agent's
   `role_template_id` and its board link survive and that `scope` is `board`. Cheap and it is the same
   failure class that already cost one migration.
2. **Make board creation atomic for links, or mark the board** (F2): either write the links inside the
   same registry transaction as `insert_board`, or set a status that the dashboard shows until links
   exist. The cheapest version is a single transaction, because links are registry rows too.
3. **Give the dashboard a statement budget** (F1): batch the counts (one query per board database is
   still one open) or cache them in the registry, then hold the result with a test like the Loop
   overview budget test.
4. **Decide what a missing role template means** (F6): today an agent whose template was deleted
   becomes board-eligible. Either treat a missing template as "no scope" (refuse) or state that a
   detached agent is board-scoped on purpose.
5. **Record the seed-file coupling** (F5): state in `0013` that a malformed seed stops startup, and
   that the file is validated by the test suite before a release.
6. Stakeholders must confirm the priorities: which quality attribute wins when the dashboard's cost
   and upgrade safety compete, and whether any token should ever see another board's configuration.

## Status after this analysis

- **F2 fixed:** board creation now writes the repository and agent links before flipping the board to
  `active`, so an interrupted creation leaves a board in `maintenance` (visible on the dashboard)
  rather than an active board that analyses nothing.
- **F3 fixed:** `test_registry_upgrade_keeps_customized_roles_and_agent_references` builds a registry at
  `0010` with a customized role, an agent pointing at it and a board link, upgrades to head and
  asserts all three survive with `scope = board`.
- **F1 and F4 remain open** (dashboard counts per board, per-id validation queries); both are recorded
  as work rather than closed, because closing them changes query shape and deserves its own change.
