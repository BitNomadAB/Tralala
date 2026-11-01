# Tralala: Loop-Based Planning, Delivery and History

**Product requirements and implementation specification - v1.0**  
**Prepared:** 2026-11-01  
**Repository:** `BitNomadAB/Tralala`  
**Reviewed baseline:** `50867258ad798f66773f45813014891fe4ec1af4` (`master` at review time)  
**Purpose:** An implementation contract for a coding agent working in the existing repository.  
**Project stage:** Early development. No production-data migration or backward compatibility is required for this redesign.

## 1. Objective and authoritative hierarchy

Evolve Tralala from board-level Kanban into a Loop-based workflow for planning, implementing and retaining the history of features. The workflow should support Ralph-style development without making project knowledge depend on disposable planning files in a repository.

The hierarchy is:

```text
App: Tralala and its overview of Boards
  Board: a project, application, or a defined part of an application
    Loop: one feature or coherent change initiative
      Kanban header
        Info
        Analysis        [human view, with access to AnalysisAI]
        RoadMap         [human view, with access to RoadMapAI]
        Loop status, approvals, progress and QA status
      Kanban
        Loop-owned columns
          Tickets
      Numbered delivery phases, represented in the RoadMap and on Tickets
```

**A Board contains Loops. A Loop owns its Kanban, columns, Tickets and planning documents.** Do not implement a single Board-level Kanban with Loops merely represented as labels or filters. Two Loops in the same Board must have independent columns and ordering.

"App" means the Tralala application shell and Board overview. It does not introduce an additional persisted project hierarchy or a new database. A Board remains the storage boundary: all of its Loops live in its existing SQLite database.

Example: the App contains a `MatchMap` Board. That Board contains separate `Email verification` and `Refund workflow` Loops. Opening either Loop displays that Loop's own Kanban and planning header.

### 1.1 Scope

Implement the hierarchy, human-authored input, AI and human planning representations, version-bound human approvals, phased Tickets, human intervention gates, QA handover, completed-Loop history, and a storage contract for future legacy imports.

Do not build a Jira clone, a generic autonomous coding platform, a repository crawler, a new model provider, or the future legacy import UI in this increment. Tralala coordinates work and records evidence; it does not gain repository, terminal or browser access merely because a model endpoint is configured.

### 1.2 Explicit implementation decisions

These decisions resolve details not fully specified in the product request:

| Topic | Decision for this implementation |
| --- | --- |
| `Analysis` input | The human-readable Analysis is derived from **AnalysisAI**, not from itself. |
| Empty Loop | All five planning documents begin empty. Creating a Loop does not call a model. |
| Human QA and AI QA | One logical QA Task with two synchronized instruction views and shared scenario IDs; not two unrelated tasks requiring duplicate testing. |
| Ticket references | Add a Board-local Loop sequence and a per-phase Ticket sequence to the requested name prefixes and phase number, preventing collisions. |
| Completion | Human acceptance of implementation and verified QA are separate decisions. Only QA-accepted completion creates a completed native history record. |
| Existing development data | A clean schema transition and an explicit development-data reset are acceptable. Do not build migration Loops, legacy workflow modes or data-conversion machinery for existing test data. |
| Legacy imports | Preserve original content in a standard historical envelope. Do not convert it into active Loops or pretend it conforms to the new workflow. |
| AI execution | Support existing configured generation capabilities and external agents using REST. Do not assume any particular external toolset. |

The user-facing requirements below are authoritative. Proposed table and service names may be adjusted to repository conventions, but observable behavior, ownership, approval rules and the integrity of newly created Loop history may not be weakened.

## 2. Existing implementation: reuse rather than replace

The reviewed repository contains more functionality than some README limitations suggest. Its source and current migrations take precedence over stale documentation.

| Existing implementation | Required treatment |
| --- | --- |
| React, TanStack Query, typed API client, drag-and-drop Kanban, reusable dialogs and theme kits | Reuse. Adapt the current Kanban to a Loop context. [R1, R7] |
| FastAPI routers, Pydantic schemas and shared service layer | Add Loop behavior in services, consumed consistently by REST, the UI and WebMCP. [R1, R2] |
| Registry database and one SQLite database per Board | Preserve. Do not create a database per Loop or introduce PostgreSQL, Redis or a broker. [R1, R3] |
| Cards, labels, checklists, assignments, comments, activity and attachments | Extend existing cards to serve as Tickets. Do not build a competing Ticket CRUD stack. [R3, R4] |
| Agents, role templates, encrypted provider credentials and role snapshots | Reuse for generation. Preserve provider and role provenance. [R1, R2] |
| Ticket discussions, discussion runs, mention jobs, durable events and in-process executors | Preserve. Reuse appropriate infrastructure and recovery patterns; do not force Loop documents into fake Tickets. [R1, R8] |
| Version checking, idempotency, scopes, sessions, CSRF and structured errors | Preserve and extend to new workflow transitions. [R2, R4, R9] |
| Alembic migrations, verified backups, Board export/import, duplication and search | Extend coverage to Loop data. Audit behavior rather than assuming it automatically covers new resources. [R3, R10] |

Important source-level constraints:

- Existing lists belong directly to a Board database, and their queries and ordering are Board-wide. Add explicit Loop ownership and scope these operations accordingly. [R5]
- Existing card movement does not itself mark a card completed. `completed_at` is managed separately. Preserve that distinction unless a separately approved workflow change is introduced; do not infer completion from a column called `Done`. [R4]
- Existing discussion orchestration expects a Ticket and builds bounded text context. It is not a Loop planning engine. [R8]
- The reviewed agent runtime sends chat-completion requests. A configured A2A connection or successful connection test does not establish that the runtime can execute an A2A task, inspect a repository, or run tests. Unsupported execution capabilities must be reported explicitly. [R6]
- Board export and duplication currently snapshot the database. Existing attachment storage and asset handling must be checked separately before claiming a portable, complete export. [R10]

Read `AGENTS.md` before implementation. Do not modify licensing files or introduce unrelated architectural changes. Compare the actual checkout with the reviewed commit before starting. This specification is based on inspection, not on a claim that the baseline test suite was executed during drafting.

## 3. Navigation, ownership and presentation

### 3.1 App and Board views

The App home remains the Board overview. Opening a Board shows its Loops, not a Kanban. Each Loop entry shows its name, broad goal, workflow stage, approval or stale-document warnings, Ticket progress, outstanding human work and QA status.

Provide active and historical views within the Board. Completed Loops are reachable through Board history; pending QA must remain visible as unfinished work rather than disappear into completed history.

Recommended routes:

```text
/boards
/boards/:boardId
/boards/:boardId/loops/:loopId
/boards/:boardId/history
/boards/:boardId/history/:historyId
```

Retain existing navigation to Settings and Discussions. Discussion and search results must identify the owning Board and Loop and open the correct Ticket. Update deep links to include the owning Loop. Compatibility redirects for the previous Board-Kanban routes are not required.

### 3.2 Loop Kanban

The Loop page contains a persistent or sticky header above its own Kanban. The primary document controls are **Info**, **Analysis**, and **RoadMap**. Analysis and RoadMap each offer a secondary technical/AI view. AI documents must remain inspectable, but need not occupy the primary reading experience.

Opening a document uses a suitable large modal or side panel. Keep revision, source validity, approval status and available actions visible. The user must be able to inspect all planning sections regardless of the current workflow stage. Empty sections display an empty state, not fabricated content.

