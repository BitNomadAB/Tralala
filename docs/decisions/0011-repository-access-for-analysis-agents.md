# 0011 — Repository access for analysis agents

- Status: accepted as Model A, slice 1 delivered 2026-11-01. Slice 2 (snapshot fetch) is deferred by
  the owner (2026-11-02): it is a feature for a repository agent that needs files it was not given,
  not a defect, and nothing in the release depends on it. Re-open it when such an agent exists.
- Date: 2026-11-01

## Context

The Analytics agent exists to turn a Loop's Info into an analysis that names what the codebase must
change. Without repository context it can only restructure the request and must mark every
code-level claim as an assumption. To investigate the codebase it needs read access to a repository,
which for most users is a **private** GitHub repository.

Three facts shape the decision:

1. **The generation path is a single provider call.** `LoopGenerationService` sends one
   OpenAI-compatible chat request per run; there is no tool loop, no shell and no network access from
   the model. Whatever the agent may inspect must therefore be fetched by Tralala itself before the
   call and placed in the prompt.
2. **Secrets already have a pattern.** Provider API keys are sealed with `core/secrets.py`
   (Fernet key derived from the session secret), stored as ciphertext plus a short hint, never
   returned by an endpoint and never logged. A repository credential must use the same machinery
   rather than invent a second one.
3. **Anything fetched from a repository is untrusted input**, exactly like card text. It may contain
   instructions addressed at the model, binaries, secrets, gigabytes of generated output or paths
   that try to escape a directory.

## Decision (proposed)

**Model A — Tralala fetches a bounded, read-only snapshot.** The alternative (Model B, below) is
recorded but not proposed.

1. **Repositories are registry-level data, linked to boards.** One row per repository in
   `registry.sqlite` (the registry, not the board database, because it holds a credential and must
   not be copied by a board export): `id`, `name`, `provider` (`github`), `url`, `branch`,
   `token_ciphertext`, `token_hint`, `enabled`, `last_checked_at`, `last_check_status`,
   `last_check_detail`. Board membership lives in the `board_repositories` link table, so a
   repository is listed once however many boards it serves and a board may select several
   (an app and its infrastructure, for example). Selection comes from the board: `repository_ids`
   on `POST`/`PATCH /boards`, shown as checkboxes in the create and edit dialogs.
2. **The token is write-only from every interface.** Create/update accepts it, every response carries
   `has_token` and `token_hint` only. It is sealed with `core/secrets.py`, re-sealed on session-secret
   rotation like provider keys, and never written to a log, an activity entry, a prompt or an error
   message.
3. **Access is a fine-grained personal access token, read-only.** The documented recipe is a
   GitHub fine-grained PAT scoped to one repository with `Contents: read` and an expiry, not a classic
   token with `repo` scope and not a deploy key (a deploy key is per-repository and would need one
   more secret format). The repository dialog carries the recipe as a collapsible guide: it names
   the exact repository from the URL field, links the token page, shows how to verify the token on
   the operator's own machine before pasting it, and states that an SSH deploy key is not an
   alternative for this field because Tralala reads the REST API over HTTPS and runs no git binary.
4. **The URL is validated like a provider endpoint.** `services/connections.validate_endpoint` rules
   apply: `https` only, no embedded credentials, no redirects, and the host must be allowlisted
   (`github.com` and, for the API, `api.github.com`). A self-hosted Git server therefore needs an
   explicit allowlist entry rather than an open URL field.
5. **The fetch is bounded and read-only.** GitHub REST only, `follow_redirects=False`, 15 s timeout,
   and hard caps: at most 2 MB of archive, at most 200 files, at most 200 KB of text in the prompt.
   No write, no clone into the data directory, no `git` binary, no execution. Directories that cannot
   inform an analysis are skipped: `.git`, `node_modules`, `dist`, `build`, `.venv`, lock files,
   binaries and images.
6. **Fetched content is data, never instructions.** The prompt frames the snapshot as untrusted
   material and the role prompt already says so. A file that contains "ignore your rules" is analysed,
   not obeyed.
7. **One check endpoint.** `POST /repositories/{id}/check` reports the repository name, default
   branch and file count it can see, or a sanitized failure (`401`, `404`, `rate_limited`, `too_large`).
   That is the only way an operator learns whether the token works; the token is never echoed.

## Consequences

- The Analytics agent can name files, modules and tests only as far as the snapshot reaches. The
  prompt must state the caps it was given so the analysis does not claim completeness.
- The board's repository becomes part of what a Loop's analysis was based on. The generation run
  already snapshots its prompt and `source_revisions`; the repository commit SHA and the file list
  belong in that snapshot so a later analysis can be explained.
- Every Loop in a board analyses the repositories selected for that board. A Loop that needs a
  different set needs a different board (or a future per-Loop selection).
- Room for mistakes remains: a token with broader scopes still works. The product states the recipe;
  it cannot enforce GitHub-side scope, only detect a `403`/`404` at check time.

## Rejected alternatives

- **Model B — no credential in Tralala.** Store only `repository.url` and let an external agent
  harness (which already holds the credentials) do the inspection, then submit the analysis candidate
  through `POST /loops/{id}/candidates`. This is the smallest change and the safest secret handling,
  but it moves the work outside Tralala and needs a second execution model for loops, so it is not
  proposed for the next slice. It remains the best option if the product should never hold a
  repository credential.
- **A deploy key or SSH key per board.** Adds a second secret format (private key), needs known-hosts
  handling and a git binary; no benefit over a read-only token for reading files.
- **Let the model call the GitHub API itself (tool loop).** It would make the analysis interactive and
  far more useful, but it is a new execution engine (tools, budgets, approvals per call) and belongs
  in its own decision, not as a side effect of this one.
- **Store the token in the board database.** A board export (`GET /boards/{id}/export`) would then
  carry the credential to whoever downloads the archive.

## Implementation slices (after the decision)

1. **Credential and reference (storage).** Registry revisions adding `repositories` and the
   `board_repositories` link table (`0007`, `0008` for the list shape, `0009` for the links), a
   `RepositoryService` reusing `core/secrets.py`, the endpoints under `/repositories` (list, create,
   get, patch, delete, check), and an administrator page at `/settings/repositories` linked from
   Settings. Tests: the token is never returned, is re-sealed only when the previous secret opened
   it, one repository may serve several boards, a board replaces its selection atomically, an
   upgrade from `0008` keeps the existing assignment, and the check reports sanitized failures.
2. **Snapshot fetch.** A `RepositorySnapshotService` with the caps above, filling the generation
   context for `purpose=analysis`, plus the commit SHA and file inventory in the run snapshot.
   Tests: cap enforcement, skipped directories, an injected "instruction" file is not obeyed (it must
   appear in the report as data), and a 401/404/rate-limit path.
3. **Analysis UX.** Show in the dialog which repository and commit the draft was based on, and warn
   when no repository is configured that the codebase was not inspected.

## Decision taken

Model A, delivered in slices so the credential handling is reviewable before anything is fetched.
Slice 1 is implemented: registry revisions `0007`–`0009`, `RepositoryService`, six endpoints under
`/repositories`, an administrator page at `/settings/repositories`, repository checkboxes in the
board create/edit dialogs (`repository_ids`), sealing and re-sealing tests, and the sanitized access
check. Slice 2 (the bounded snapshot that fills the analysis context) is the next step and needs its
own review of the caps and the prompt framing.
