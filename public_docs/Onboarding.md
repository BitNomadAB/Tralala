# Onboarding

Tralala is installed and you are signed in as `admin`. This is what to do next, in the order that
avoids going back: make the account yours, bring in one person, connect one agent, connect one
repository, then run one Loop end to end. Each section is short on purpose; the why lives in
[Architecture.md](Architecture.md) and the rules in [Loops.md](Loops.md).

```text
1 account -> 2 people -> 3 agent -> 4 repository
   -> 5 one Loop: Info -> Analysis -> RoadMap -> Execution -> QA -> Finalize
   -> 6 habits
```

## 1. Make the administrator account yours

**Settings → Your password.** Enter the current password (from `<data>/.bootstrap-password` on a
fresh install) and a new one of at least 8 characters. Every other session is signed out, including
yours, so sign in again. The change also deletes `<data>/.bootstrap-password`: it is a delivery
mechanism, not a credential, and Settings tells an administrator as long as it is still there.

Nothing else on this page is required to start working. The theme kits, backups and appearance
settings can wait.

## 2. Bring in one other person

1. **Settings → Users → New user** creates the account with a username and an initial password.
   Choices: `member` (everything except user and credential administration) or `admin`.
2. Or press the **invitation link** icon next to the account: it shows `/enrol?token=…` once. Send
   it through a channel you trust; the person chooses their own password and is signed in. You never
   learn it. The link expires after `TRALALA_INVITE_TTL_HOURS` (default 72) or when replaced.
3. Switching a person to `member` or `admin` takes effect immediately, and both roles see every board
   today — private boards are a separate feature, not a setting.

Tralala sends no e-mail. Delivery is yours.

## 3. Connect one agent

Two different things are called "agent". Do the first one if you want AI help inside Tralala; the
second if you want your own coding agent to drive Tralala.

### 3a. A role agent, so Loops can be analysed and discussed

1. **Settings → Agents → New agent.**
2. Name it, pick a **role template** (the factory list includes Lead Developer, QA Engineer,
   Security Engineer, Architect, Project Manager…), and set the **connection**. The two choices are
   different things, not two ways to say the same:

   | Connection | What sits on the other end | What the role decides |
   | --- | --- | --- |
   | `openai_compatible` | A model endpoint you point at. It has no tools or memory of its own. | Everything: Tralala sends the role prompt and the conversation, and the model answers as that role. |
   | `a2a` | An agent that already runs outside Tralala, with its own tools, memory and job. | Only how it answers inside this board. It arrives with its own way of working. |

   A local model is fine — private and loopback addresses are allowed on purpose.
3. Paste the provider **API key** if the endpoint needs one. It is sealed with a key derived from your
   session secret and never shown again; the list only says `has_api_key` plus a hint.
4. Press **Test connection** — before you save. It asks the endpoint which models it serves *and*
   sends one tiny real completion, so a wrong model name fails here instead of in a generation an hour
   later. Nothing is stored until the test is green, the reported model names become suggestions in
   the model field, and the raw answer is shown as JSON so the same block serves every provider.

   A model on the machine that runs Tralala is `http://host.docker.internal:<port>/v1` from inside
   the container, not `127.0.0.1`; see
   [Reaching a model that runs on the host](Installation.md#reaching-a-model-that-runs-on-the-host).
   A model running on your own machine or network — `http://192.168.0.10:8080` — usually has no key:
   tick **This endpoint needs no key** and nothing is sent, in the test or in a generation. The known
   local presets tick it for you; hosted providers keep it unticked and cannot be saved without one.

   Leave **Temperature** and **Maximum answer length (tokens)** empty unless you know you need them:
   empty sends neither, so the provider's own defaults apply and a provider that refuses either one
   still answers. **Timeout** starts at 180 s, because a reasoning or local model can need minutes for
   a structured answer; the connection test keeps its own limit of 30 s per call.
5. Make it work on the board: open the board and choose **Edit board → Agents**. An agent a board does
   not list is never asked on that board; leaving every box unchecked means "any enabled board
   profile", which is fine for a single-agent install. A Loop can narrow that further in its own
   agent settings.

An agent is a reader and discussion partner: it never authenticates, never moves a Ticket and never
changes code.

### 3b. A worker key, so your own coding agent can read and update Tralala

1. **Settings → New access key.** Name it, pick scopes, create. The token is shown once.
   For a coding agent take `boards:read`, `loops:read`, `cards:read`, `cards:write`,
   `comments:write`, `discussions:read`, `discussions:write`; add `loops:write` and
   `loops:generate` if it should open Loops and run analyses.
2. Point the agent at `<your URL>/mcp` with `Authorization: Bearer <key>`. `<your URL>/llms.txt`
   tells it the rest. The full walkthrough, the thirteen tools and their scopes are in
   [Agent_usage.md](Agent_usage.md).
3. The key belongs to your account: disable the account and it stops. Revoke it under the same list
   when a laptop is retired, and check `last_used_at` if you are unsure which key is which.

## 4. Connect one repository (optional, but it is what makes analysis concrete)

1. Create a **fine-grained GitHub token** with *Contents: read* for that repository only (a public
   repository needs none).
2. **Settings → Manage repositories → New repository**: provider *GitHub*, name,
   `https://github.com/your-org/your-repo`, optional branch, and the token. It is stored sealed and
   never shown again.
3. **Test access** proves the token works before you rely on it.
4. Assign it to the board: open the board → **Edit board → Repositories**. A board may have several;
   the analysis agents read only what is assigned, and the repository page shows which board uses
   which repository.
5. Optional: point the analysis at the part that matters. A selected repository shows **Focus
   paths** and **Exclude paths**, one glob per line relative to the repository root: `docs/**` reads
   only the documentation, `docs/archive/**` under exclude leaves old pages out. Both empty reads the
   whole repository. At most 20 globs of 200 characters each; no absolute paths and no `..`.

Without a repository the analysis still works from the Info you write; with one it cites files and
revisions, which is what makes the RoadMap reviewable.

A repository on another Git host (a closed network, a self-hosted server) uses the provider
*Git over HTTPS*: Tralala keeps a mirror of its main branch and fetches it before every run, once
the operator has listed the host in `TRALALA_REPOSITORY_HOSTS`. [Repositories.md](Repositories.md)
has the whole procedure, the token recipe for other hosts and a troubleshooting table.

What an analysis can actually see is **bounded on purpose**: at most 200 files and 200 KB of text
per repository (and 2 MB of archive from GitHub), with build output, dependencies, lock files,
binaries and images skipped. A file the snapshot cut away is a file the analysis must
list under *open questions* instead of guessing. After a run, the Loop's document dialog shows which
commit each analysis was based on and how many files it read — "based on acme app @ abc123de, 12
files" — and a repository that could not be read appears there with its reason (`unauthorized`,
`not_found`, `rate_limited`, `too_large`, `timeout`).