The Kanban contains only actionable Tickets, including a QA Task when one exists. Info, Analysis, RoadMap and Phases must never appear as pseudo-Tickets. Phases are planning groups, not Kanban status columns.

Use existing themes and semantic color variables. Modal keyboard navigation, focus restoration, screen-reader labels and status communication must work without reliance on color.

### 3.3 Columns, labels and templates

Columns belong to a Loop. Ordering, card counts, archived-column queries, reorder normalization and drag-and-drop must be scoped to that Loop. A normal drag operation cannot move a Ticket into another Loop.

Board-level labels may remain shared vocabulary within that Board. A label does not determine Loop ownership.

Retain existing reusable templates. Their column definitions become defaults for **new Loop Kanbans**. Selecting a template when creating a Board stores a snapshot of its Loop defaults; it must not create ownerless columns. Creating a Loop copies those defaults into Loop-owned columns. Template edits affect future instantiations only. Saving a layout as a template must identify the source Loop rather than merge columns from every Loop in a Board. Preserve Board description and label behavior where applicable.

A newly created Board may contain zero Loops. A newly created Loop receives default columns but no Tickets and no generated planning content.

## 4. Planning documents

### 4.1 Shared document contract

Each Loop has five document slots: `info`, `analysis_ai`, `analysis`, `roadmap_ai`, and `roadmap`. An empty slot has no authored revision yet; a stable empty response is sufficient. Do not create fake human or AI revisions during Loop creation.

Persist immutable content revisions with document kind, revision number, content, content hash, creation time, authenticated author/provenance, source revision IDs and any generation-run reference. Keep current and approved pointers separate. Do not overwrite a previous revision to make an audit trail look current.

Store machine-oriented structured payloads where required and human-readable Markdown where appropriate. Markdown is rendered through the existing safe renderer. Documents, URLs, imported text and model output are untrusted content, not executable instructions.

Expose meaningful statuses such as `empty`, `draft`, `ready_for_review`, `approved`, `changes_requested`, and `stale`. Generation progress and failure belong to the generation run; a failed attempt must not replace a valid document with an empty or half-written one.

### 4.2 Info: human-authored intent

Info is the human's collection of notes, requirements, URLs, observations, constraints and desired outcomes. It begins empty even when the Loop has a name and a short goal.

Only an authenticated human user may create or revise Info through the supported workflow. Agents may read it but may not modify it, append to it, summarize it in place or silently "clean it up." An agent's suggested clarification is returned separately for a human to consider.

The system cannot determine whether pasted prose was composed with outside assistance. The enforceable rule is that Tralala's agents cannot write Info and its saved revisions record a human action.

Save changes as revisions. Any change to the effective input invalidates dependent approvals as specified in section 5. URLs are references; saving a URL does not automatically authorize a crawl or send its contents to a model.

### 4.3 AnalysisAI: technical findings and implementation assessment

AnalysisAI is primarily consumed by agents. Humans can inspect it when necessary. It begins empty and is produced from the current Info revision plus explicitly available project context.

Its structure must cover:

- The requested outcome, scope and non-goals, with traceability to Info.
- What already exists, what can be reused and what must change.
- Relevant architecture, modules, data structures, APIs and migration considerations.
- Dependencies, practical limitations, security and privacy concerns, and potential licensing or other legal conflicts supported by the available evidence.
- Contradictions, open questions, assumptions and missing access or missing information.
- Implementation options, the proposed direction and how success can be verified.

Assign stable finding IDs within the analysis revision so the human summary can reference their coverage. Record evidence sources with available repository revisions, file references, URLs or supplied excerpts. Distinguish observed facts, reported evidence, assumptions and recommendations.

Do not claim that a model inspected a repository or checked a legal constraint when the relevant evidence was not available. Unresolved legal questions are flagged for human review, not reported as legal clearance.

### 4.4 Analysis: plain-language decision support

Generate Analysis from a specific AnalysisAI revision. Write for a project manager with no technical background: direct language, short explanations, no unexplained jargon, code symbols or source-file paths in the main narrative.

Explain what was found, what can be reused, what must change, what may be difficult, which decisions are needed, and whether the request conflicts with the project's goals or known practical or legal constraints. Do not hide a serious risk just because its technical details are omitted.

Every material finding and unresolved blocker in AnalysisAI must be represented in the human view, with traceability metadata available behind the interface. Structural coverage can be validated; the application must not pretend that a schema validator proves the semantic quality of a summary.

A human can accept the presented analysis pair or request changes with feedback. Acceptance approves the exact Info, AnalysisAI and Analysis revisions presented. RoadMapAI generation is blocked until that approval is current.

### 4.5 RoadMapAI: structured delivery plan

RoadMapAI begins empty. Generate it only from a currently approved analysis pair and its input revision.

It contains numbered, named Phases and concrete planned Tickets. Each Phase defines its intended outcome, entry conditions, exit conditions and dependencies. Each planned Ticket includes its stable identity, title, Phase, objective, actionable instructions, prerequisites, acceptance criteria, expected evidence and whether a human is required.

Technical details may include files, APIs, data migrations and tests where supported by the analysis. Clearly distinguish implementation steps from research still required. Allocate human work explicitly rather than asking an AI to assume that an external account, approval or physical action has been completed.

Use a validated structured schema as the authoritative plan representation. Do not make executable dependencies or approval decisions depend on parsing arbitrary Markdown.

Draft planned Tickets are not yet live Kanban cards. Reserve their stable identities so RoadMapAI, RoadMap and later cards refer to the same items.

### 4.6 RoadMap: the human-readable delivery plan

Generate RoadMap from the exact RoadMapAI revision. Present the same Phases, Ticket references, order, dependencies and human interventions without implementation jargon.

For every Phase, explain what will change, which Tickets it includes, what should work when it is complete, what must happen first and what could prevent progress. Human intervention and its downstream consequences must be especially visible.

The human view and the AI view must have matching Phase and Ticket identities. The model must not introduce, omit or reorder work only in the human summary. Render structural facts from the validated plan and add plain-language explanations around them.

A human must accept the exact RoadMapAI/RoadMap pair. Acceptance publishes or updates the live Tickets atomically. Discovering a wrong assumption or technical limitation at this stage is expected: the user can request changes, update Info or revise the analysis, and regenerate affected downstream documents.

## 5. Approval, revision and lifecycle rules

### 5.1 Approval is a recorded human decision

Store approval records separately from generated content. Each decision includes the authenticated reviewer, timestamp, decision, optional feedback, exact document revision IDs and source hashes.

The server must enforce human-only decisions. An agent token cannot approve Analysis, approve RoadMap, confirm completion of a human-only Ticket, accept QA or finalize a Loop, even if it can generate documents or update other Tickets. Never trust `approved_by`, `actor_type`, `qa_passed` or similar identity assertions supplied in a request body.

Use the existing human identity and session checks, with additional authentication provenance if needed. Human-only workflow actions must not be exposed as autonomous WebMCP tools. Ordinary signed-in members may make project decisions; installation administrator status is not required unless an existing permission explicitly requires it.

A session and confirmation action establish the authorized user action; they do not technically prove that a person, rather than browser automation using that session, physically clicked a button. Do not claim stronger human detection than the application provides.

### 5.2 Invalidation rules

