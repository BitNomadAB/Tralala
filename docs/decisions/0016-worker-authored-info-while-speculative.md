# 0016 — A worker may seed a Loop's Info while the Loop is speculative

- **Status:** accepted
- **Date:** 2026-11-02
- **Context:** Loop documents and approval boundaries (`docs/loops.md`), the worker surface
  ([0015](0015-worker-surface-mcp-and-llms-txt.md)), board agent membership
  ([0012](0012-board-agent-membership.md))

## Problem

The way work actually starts is a conversation: a person and their coding agent agree what to build,
open a Loop for it, write that agreement down as Info, and ask an analysis agent to turn it into
findings. Until now the second step was impossible for the agent: `PUT …/documents/info` called
`require_human`, so a worker token got `403 human_action_required` and the person had to retype the
intent in the UI.

That rule exists for a good reason — a new Info revision invalidates the analysis, the RoadMap and
every approval that depended on them — but it was applied to two different situations:

- writing the intent of a Loop that does not exist yet, which is exactly the act the person and the
  agent just performed together;
- rewriting the intent of a Loop that has been planned and approved, which silently undoes decisions
  other people took.

## Decision

A token may write Info **only while the Loop is speculative**: `stage` is `draft` or
`analysis_review`. In every later stage the write is refused with `403 human_action_required` and the
stage in `details`, exactly as before. The check lives in `LoopDocumentService.save_info`
(`WORKER_INFO_STAGES`), not in the transport, so REST, MCP and any future interface inherit it.

The revision is still immutable, still records the acting actor (`author_actor_type: agent`), still
carries a note and a content hash, and still invalidates downstream work — a worker seeding Info
cannot smuggle in a change that escapes the revision history. What changes is only *who* may author
the first revision of a Loop that has not been approved yet.

## Consequences

- `create_loop` → `write_info` → `run_analysis` is one uninterrupted flow for a person and their
  worker; the person reviews the analysis candidate and approves it, which is where the real decision
  always was.
- The dangerous edit — new requirements after approval — is unchanged. A worker that wants to change
  a planned Loop must ask its person, who will move the Loop to `replanning` deliberately.
- The Info's author is visible in the revision history, so a reviewer can tell an agent-seeded
  revision from a human one without trusting a summary.
- The documented invariant "Info is written by a person" becomes "Info is a person's decision;
  their worker may write the first draft of it".

## Alternatives considered

- **Keep it human-only and have the worker hand over a patch.** Honest, but it makes the worker
  useless at the one moment it is most useful, and the person ends up copy-pasting from the chat into
  the UI anyway.
- **Let a token write Info at any stage.** Simple, and wrong: a worker could rewrite requirements
  behind an approved plan, invalidating decisions invisibly. Stage-gating keeps the gate where it
  costs nothing and removes it where it protects nothing.
- **A per-board "worker may write Info" setting.** More knobs for the same outcome; the stage already
  expresses "has anybody decided anything yet".