## 5. Run one Loop end to end

A **Board** is a project; a **Loop** is one feature or coherent change inside it. Create a board
(**New board**), then a Loop inside it (**New Loop** — a name and a broad goal are enough).

### The order of work inside a Loop

| Step | Who | What happens |
| --- | --- | --- |
| 1. Info | you, maybe with your worker agent | Write the intent: what to build and why. This is the input everything else is derived from. |
| 2. Analysis | the analysis agent, approved by you | Generate a technical analysis; read the plain-language view; **approve** it. Approval binds to that exact revision. |
| 3. RoadMap | an agent, approved by you | Generate a structured RoadMap: numbered Phases and planned Tickets; **approve** it to publish every Ticket at once. |
| 4. Execution | you and your worker agent | Move Tickets through the Loop's columns, assign them, comment progress. Readiness shows what blocks a Phase. |
| 5. QA | the QA agent, accepted by you | Ask for a QA Task (scenarios, agent view and human view); **accept implementation**, then **accept QA**. |
| 6. Finalize | you | The Loop is finalized: an immutable, hashed snapshot lands in History and the Loop becomes read-only. |

Three rules that keep this honest:

- **A person decides.** Approving the analysis and the RoadMap, confirming a human-only Ticket,
  accepting QA and finalizing are human actions. A token cannot perform them, whatever its scopes.
- **Changing Info invalidates approvals.** Edit the intent after planning and the Loop returns to
  `replanning`; the dependent approvals go stale and execution stops until you approve a replacement.
- **A column named Done completes nothing.** Completion is the acceptance decision, not a move.

### Where to talk instead of writing

Every Ticket has a **discussion**: ask the agents a question, get rounds of answers with positions,
pause or stop a run, then decide. It is capped at four rounds, with a token and time budget per run,
so a question cannot quietly spend the afternoon. Use it when you want an opinion *before* writing
the Info or the plan; use `@Agent` in a comment when you want one answer next to the work.

## 6. Day two: the habits that matter

- **Boards are cheap, Loops are the unit of work.** One Loop per coherent change; do not park a
  backlog of unrelated Tickets in a Loop you already approved.
- **Write the Info as if someone else will read it.** The analysis and the RoadMap are only as good
  as that paragraph.
- **Watch readiness, not the column name.** The Loop banner and
  `GET /boards/{id}/loops/{loop_id}/readiness` explain every blocker.
- **Let your worker comment as it goes.** A Ticket with the findings in it is worth more than one
  that looks finished.
- **Backups are automatic** (every 24 h, newest 10 kept). Take one before an upgrade anyway; the
  commands are in [practical_commands.md](practical_commands.md).

## If something looks wrong

[Troubleshooting.md](Troubleshooting.md) covers the generated password, throttling, a stuck
migration, a board that will not delete, and an agent that is not reachable. Security defaults and
what only you can decide: [Security_defaults.md](Security_defaults.md).