| Change | Required consequence |
| --- | --- |
| Info revision or explicitly selected project-context input changes | Analysis and both RoadMap views become stale; their approvals no longer authorize new execution. |
| AnalysisAI changes | Analysis must be regenerated or revised consistently; analysis approval and downstream RoadMap approval become stale. |
| Analysis changes substantively | The analysis pair needs approval again; a dependent RoadMap must be reviewed against the new approved basis. |
| RoadMapAI changes | RoadMap becomes stale; the revised plan cannot be published without fresh approval. |
| RoadMap changes substantively | The plan pair needs fresh approval. Structural changes must also exist in RoadMapAI. |
| Ticket scope, dependencies or acceptance criteria change | Treat as a plan amendment, not an unrestricted card edit. |
| Execution evidence, comments or checklist progress change | Preserve the approved plan; record execution activity and invalidate any already-prepared completion/QA snapshot that depends on changed results. |
| Cosmetic Loop name change | Keep identifiers unchanged; do not invalidate the plan solely because the display name changed. |

Do not silently promote a newly generated document over an approved one. Display the current candidate and approved baseline distinctly. Revision history remains readable even when a revision is stale.

External repository changes cannot be detected magically. Record the repository revision supplied with the analysis. When a user or agent reports a changed relevant baseline, require revalidation; do not imply continuous repository monitoring.

### 5.3 Workflow stages

The UI may derive stage labels from persisted state, but must support these distinctions:

| Stage | Meaning and allowed next action |
| --- | --- |
| Draft | Loop created; human gathers Info and supplies context. |
| Analysis review | Current AI and human analysis views are available; human accepts or requests changes. |
| Planning | Analysis accepted; a RoadMap may be generated. |
| RoadMap review | Current plan pair awaits human approval. No planned Tickets are executable yet. |
| Ready | Approved plan published to the Loop Kanban. |
| In progress | Delivery Tickets are being executed. |
| Replanning | Previously published work exists, but changed requirements or requested changes require renewed approval. |
| Awaiting QA | Human accepts implementation as ready, but QA is outstanding, incomplete or unsuccessful. |
| Completed | Human accepts QA and completion; a historical snapshot has been committed. |
| Cancelled | Work was explicitly abandoned; this is not successful completion. |

Generation jobs have their own queued/running/failed/completed states. A provider failure must not put the Loop into a misleading approval or completion state.

Creating a Loop, approving Analysis and receiving a model answer must not silently start implementation. Initial RoadMap approval materializes Tickets; execution remains an explicit action by a human or external agent.

### 5.4 Replanning after work has started

Once a published plan is challenged or its required input changes, block new starts and completion transitions for affected delivery work until a replacement plan is approved. For this release, freezing execution transitions for the entire Loop is an acceptable conservative implementation. Continue allowing inspection, feedback and the recording of results from work already underway.

Show a change preview: added, changed, retained and superseded Tickets; changed dependencies; and completed work that needs revalidation. Retain UUIDs, keys, comments, attachments, assignments and evidence for unchanged Tickets. Do not delete completed work because a model omitted it from a replacement draft.

Scope changes on completed Tickets must produce an explicit human-reviewed disposition: retain the completion, reopen for revalidation, or supersede with a linked replacement. Preserve the prior completion in the audit trail. Materialized Tickets removed from scope remain traceable; archiving alone is not approval to remove required work.

Publish the approved replacement and its Ticket changes in one Board transaction. A partial plan must never become active.

## 6. Phases, Ticket identities and plan publication

### 6.1 Stable references

Use UUIDs internally. Human-readable Ticket keys supplement UUIDs; they do not replace ownership checks or authorization.

Recommended format:

```text
<LoopPrefix><LoopSequence>-<PhasePrefix><PhaseNumber>-<TicketSequence>

AC004-DA02-003
```

This example represents Loop `Account login`, Board-local Loop sequence `4`, Phase `Database update`, phase number `2`, and Ticket `3` within that Phase.

Prefixes use the first two normalized alphanumeric characters of the corresponding name. Normalize case and accents; for an empty ASCII result use `LP` or `PH`, and pad a one-character result with `X`. Keep the algorithm deterministic. Sequence widths are minimum display widths, not maximum values.

The Board-local Loop sequence prevents collisions between Loops with the same initial letters. The Ticket sequence distinguishes multiple tasks within a Phase. Allocate these values transactionally in the server, not in model-generated prose. Never reuse an allocated reference, including one reserved for a discarded plan candidate.

Freeze references after allocation. Renaming a Loop, Phase or Ticket does not rename its existing keys. Phase numbering is a stable reference; execution order is defined by the approved dependency graph. Moving an already-published Ticket to a fundamentally different Phase requires a reviewed plan amendment and must not silently recycle its identity.

Draft plan revisions must carry stable Phase and Ticket UUIDs. A regenerated draft can retain identities through explicit mappings to earlier entries; it must not guess identity solely from similar text. A new item gets a new identity.

Ticket keys are unique within their Board. APIs, cross-Board search and history links qualify them with Board identity. Imported history may retain foreign or duplicate original keys without turning them into active native keys.

### 6.2 Structured plan contract

Version the plan payload independently from the database migration version. A minimum RoadMapAI payload contains:

```text
schema_version
loop_id
source_info_revision_id
source_analysis_ai_revision_id
source_analysis_revision_id
phases[]
  id, number, name, objective, entry_conditions, exit_conditions
  prerequisite_phase_ids[], prerequisite_ticket_ids[]
  tickets[]
    id, key, title, objective, instructions
    required_actor: any | human
    execution_mode: normal | pre_phase_gate
    prerequisite_phase_ids[], prerequisite_ticket_ids[]
    acceptance_criteria[], expected_evidence[]
    human_action_reason, human_instructions (when applicable)
```

Additional fields may cover priority, labels, estimates or context references when justified, but do not introduce unrelated scheduling or resource-management features.

Validate membership, uniqueness, references, dependency acyclicity, required human instructions and correspondence with the human view before exposing a plan for approval. Invalid output remains a failed draft and creates no live cards.

### 6.3 Atomic Ticket publication

On initial RoadMap approval, recheck the exact source revisions, Loop version and authenticated reviewer, then commit the approval, active plan reference, dependencies and all live Tickets atomically.

Create live cards using the previously allocated UUIDs, keys and approved titles. Reuse existing checklist, label, assignment, comment and attachment capabilities. Store a link from each Ticket to its plan item and source plan revision.

Do not use a bulk-create path that permits partial success for this operation. The reviewed bulk-card path supports partial failures; plan publication requires an all-or-nothing transaction instead. [R4]

Use an idempotency key and durable uniqueness constraints. Repeated approval requests, client retries or restart recovery must not create duplicate Tickets, decisions or plan activations.

## 7. Ticket execution and dependencies

### 7.1 Ticket contents and existing behavior

A Ticket is an extension of the existing card resource. It includes the stable key, name, owning Loop, Phase, instructions, acceptance criteria, prerequisites, blocking information and execution evidence. Preserve existing Markdown descriptions, checklists, labels, priority, due dates, comments, discussions, attachments, assignment, activity, completion and version-conflict behavior.

Separate approved work definition from mutable execution data. An agent may record results and move an eligible Ticket through the Kanban, but must not rewrite the approved scope or bypass dependencies through any retained card endpoint.

