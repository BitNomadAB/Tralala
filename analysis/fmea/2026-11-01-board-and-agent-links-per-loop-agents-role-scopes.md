2026-11-01

# FMEA: board and agent links, per-loop agents, role scopes

## At a glance

8 failure modes · 3 high-severity concerns · 5 recommended actions · ratings: not rated (no agreed scale or frequency data; severity described qualitatively)

- A board can end up created without the repositories and agents it was given, and nothing on screen says so, so its Loop analyses run with no code and no chosen agent (high · observed · F1).
- An organisation profile (Coordinator, Architect) can still run a Loop when the board lists no agents, so a Loop can be answered by a profile meant for the whole installation (high · observed · F2).
- A typo in the role seed file stops the process from starting, which is deliberate but means one data file gates every deployment (high · observed · F6).

## Scope and method

Software FMEA of the changes added since the 2026-11-01 Loop analysis: board↔repository and
board↔agent links (`registry/0009`, `registry/0010`), the per-Loop agent preference
(`board/0009`), role scopes and the role seed file (`registry/0011`, `app/seeds/role_seeds.json`),
and their reads on the board list, the Loop dialog and generation.

Functions reviewed: choose what a board is about; keep a Loop's agent choice; resolve the agent for a
run; seed and upgrade the registry. Evidence: source read in this session, the test suite, and the
local dev instance. Ratings: no agreed severity/occurrence/detection scale exists in the repository
and no incident or frequency data is available, so the table describes severity qualitatively and
leaves numeric ratings out rather than inventing them.

## FMEA table

| ID | Function | Failure mode | Effects | Causes | Existing prevention | Existing detection | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | Create a board with repositories and agents | The board row is committed but the link rows are not | Board looks configured, analyses nothing, runs with any agent | Links are written in a second transaction after `insert_board` (`services/boards.py::create`) | Ids validated before any write; links written right after the database is created | None: the response is computed after the links, but a crash between the steps leaves no marker | observed |
| F2 | Resolve the agent for a generation run | An organisation-profile agent runs a Loop | Off-target analysis, tokens spent on a whole-installation prompt | `_agent_row`/`_default_agent_row` filter on `enabled` and connection type only; the scope check exists for board selection, not for generation | Board membership is enforced when the board lists agents; the UI hides organisation profiles | Run snapshot records the agent name, but only after the fact | observed |
| F3 | Store a Loop agent preference | A preference points at an agent that was deleted, or that the board dropped | The run silently uses another agent | No foreign key by design (`board/0009`) | `_resolve_agent` falls back to the board default | None before the run; the run snapshot shows the agent that actually ran | observed (test) |
| F4 | Validate ids for board links | A check passes while a later insert fails | Nothing written (single transaction), error surfaces as 500 | `set_board_links`/`set_board_agents` delete and insert in one transaction | Validation before the transaction | Only the generic error envelope | inferred |
| F5 | Write a Loop's agent preference | A partial update clears a purpose the caller did not send | A stored preference disappears | An earlier full-replacement payload cleared everything | `model_fields_set` restricts the write to the fields sent | Test `test_a_loop_remembers_one_agent_per_purpose` covers clear-one-purpose | observed (fixed) |
| F6 | Start the process with a role seed | The seed file is malformed or missing | The installation does not start | Seed is a data file validated at import (`services/role_defaults.py::_load`) | Validation with an explicit message; the file ships with the source and the image | Startup fails loudly; `test_role_seeds` runs before release | observed |
| F7 | Upgrade a registry from `0010` to `0011` | `batch_alter_table` loses rows or agent references | Customized roles and agent assignments vanish | Table recreation is the documented SQLite path | No foreign key from `agents` to `role_templates`, so a drop cannot cascade | No upgrade-with-data test | inferred from code; untested |
| F8 | List boards for the dashboard | Counts for a board that cannot be opened are reported as zero | A broken board looks empty rather than broken | `_counts` swallows `NotFound`/`ServiceUnavailable` | Status filter and the migration banner on the board page | None at the dashboard level | observed |

## Priorities

High-severity concerns (worth acting on regardless of likelihood): **F1**, **F2**, **F6**.

- F1 and F2 share a cause: the write and read paths of board configuration are split, so a partial
  state has no marker and no filter refuses an unintended agent.
- F6 is deliberate (fail fast beats seeding half a set) but should be stated as an operational
  requirement, not left implicit.
- F3 and F5 are already controlled; F4, F7 and F8 are lower impact but F7 is the same failure class
  that produced a real data loss in `0009` earlier, so it belongs in the next test batch.

## Recommended actions

| Action | Targets | Expected effect | Status |
| --- | --- | --- | --- |
| Refuse an organisation-scope agent in generation, both for an explicit `agent_id` and for the default pick | F2 | A Loop can no longer be answered by a whole-installation profile | done in this round |
| Write the board's links in the same registry transaction as the board row (or mark the board until links exist) | F1 | A created board is either fully configured or visibly not configured | proposed |
| Add an upgrade-with-data test for `0011` (customized role + agent reference + board link) | F7 | An upgrade cannot silently drop role customization or agent assignment | proposed |
| State in `0013` that a malformed seed stops startup, and that the suite validates the seed | F6 | The operational requirement is explicit | done in this round |
| Keep the "one purpose at a time" write pinned by a test, and add a test that a dropped agent leaves a fallback that names the agent used | F3, F5 | The degraded path stays visible | existing tests |

## Assumptions and open questions

- No occurrence data exists (no incidents, no telemetry on failed creations), so likelihood is not
  rated.
- Whether a partially configured board is acceptable depends on the deployment: single-operator
  installations notice, automated ones do not. Confirm with the owner.
- F7 assumes SQLite's documented table-recreation behaviour; it should be proven by the proposed test
  rather than by reading the migration.
- A separate analysis should cover adversarial use of the repository token; this FMEA covers failure
  behaviour, not threat modelling.

## Status after this analysis

- **F1 fixed:** links are written before the board turns `active`, so an interrupted creation is
  visible as `maintenance` instead of a silently unconfigured board.
- **F2 fixed:** generation refuses an organisation profile, whether a run names one
  (`422 agent_scope_organisation`) or the default pick would choose one
  (`_agent_row(..., strict=False)` falls back, `_default_agent_row` filters the scope in SQL). Tests:
  `test_generation_refuses_an_organisation_profile`,
  `test_the_default_agent_skips_an_organisation_profile`.
- **F6 recorded:** `docs/decisions/0013` now states that a malformed seed stops startup on purpose and
  that the suite validates the same file.
- **F7 tracked:** the upgrade-with-data test now covers `0011` (customized role, agent reference and
  board link survive).
