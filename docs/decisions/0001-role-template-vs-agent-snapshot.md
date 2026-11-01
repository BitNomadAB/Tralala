# Decision: role templates are shared, agent role prompts are snapshotted

Status: accepted (2026-10-30)

## Context

The discussion forum needs AI agents with a role (Lead Developer, QA Engineer, Customer …). Roles
are opinionated and evolve: when a team improves its QA prompt, every *future* discussion should
benefit. At the same time an old discussion must remain explainable: "why did this agent vote
dissent?" must stay answerable after the role prompt changed.

## Decision

1. **Two resources, not one.**
   - `role_templates` (registry) holds the centralized, reusable definition: name, description,
     system prompt, a factory copy of the prompt, and a `built_in` marker.
   - `agents` (registry) is a separate identity with a stable UUID, its own connection, its own
     encrypted credential and a **reference** to a role template plus an optional prompt override.
2. **Central edits apply forward only.** An agent resolves its role at call time
   (`AgentService.effective_role`), so template edits change future discussions.
3. **Discussions store a snapshot.** `AgentService.role_snapshot` produces an immutable record
   (template id, template name, template `updated_at`, effective prompt, SHA-256 of the prompt,
   snapshot timestamp). Discussion participants persist that copy; rendering a discussion reads the
   snapshot, never the live template.
4. **Deleting a template never deletes history.** Custom templates can be deleted; agents lose the
   reference (`role_template_id = NULL`) and must be given another role or an override, while every
   stored snapshot keeps working because it contains the text, not a join.

## Consequences

- The role prompt in a historical discussion is reproducible byte-for-byte (hash included).
- Template renames and prompt edits are safe and do not require a data migration.
- Duplicated agents do not inherit credentials; a copied agent must be tested again.
- `agents` needs an encrypted secret column, which is why `cryptography` (Fernet + HKDF) was added
  as a dependency instead of storing provider keys in plaintext.