Card completion remains explicit through `completed_at`; a column name or position is not evidence of completion. Do not assume that the final column means Done. The API must expose server-computed readiness and blocker reasons. Any explicit start operation, an agent request for executable work, and every completion transition must enforce the same readiness rules. Moving a blocked Ticket visually must not make it executable or completed.

A Ticket archived while still required is not completed. Hiding a card cannot unblock a Phase or permit Loop finalization.

### 7.2 Human-only work

A Ticket requiring a human displays a recognizable person/stick-figure icon and the text `Human action required`. Use a theme-compatible light blue or yellow accent distinct from normal Ticket surfaces; preserve readable contrast in all existing themes. Color is supplementary, not the only indication.

Its detail view states why a human is needed, exactly what the person must do, what must be completed first, which Phase is blocked and the downstream impact. An agent may prepare instructions or record a request for assistance but cannot confirm that the required human action occurred.

For example:

> This action can be performed after Phase 2 is complete. Phase 6 and its dependent phases cannot start until a human confirms that this action is complete.

Render this explanation from structured dependencies, with optional additional instructions. Do not rely on a free-text sentence as the blocking mechanism.

### 7.3 Phase readiness and pre-phase gates

By default, generate a sequential Phase plan unless analysis justifies parallel work. Persist explicit dependency edges rather than infer dependencies from numbers or names. Phase completion is derived from required Ticket dispositions and explicit exit conditions, not a free-form model assertion.

Support both Ticket-to-Ticket prerequisites and Phase completion as a prerequisite. Phase entry may depend on other completed Phases and on specific human or machine Tickets.

The example above must not create a deadlock or unnecessarily block Phases 3-5. Model that human action as a **pre-phase gate for Phase 6**, available after Phase 2. Its own readiness does not require Phase 6 to have started. Phase 6 entry depends on the gate and its other prerequisites. Ordinary Phase 6 Tickets wait for Phase 6 entry; the gate does not wait on itself.

A complete cycle check must include implicit ordinary Ticket-to-Phase-entry relationships as well as explicit edges. Reject self-dependencies, cross-Loop edges, missing references and indirect cycles. This increment does not implement cross-Loop or cross-Board dependency graphs.

Show direct blockers and explain downstream impact separately. "All later phases" is true only where the dependency graph actually propagates that block.

### 7.4 Reopening and plan changes

Reopening a prerequisite recomputes readiness. Previously completed dependent work remains recorded, but its validity must be flagged for review rather than silently treated as newly verified. Affected QA results are invalidated. Require human disposition before final completion.

Cross-Loop or cross-Board drag-and-drop is not supported. Remove or disable direct transfer of planned Tickets with an actionable error: use a reviewed plan amendment and explicit destination creation instead. There is no legacy-card exception. Never copy unresolved foreign dependencies into another Loop.

## 8. Completion and QA

### 8.1 Human implementation acceptance

When the human considers the feature implemented, offer a completion review showing required delivery Tickets, unresolved blockers and known risks. Only a human can accept implementation as complete.

Ask whether QA has been performed successfully. Distinguish `not tested`, `tested with failures or incomplete coverage`, and `passed` rather than treating any test activity as success.

If QA already passed, capture a human attestation identifying what was tested, the relevant build or environment when known, results and any supporting evidence. Do not claim automated verification when this is a human attestation. Finalize only when all completion conditions hold.

If QA is absent or unsuccessful, keep the Loop in `Awaiting QA` and create or reuse its QA Task. Do not create a native completed history record yet.

### 8.2 One QA Task, two instruction views

Create one logical QA Task with an AI-oriented view and a human-oriented view. Both refer to the same scenario IDs and expected behavior. Completing two duplicate tasks must not be required simply because there are two audiences.

The Task uses existing card infrastructure with `kind=qa`. It may belong to a separately marked, numbered verification Phase appended after delivery planning. This is a QA addendum, not an invisible rewrite of the approved delivery RoadMap. Allocate its key through the same identifier service. Exclude the QA Task from the delivery-complete precondition to avoid a circular completion gate.

Use a unique constraint for the Loop's active QA cycle. Repeated completion attempts reuse that cycle instead of producing duplicate Tasks. On a new QA cycle, retain earlier instructions and results as history.

Generate QA instructions from the approved requirements, RoadMap, actual delivery results, known risks and changed functionality. Include happy paths, relevant failure paths and regression checks. Do not fabricate test results during instruction generation.

The completion request may commit a QA Task in `instructions_pending` state plus a durable generation job. If generation fails, retain the Task and display a retryable failure. It is not ready for execution until both views are valid and correspond to the same scenario set. Starting a new generation must not destroy a previous valid instruction set.

### 8.3 AI-oriented QA instructions

Describe behavior to verify, setup and prerequisites, scenarios, expected results, evidence to capture and reporting requirements. The external agent must discover or state which of its own tools are available.

Do not assume a particular browser automation tool, shell, test framework, repository mount or model provider. Distinguish a suggested command from an executed command. If a required capability or environment is missing, report the relevant scenario as blocked or not executed; never infer a pass from the absence of an error report.

No arbitrary code execution is added to Tralala's backend by this feature. External agents execute in their own authorized environments and submit results through the API.

### 8.4 Human-oriented QA instructions

Provide short numbered steps describing what to open, what action to perform and what visible result to expect. Include prerequisites and test data only when known. Missing URLs, credentials or environment details must be called out, not invented.

Use plain language. Example:

```text
Scenario QA-03: An expired confirmation link
1. Open an expired confirmation link supplied for this test.
2. Confirm that the page explains that the link has expired.
3. Request a new confirmation link.
4. Confirm that the new link lets you complete the process.
Expected result: The expired link is rejected, and a new link can be used.
```

### 8.5 Results and final acceptance

Store scenario-level outcomes such as `passed`, `failed`, `blocked`, `not_run` and `not_applicable`, with reasons, evidence, actor, timestamp, tested baseline and QA instruction revision. Agents may submit results; a human accepts the QA result set and final completion.

A required failed, blocked or not-run scenario prevents QA acceptance. A human may approve a justified `not_applicable` disposition, recorded explicitly; this must not be an agent-controlled blanket waiver.

Fixes after QA invalidate affected results. New scope requires a plan amendment; a failed acceptance criterion on existing scope may reopen the existing Ticket with its previous evidence retained. Finalization requires results matching the current delivery baseline.

Commit the final human decision, immutable history snapshot and completed Loop state in one transaction. In-flight generation or agent jobs must not be allowed to mutate the captured baseline afterward. Repeated finalization requests return the existing record.

## 9. Standardized Board-local history

### 9.1 Native completed Loops

Store completed native Loops in a dedicated `loop_history` table inside the owning Board database. Completion is not implemented by dumping a Markdown file into the project repository or simply hiding the live Tickets.

The history record is an immutable, versioned snapshot that can be understood without joining mutable current documents or live agent configuration. Keep the completed Loop read-only and remove it from active-work views by default. Do not delete its live rows during finalization.

The snapshot includes:

| Area | Captured information |
| --- | --- |
| Envelope | History schema version, record ID, source kind, original Board/Loop IDs, Loop key and name, timestamps and content hash. |
| Intent and analysis | Info and analysis revisions used, relevant revision history, findings, sources, assumptions and decisions. |
| Plan | Approved RoadMapAI and RoadMap, Phases, Ticket identities, dependencies and approved amendments. |
| Delivery | Ticket definitions, final dispositions, execution evidence, relevant comments, checklist outcomes and activity. |
| Human decisions | Approval records, human intervention confirmations, completion reviewer and QA acceptance. |
| QA | Instruction revisions, scenarios, results, evidence and tested baseline; distinguish reported automated results from human attestations. |
| Generation provenance | Agent/model identifiers, role/prompt snapshots and run metadata needed to explain the artifacts, excluding secrets. |
| Assets | Attachment/evidence manifest with filenames, media types, hashes and explicit inclusion status. |

Textual historical content must be self-contained. Required binary QA evidence and raw imported files can be stored in a Board-local `loop_history_artifacts` table as bounded BLOBs with hashes, making them part of the database snapshot. Preserve original bytes. Do not silently omit required evidence, nor assume that a mutable filesystem link is an immutable historical record.

If existing external attachment storage is reused instead, implement retention and portable backup/export support for those referenced bytes. A database-only snapshot is not proof that external assets have been preserved. The finalization preview must disclose any intentionally excluded optional assets.

Finalization is atomic and idempotent, with a uniqueness constraint preventing duplicate completion snapshots for the same finalized Loop. A history content hash checks integrity, not whether the recorded claims are true.

Completed history is immutable until explicit permanent deletion of its owning Board under the existing safety model. A future reopening feature must create a new working revision or linked Loop without modifying the original snapshot; reopening is not required in this release.

### 9.2 History browsing and search

Provide a Board history view with full-text search and filters for source kind, Loop name/key, completion or import date and QA provenance. Search must cover useful document text, decisions and Ticket references, not only the Loop title.

Reuse the existing FTS5-with-fallback approach. Index a derived textual projection of historical content; do not require embeddings, a vector database or a model call. Provide pagination and report the actual search engine. Optional App-wide history search must query Boards through existing authorization boundaries, not copy all history into the registry.

A result opens a read-only historical view with its source and QA status clearly visible. Do not mix historical Tickets into an active Loop Kanban.

### 9.3 Future imported legacy Loops

Prepare the storage model and internal service contract for legacy import, but do not implement a filesystem scanner, external-format converter or import wizard in this release.

Use the same historical envelope with:

```text
source_kind = imported_legacy
conformance = legacy_unvalidated
imported_at
imported_by
source_project / source_reference, when supplied
source_format / source_version, when known
raw_artifact_manifest
reported_metadata
validation_warnings
qa_status = unknown, unless a separately identified assessment exists
```

Store original files or text without rewriting them to the native plan schema. Missing sections remain missing. Preserve original identifiers as source data; they do not need to satisfy native key rules.

Distinguish claims inside the imported material from verification performed by Tralala users. A legacy file saying "QA passed" is reported source information, not automatically a verified native QA result.

Every imported result and detail view shows `Imported legacy reference - may not follow the current standard`. Imported entries never create executable Tickets, trigger agents, acquire approvals, or appear as newly completed native Loops.

The import service contract must support bounded payloads, source metadata, artifact hashes and idempotent ingestion. It validates the envelope and safe storage, not the source's compliance with the new workflow. Test it with fixtures now so a future importer has a stable destination.

## 10. Persistence and consistency

### 10.1 Ownership and logical resources

Retain `registry.sqlite` for global Board metadata, accounts, credentials, agents and templates. The following resources belong in `boards/{board_uuid}/board.sqlite`:

| Resource | Minimum purpose |
| --- | --- |
| `loops` | UUID, name, goal, stable sequence/key, lifecycle, active document/plan references, version and timestamps. No legacy workflow mode is required. |
| `loop_documents` | Immutable content revisions, kinds, Markdown/structured payload, source revision IDs/hashes, authorship and generation provenance. |
| `loop_approvals` | Append-only human decisions bound to exact revisions and authenticated actors. |
| `loop_phases` | Stable Phase identities, numbers and identifier allocation state. |
| `loop_plan_items` | Reserved planned Ticket identities and keys, retained across drafts and materialization. |
| `loop_dependencies` | Validated, revision-bound projection of the structured plan's dependency graph. |
| `loop_generation_runs` | Durable generation state, captured inputs, model/role provenance, budgets, attempts, output references and failures. |
| `loop_qa_cycles` / `loop_qa_results` | Paired instruction revisions, scenario outcomes, delivery baseline and human QA decisions. |
| `loop_history` | Immutable native-completion and imported-legacy envelopes and searchable metadata. |
| `loop_history_artifacts` | Original bounded bytes and integrity metadata when self-contained artifact storage is used. |

Extend `lists` with non-null `loop_id`. Extend `cards` with non-null `loop_id` and the relevant Phase, plan-item, Ticket-key, kind, execution-mode and human-action fields. Keep UUID primary keys as the internal identity mechanism. A card and its list must belong to the same Loop; enforce this with database constraints where feasible, not only UI checks.

Add a snapshot of default Loop column configuration to Board-local metadata. Existing shared labels can remain unchanged.

The structured RoadMapAI revision is the authoritative planned content. Relational plan/dependency rows are identities or validated projections, not independently editable competing copies. Live cards are the execution projection of an approved plan.

Ticket discussions remain tied to real Tickets. Resolve their Loop through the Ticket. A Loop planning run does not require a fake card or a generic reimplementation of Discussions.

### 10.2 Transactions, concurrency and authorization

All new mutations use the existing service layer and Board authorization. Validate Board, Loop, Phase, list and Ticket ownership at the server boundary. Reject mismatches rather than trusting a route or request body.

Use optimistic versions for editable Loop state and expected revision IDs for document and approval operations. Return a structured `409` on stale writes. Recheck dependencies and approvals in the same transaction that changes execution state, avoiding check-then-write races.

Add idempotency to Loop creation, generation requests, plan publication, QA-cycle creation, finalization and future history ingestion. A reused key with a different request fingerprint remains an error. Uniqueness constraints must protect against duplicates even after an idempotency record expires.

Do not hold a Board transaction or lock open while waiting for a model response. Capture inputs, perform the external call, then acquire a transaction and verify that the result still matches the intended revisions. Persist stale results for inspection when useful, but do not activate them.

New immutable snapshots must not depend on mutable actor or agent names for historical display; retain display-name/provenance snapshots. Registry identities cannot be represented as SQLite foreign keys into another file.

History must not cascade away when a live Ticket, list or draft plan item is removed. Completed Loop data is read-only through every mutation path, including subresources and any retained alternative endpoints. Board-level physical deletion remains an explicit exception governed by the existing confirmation and authorization rules.

### 10.3 Events and recovery

Reuse existing durable-event patterns where applicable. Emit Loop document, review, plan, readiness, QA and completion events only after the corresponding transaction commits. Frontend events invalidate queries; fetched state remains authoritative.

Extend SSE scope support cleanly if Loop events are added. Maintain reconnect/replay behavior and polling fallback. Do not introduce a broker solely for this feature.

At startup, reconcile interrupted Loop-generation work using the existing run-recovery principles. Interrupted requests must not leave a permanently locked Loop, an approval falsely marked complete, or a half-published plan. Mark interrupted external calls failed/retryable rather than blindly repeating a call with unknown outcome.

Board restore, deletion and duplication must coordinate with running jobs. A job captured before a restore must not write its old result into the restored state merely because a revision number happens to match; use a runtime/database incarnation guard or equivalent cancellation-and-drain protection.

## 11. Generation and external-agent contract

### 11.1 Reuse configured agents

Use existing agent configuration, sealed credentials, role templates and provider-call support. A specific model name is not part of this product contract. The coding agent implementing Tralala and the agents later used inside Tralala are separate concerns.

Provide explicit generation actions for analysis, RoadMap and QA. Each workflow may produce its technical and human documents in sequential bounded calls. Validate the technical output before generating its human representation. Publish a coherent candidate pair only when both are valid.

Persist the effective role/prompt snapshot, agent/model identity, generation purpose, input hashes and available usage data. Do not reread a live role template to reconstruct a past run.

The reviewed runtime is discussion-oriented. Factor reusable provider invocation from discussion verdict extraction rather than forcing planning output to contain `AGREE`, `DISAGREE` or `ABSTAIN`. Preserve existing discussion behavior. Report unsupported connection/execution types clearly; do not silently send an A2A configuration to an unrelated chat route. [R6, R8]

### 11.2 Context and evidence

Expose a versioned Loop context resource for external agents. It contains permitted current documents, approved plan references, relevant Ticket context, blocker information and required output schemas. It must never expose provider credentials or unrelated Board data.

In-app generation uses only context actually supplied to it. External coding agents may inspect their own authorized project checkout and submit analysis or plan candidates with source references. Such submission records the authenticated submitting agent and separates reported evidence from independently validated facts.

Make missing or omitted context visible. Do not silently truncate a large analysis or RoadMap and then treat the output as complete. Use bounded sections, pagination and explicit included/omitted source manifests. Never load every historical Loop into every prompt.

### 11.3 Bounded, validated output

Define strict Pydantic schemas for machine output. Reject malformed identifiers, unknown fields where appropriate, excessive sizes, broken references, invalid dependencies and mismatched source revisions before materialization.

Model providers need not support a particular structured-output extension: the adapter can request a schema-shaped payload and validate the returned content. Any repair retry must be bounded, for example at most two repairs under the same total budget. Persist a clear failure if validation still fails.

Keep wall-time, output-size and available token limits. Do not invent token counts when a provider supplies no usage data; apply time and output bounds regardless. Provide cancellation and retry without duplicate publication. No unlimited autonomous repair loops.

A plan contains intended work, not proof of executed work. Generation runs must never mark implementation or QA as passed solely because the generated document says so.

## 12. API and WebMCP changes

Retain the `/api/v1` envelope, pagination, authentication and structured errors. Recommended resource groups below are relative to `/api/v1/boards/{board_id}`; route naming may follow existing conventions.

| Resource or action | Contract |
| --- | --- |
| `GET/POST /loops` | List or create Loops; creation initializes empty document slots and Loop-owned columns. |
| `GET/PATCH /loops/{loop_id}` | Read or edit allowed Loop metadata with version checking. |
| `GET /loops/{loop_id}/documents` and revision routes | Read current/approved revisions and their history without conflating them. |
| Human Info revision route | Human session required; agent and WebMCP writes prohibited. |
| `POST /loops/{loop_id}/generation-runs` | Request analysis, RoadMap or QA generation with captured source revisions and idempotency; return a durable run reference. |
| Run status/cancel/retry routes | Bounded generation management and actionable failure information. |
| Candidate submission routes | External agents submit schema-validated AnalysisAI, RoadMapAI or paired artifacts; submission is not approval. |
| Analysis and RoadMap review routes | Human-only decisions with expected Loop version and exact revision IDs. |
| `/loops/{loop_id}/lists` and `/cards` | Loop-scoped access over the existing list/card services. |
| Readiness/context routes | Machine-readable work eligibility, blockers and bounded input context. |
| Completion/QA routes | Human implementation acceptance, QA instructions/results, human final QA acceptance and idempotent finalization. |
| `GET /history` and `/history/{history_id}` | Paginated history search and immutable detail views. |

Use distinct scopes where needed, such as `loops:read`, `loops:write`, `loops:generate`, `loops:review` and `history:read`, integrated with existing role policy. Do not silently expand existing token grants. Review and human-only decisions require the human/session condition in addition to any scope.

Every list/Ticket mutation must have an explicit Loop context and validate it against the list, Phase and Ticket being addressed. New nested routes can replace the previous Board-scoped routes; backward-compatible aliases are not required. A retained Board-scoped GET endpoint may serve an explicitly aggregate read, with each result identifying its Loop. Never infer a default Loop or select the first available one.

Update the frontend, typed client, API documentation, tests and WebMCP tools together. A Board is now a container of Loops, not a Kanban. Creating a Loop creates its columns; actionable delivery Tickets are materialized from its approved plan.

All retained card mutation paths, bulk operations, checklist actions and attachment/discussion operations must respect the new ownership, completion and history protections. Remove obsolete paths rather than maintaining compatibility behavior that bypasses a gate.

Register WebMCP tools according to the current App, Board or Loop context and authenticated scopes. Offer inspection, generation and permitted Ticket operations. Do not register autonomous tools for editing Info, accepting plans, confirming human work, accepting QA or finalizing a Loop.

Useful structured error codes include `loop_required`, `loop_mismatch`, `loop_read_only`, `document_stale`, `approval_required`, `human_action_required`, `invalid_dependency_graph`, `ticket_blocked`, `plan_change_required`, `generation_input_changed`, and `qa_incomplete`. Include machine-readable blocker IDs and actionable details without leaking secrets or server paths.

## 13. Clean schema transition and existing-operation integration

### 13.1 Early-stage development: no production migration

There is no production data to preserve. This is an intentional structural redesign, not a rolling production migration. A reset of disposable development/test databases is acceptable and preferable to introducing compatibility complexity.

Do not implement an `Existing work` migration Loop, a legacy card workflow, retrospective adoption of existing cards, preservation of old primary keys, compatibility redirects, old API payload support or conversion of pre-redesign Board exports. These are explicitly outside scope. This does **not** remove the separate requirement for a future importer of external historical Loops: that importer targets the read-only history envelope described in section 9.3.

Continue using Alembic as the schema authority. Add the necessary revisions and keep clean initialization deterministic; do not introduce ad-hoc runtime DDL or edit already released revisions. Applying the migration chain to an empty database must produce the new schema directly. No populated-old-schema upgrade path is required for this feature.

Provide a documented, explicit development reset command or procedure. It must identify the data directory being reset and require deliberate confirmation before removing local databases or assets. Do not silently erase data during application startup. If an incompatible populated development database is encountered, stop with an actionable reset instruction instead of creating a partially converted state.

Update fixture builders and test setup to create `Board -> Loop -> columns/Tickets`. Remove assumptions that creating a Board must create a Kanban or that cards can exist without Loop ownership. Existing tests for intentionally removed behavior should be rewritten, not kept alive through legacy exceptions.

Schema-version management, integrity checks, verified backups and failure reporting remain valuable infrastructure for the new design. The exemption concerns old development data, not the correctness or durability of the new Loop workflow.

### 13.2 Integrate reused operations with the new hierarchy

Audit and update the following operations as part of the feature:

| Operation | Required behavior |
| --- | --- |
| Card/list reads and reorder helpers | Explicit Loop scope; aggregate Board reads identify each item's Loop. |
| Query keys and invalidation | Include Board and Loop identity, applicable filters and pagination. Never reuse one Loop's cached cards in another. |
| Bulk card operations | Apply workflow checks; do not reuse partial-success behavior for atomic plan publication. |
| Card archive/delete and list deletion | Do not erase required planned work or completed historical evidence through a cascade. |
| Card transfer | Disable unsupported cross-Loop/cross-Board planned Ticket transfers with clear guidance; no legacy exception is required. |
| Board templates | Store defaults without ownerless columns; instantiate independent columns per Loop. |
| Search and Discussions | Show Loop context and open Tickets and threads through the correct Loop. |
| Mentions and agent replies | Include bounded relevant Loop context; respect completed/read-only state and in-flight job guards. |
| Board backup/restore | Preserve newly created documents, plans, approvals, QA and history; coordinate with active jobs and verify required assets. |
| Board duplication | Copy Loop-local data consistently without launching copied pending runs. Preserve source provenance; copied decisions must not be represented as newly performed human approvals. |
| Board export/import | Round-trip the new schema, history and required assets. Clearly reject unsupported old formats; conversion of them is not required. |
| Board archive/delete | Apply to all its Loops. Archiving does not delete history; permanent deletion retains explicit confirmation and authorization. |

On duplication or native Board import, Board-local child UUIDs may be retained, but identity must be qualified by the new Board ID. Immutable historical snapshots retain their original source Board identity. Do not silently rewrite a hashed historical payload to make it appear newly authored in the destination.

Version a changed portable archive format accurately. It is acceptable to accept only the new format for this early-stage redesign. The future legacy-Loop importer is a different feature from native Board archive import.

### 13.3 Schema and integration verification

Test fresh initialization from an empty data directory, explicit development reset, repeatable startup, integrity and ownership constraints, and clear handling of an incompatible populated development database. Do not add old-data preservation fixtures or a migration/adoption workflow.

For the new model, test Board export/import/duplication/restore, FTS fallback and generation recovery with representative Loop documents, Tickets, QA, history and assets. Newly created workflow data must remain consistent even though pre-redesign data preservation is not required.

## 14. Implementation structure and ordered delivery

Implement small vertical slices. Keep each slice testable and integrate through the existing composition root. Suggested service responsibilities are Loop ownership/lifecycle, document revision/review, planning/publication, dependency evaluation, generation, QA and history. These are application modules, not new processes or microservices.

Do not copy business rules into React, API routers and WebMCP separately. Do not rewrite the existing card subsystem, authentication system or discussion engine to fit a new abstraction.

| Slice | Deliverable | Exit condition |
| --- | --- | --- |
| 0. Baseline verification | Inspect the current checkout, migrations, services and test commands; record any difference from the reviewed commit and existing test failures. | An implementation plan references actual paths and current migration heads. No baseline failure is silently attributed to this feature or ignored. |
| 1. Loop ownership and clean schema | Add Loops, scope lists/cards and add Board Loop defaults. Implement a documented development reset instead of preserving old test data. | Fresh database initialization and reset tests pass; two Loops cannot share columns accidentally or leak query results. |
| 2. Navigation and Loop Kanban | Change Board pages to Loop overviews; route the existing Kanban into a Loop page; add the document header and correct deep links. | Existing Ticket features work within a Loop; there are no document pseudo-cards. |
| 3. Revisioned documents and permissions | Implement empty slots, human-only Info editing, immutable revisions, source tracking and version conflict handling. | Agent writes to Info are rejected; stale edits and source mismatches are tested. |
| 4. Analysis generation and review | Add bounded generation/external submission, technical findings, human summary, run recovery and version-bound human approval. | Analysis can be generated, rejected, revised and approved; unsupported tools are not falsely claimed. |
| 5. Structured RoadMaps and identities | Add numbered Phases, planned Ticket reservations, validation, human representation and dependency graph checking. | Candidate pairs match; collisions, cycles and invalid references are rejected before publication. |
| 6. Publication and replanning | Atomically publish Tickets and approvals; implement change previews, retained identities and invalidation rules. | Retry does not duplicate cards; partial failures roll back; completed work is not silently overwritten. |
| 7. Work readiness and human gates | Enforce dependencies on all execution paths; add person icon, accent, instructions and blocker explanations. | The Phase 2/Phase 6 example works without blocking Phases 3-5 or deadlocking its own human gate. |
| 8. QA workflow | Add human implementation acceptance, one QA Task with two views, scenario results and human final acceptance. | Missing tools are reported as blocked; generated instructions or agent claims cannot finalize a Loop. |
| 9. History and import boundary | Add immutable native snapshots, history UI/search and tested legacy-envelope storage. | Completion is atomic/idempotent; legacy artifacts round-trip unchanged and remain clearly marked. |
| 10. Operational integration | Finish templates, archive/transfer guards, restore/duplicate/export/import handling, query invalidation and WebMCP updates. | Existing operations cannot bypass workflow rules or lose new data; copied jobs do not resume unexpectedly. |
| 11. End-to-end verification and documentation | Cover the complete journey, failure/retry paths and clean installation/reset; update README, API, architecture, database and relevant agent instructions. | Verification gates pass, known limitations are accurate, and the new hierarchy is documented consistently. |

Tests for a slice are part of that slice; do not postpone all verification to Slice 11. Keep implementation progress in the repository's existing development workflow. Do not delete existing `.ralph` history merely because this feature will eventually reduce reliance on such files.

## 15. Acceptance and regression scenarios

The following scenarios are minimum acceptance coverage, not substitutes for unit tests around individual services.

| ID | Scenario and expected result |
| --- | --- |
| AC-01 | Create a Board and two Loops. Each Loop has its own columns, ordering, Tickets and five empty document slots. No generation has occurred. |
| AC-02 | Open a Board: it lists Loops. Open a Loop: it shows that Loop's Kanban and Info/Analysis/RoadMap header. No planning document is a card. |
| AC-03 | Edit Info as a user, then attempt the same operation with an agent token or registered WebMCP tool. Only the authorized human workflow succeeds. |
| AC-04 | Generate analysis with incomplete project context. Missing access and assumptions are visible; the output does not claim repository inspection it did not perform. |
| AC-05 | AnalysisAI contains a material risk. The human Analysis exposes its practical consequence and retains traceability without displaying implementation jargon in the main explanation. |
| AC-06 | Attempt RoadMap generation before current analysis approval. The server rejects it. An older approval for another Info revision is insufficient. |
| AC-07 | Change Info after approval. Dependent artifacts become stale and new execution is blocked; earlier documents and decisions remain readable. |
| AC-08 | A generation result arrives after its inputs changed. It is not promoted over current documents or accepted as current without review. |
| AC-09 | Generate several Loops and Phases with identical name prefixes and multiple Tickets per Phase. All native keys are unique in the Board and stable after renaming. |
| AC-10 | Generate an invalid plan, a missing reference, a cycle or a mismatched human projection. No live Tickets are created. |
| AC-11 | Approve a RoadMap, retry the request and simulate a failure during materialization. Exactly one complete approved plan is active, or the operation rolls back entirely. |
| AC-12 | An agent tries to approve a plan or alter an approved Ticket's scope through a retained card endpoint. The human gate/plan-amendment policy is enforced. |
| AC-13 | A human gate is available after Phase 2 and blocks Phase 6. Before Phase 2 it is blocked; afterward it is actionable while Phases 3-5 may continue. Phase 6 remains blocked until human confirmation. |
| AC-14 | An agent tries to confirm the human gate. The request is rejected even when the agent is assigned to the Ticket or possesses card-write permissions. |
| AC-15 | A required Ticket is dragged to a column called Done or archived while incomplete. Neither action silently completes the Ticket or unblocks dependent work. |
| AC-16 | A prerequisite is reopened after dependent work or QA was reported complete. The relevant validity warning appears and finalization requires revalidation or explicit human disposition. |
| AC-17 | Revise an in-progress RoadMap. Unchanged Tickets retain UUIDs, keys and evidence; removed or changed completed work is shown for review rather than erased. |
| AC-18 | Accept implementation without QA and retry the request. The Loop remains Awaiting QA with one active QA Task containing two matching instruction views. |
| AC-19 | QA generation fails or the provider is unavailable. The Task shows the failure, existing content is preserved, and no QA pass or history completion is recorded. |
| AC-20 | An external QA agent lacks browser or repository access. Relevant scenarios are blocked/not run; the application does not assume a particular tool or report a pass. |
| AC-21 | An agent reports successful QA. Results are recorded, but only a human can accept QA and finalize the Loop. |
| AC-22 | The human confirms QA already passed outside Tralala. The record identifies this as a human attestation with scope and evidence rather than claiming an in-app automated run. |
| AC-23 | A required QA scenario fails or delivery changes after testing. Completion is rejected until the affected outcome is resolved and revalidated. |
| AC-24 | Finalize a Loop and retry. One immutable native history snapshot exists; the Loop is read-only, and active-work views no longer show it as pending work. |
| AC-25 | Search history by a finding, decision or Ticket key. The corresponding native or imported record is found with explicit source/QA status and correct pagination. |
| AC-26 | Store a legacy fixture that lacks Phases or contains nonstandard keys. Its original bytes are preserved, a warning is shown, and no live Tickets or verified approvals are created. |
| AC-27 | Initialize from an empty data directory and create a Board. The latest schema is installed, the Board has no ownerless columns, and all subsequently created Loops follow the new workflow. |
| AC-28 | Run the documented development reset. It requires an explicit destructive confirmation, recreates a usable clean schema, and creates no migration Loop or fabricated historical data. |
| AC-29 | Create or mutate a list/Ticket without a valid Loop context, or supply a list from another Loop. The server rejects the request rather than selecting a default or accepting mismatched ownership. |
| AC-30 | Switch rapidly between Loops and reconnect an event stream. Query caches, counts, events and dialogs never show another Loop's state under the wrong header. |
| AC-31 | Restore, duplicate or import a Board containing active generation records and historical content. Old jobs cannot mutate the wrong database incarnation, and history/provenance survive. |
| AC-32 | Export and restore a completed Loop's required evidence. Text and included assets remain inspectable, and their integrity metadata matches. |
| AC-33 | Attempt mutation of a completed Loop through comments, attachments, checklists, transfer, list deletion and all retained API routes. Read-only/history protections hold consistently. |
| AC-34 | Run without FTS5 or without a configured AI provider. Search falls back correctly; existing data remains usable and unavailable generation is explained without fabrication. |
| AC-35 | Use keyboard navigation and each existing theme. Header dialogs, person icons, blocked states and QA warnings remain understandable and accessible. |

### Verification gates

Follow the current repository commands and conventions. At minimum run backend tests and Ruff; frontend tests, type checking and the production build; and Playwright journeys for the changed workflow. Include tests for fresh schema initialization, explicit development reset, failure recovery and the new schema constraints. Tests for migrating old production data, compatibility routes and old exports are not required. Update tests whose expectations are intentionally replaced by the new hierarchy; retain relevant coverage of reused functionality rather than replacing it with only new happy-path tests.

A coding agent must report the exact checks run and their results. Do not mark a slice complete merely because files were written or a model response looked plausible. Unavailable checks and remaining failures must be stated explicitly.

## 16. Definition of done and non-goals

This feature is complete when a user can create a Loop under a Board, gather human Info, obtain and approve analysis and a phased RoadMap, work through its independent Kanban with enforced human gates, perform and accept QA, and find the finished work in standardized Board-local history. The implementation must work from a clean development database and reuse useful existing functionality. Preserving pre-redesign development data or supporting old clients is not a completion condition.

The legacy-history destination must be ready and tested, but a full importer is not required. Source format conversion is explicitly not required. No production-data migration, legacy workflow mode, backward-compatible API layer, old export conversion, new cloud dependency, central history database, model provider, queue broker, built-in coding sandbox, autonomous browser-testing engine, vector-search service, sprint system, billing feature or licensing change is part of this increment.

## Appendix A. Repository evidence used for this specification

All references below are paths within `BitNomadAB/Tralala` at commit `50867258ad798f66773f45813014891fe4ec1af4`. The implementation agent must inspect the current versions before editing. These references establish the reviewed baseline; requirements and design decisions in this specification describe the intended new behavior.

| Reference | Inspected source | Relevant baseline |
| --- | --- | --- |
| R1 | `docs/architecture.md` | Shared service layer, SQLite ownership, discussions, events, mentions, search, WebMCP and operational assumptions. |
| R2 | `AGENTS.md` | Architecture rules, authentication/identity rules, migrations, verification and licensing boundaries. |
| R3 | `docs/database.md` | Existing registry and Board tables, relationships, migration approach, backups and export documentation. |
| R4 | `backend/app/services/cards.py`, inspected through the relevant creation, bulk, update, move and archive paths | Existing card identity, assignment, completion semantics, version checks and partial bulk behavior. |
| R5 | `backend/app/services/lists.py` | Board-wide list ownership, ordering and mutation paths that need Loop scoping. |
| R6 | `backend/app/services/runtime.py` | Actual chat-completion invocation, response extraction, errors and usage handling. |
| R7 | `frontend/src/features/board/BoardPage.tsx`, inspected navigation, queries and mutations | Existing Board Kanban, per-list queries, drag-and-drop, card dialog and template actions. |
| R8 | `backend/app/services/orchestrator.py`, `backend/app/services/__init__.py`, `docs/api.md` | Ticket-bound discussion context, service composition, run behavior and capability contracts. |
| R9 | `backend/app/core/context.py`, `backend/app/api/deps.py` | Actual actor types, scope policy, session/bearer resolution, CSRF and pagination. |
| R10 | `backend/app/services/boards.py`, inspected lifecycle, snapshot, export/import and recovery paths | Current archive/delete behavior, database-copy operations, format handling and Board access guards. |

Repository location: `https://github.com/BitNomadAB/Tralala`.

## Appendix B. Coding-agent kickoff

```text
Implement the attached Tralala Loop specification incrementally in the existing repository.
Read AGENTS.md and inspect the current code and migration heads first.
The authoritative hierarchy is App -> Boards -> Loops -> per-Loop Kanban -> Tickets.
Info, Analysis and RoadMap belong in the Loop Kanban header.
Reuse existing card functionality; do not rebuild the application from scratch.
There is no production data to preserve. A clean schema change and explicit development reset
are allowed; do not build migration Loops, legacy modes or backward-compatibility adapters.
Follow the ordered slices, human approval boundaries and verification gates in the specification.
Record assumptions, deviations and failing checks explicitly. Do not claim execution or QA
success without evidence. Start with the baseline assessment and Loop ownership/clean-schema slice.
```
