# Repositories

An analysis or RoadMap run can read the code a board is about. Tralala keeps one list of
repositories; each board links the ones it concerns, and every analysis or RoadMap run reads each
linked, enabled repository at one commit. A model that calls tools reads the code itself, as much as
the request needs; any other model gets a bounded snapshot of it in the request. This page is the
operator's guide: which way of reading a repository fits, how to add one, how a run reads the code,
what Tralala keeps on disk, the settings, and what to do when a repository cannot be read.

**Nothing from a repository is ever executed.** Tralala reads files as text and nothing else: no
build, no install step, no script, no hook and no Git configuration from the repository runs, the
tools a model reads with only read, and the prompts tell the model that repository content is data,
never instructions. The details are under [Nothing is executed](#nothing-is-executed).

## Which way fits

A repository is read through one of two providers, chosen when it is added:

- **GitHub** (`github`, the default) reads a `github.com` repository through the GitHub API.
- **Git over HTTPS** (`git_https`) keeps a mirror of the repository's main branch under the data
  directory and brings it up to date before every run. It works with any Git host that serves
  HTTPS and is listed in `TRALALA_REPOSITORY_HOSTS`, including a host on a closed network.

| Scenario | What you need | Provider | What Tralala reads | How to see what a run used | How to narrow it |
| --- | --- | --- | --- | --- | --- |
| Public GitHub repository | The URL | GitHub | The branch head through the GitHub API, no token | The document dialog's "based on" line and the run's steps; `source_revisions.repositories` and `trace` on the run | The *Branch* field; the board link's focus and exclude globs; link it only to the boards it concerns; untick *Enabled for analysis* |
| Private GitHub repository | The URL and a fine-grained token for that repository with *Contents: read* | GitHub | The same, with the token | The same | The same |
| Any HTTPS Git host | The HTTPS URL, the host in `TRALALA_REPOSITORY_HOSTS`, and a read-only token if the host wants one | Git over HTTPS | The main branch, fetched into the mirror before every run | The same, plus when the mirror was fetched and whether it was stale | The same |

A public GitHub repository needs no token. Without one, GitHub allows 60 API calls an hour per
address; each run of a linked repository makes one to resolve its branch. When that limit is reached,
the check and the run say so (`rate_limited`), and a token raises it to 5 000 an hour: a fine-grained
token with *Contents: read* is enough, even for a public repository. The archive of a commit is
downloaded once and kept (see the layout below), so a retry or a second Loop on the same commit costs
only that one call. A token that passed an earlier check and is then rejected has most likely
expired: the check says so, and you replace it under **Edit**. `github.com` is in
`TRALALA_REPOSITORY_HOSTS` by default, so a GitHub repository can also be read through the mirror.

Either way, a run gets the archive of one commit. The GitHub download and the mirror's archive are
both held to `TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES` (128 MiB by default), and a larger one fails as
`too_large`. What the model then sees of it depends on the agent, not on the provider: see
[How a run reads the code](#how-a-run-reads-the-code).

## Add a repository

The steps for Git over HTTPS; a GitHub repository skips step 1. Each step names the dialog field and
the API call that does the same (`/api/v1`, an administrator's session or a token with
`boards:admin`).

1. **Allow the host.** Add the host name to `TRALALA_REPOSITORY_HOSTS` in `.env` (comma-separated,
   for example `TRALALA_REPOSITORY_HOSTS=github.com,git.example.com`) and restart the backend. A
   repository on any other host is refused when it is added (`422 host_not_allowed`) and again before
   every fetch.
2. **Create a read-only token**, if the repository is not public. See
   [Tokens](#tokens) for what to create and how to check it before pasting it.
3. **Add the repository**: **Settings → Manage repositories → New repository**.

   | Field | What to enter |
   | --- | --- |
   | Provider | *Git over HTTPS* (or *GitHub*). Fixed once the repository exists |
   | Name | Shown in lists; defaults to the last part of the URL |
   | Repository URL | `https://git.example.com/team/app.git`: `https` only, no user name or token in it |
   | Branch (optional) | Empty reads the main branch, the one the remote's HEAD names (`main`, `master`, ...). A name here wins |
   | Access token | The read-only token, or empty for a public repository. Stored sealed, never shown again |
   | Enabled for analysis | Ticked; untick it to leave the repository out of runs without unlinking it |

   The same through the API:

   ```bash
   curl -sS -X POST https://tralala.example.com/api/v1/repositories \
     -H "Authorization: Bearer trl_..." -H "Content-Type: application/json" \
     -d '{"provider": "git_https", "url": "https://git.example.com/team/app.git", "token": "..."}'
   ```

   The answer is the repository with its `id`, `has_token` and a short `token_hint`, never the token.
4. **Test access**: saving a new repository, or a new token, runs the check at once; the row's
   *Test access* button, or `POST /repositories/{id}/check`, runs it again. It reads the repository
   the way a run does, its code and not only that it exists: a GitHub repository is asked for its
   newest commit, so a token that sees the repository but not its contents fails here
   (`contents_hidden`) instead of in a run. For Git over HTTPS it runs `git ls-remote` only: it
   clones nothing, names the main branch and stores it as the row's *Default branch*. `status` is
   `ok`, `branch_missing` when the *Branch* field names a branch the remote does not have, or one of
   the codes under [Troubleshooting](#troubleshooting); `detail` is the same sentence a run shows.
5. **Link it to a board**: open the board → **Edit board → Repositories**, or
   `PATCH /boards/{id}` with `{"repository_ids": ["<id>", ...]}`. The list replaces the board's
   selection; an empty list unlinks every repository. A board may link several repositories and a
   repository may serve several boards.
6. **Run an analysis.** The first run clones the mirror; every later run fetches the newest commit
   first. The document dialog then says what the run read: "based on app @ 1a2b3c4d, 42 files,
   96 KB", and the run's steps say how it read it.

## How a run reads the code

An analysis or RoadMap run reads every linked, enabled repository at one commit, in one of two ways.
The agent the run uses decides which, not the repository's provider. A QA run reads no repository.

| The run's agent | How the model sees the code |
| --- | --- |
| OpenAI-compatible, and its last connection test found tool calling: Settings lists it as "reads repositories with tools" | It reads the repositories itself through three read-only tools, as much as the request needs |
| OpenAI-compatible without it: "no tool calling", or never tested | A fixed snapshot of each repository in the request |
| A2A | A fixed snapshot: an A2A agent is never offered tools |

The flag comes from **Test connection** on the agent: after its completion the test offers the model
a dummy tool and records whether the model called it. Every test writes the flag afresh; editing the
agent does not, so test again after you change its model or endpoint.

An agent that reads with tools still gets the snapshot in two cases, and the run's steps say which:

- **No linked repository could be read.** Each repository's step names its error (see
  [Troubleshooting](#troubleshooting)), and the run goes on without code, as a snapshot run would.
- **The provider refuses the tools** on the run's first call although the test found them, for
  example because another model now answers behind the endpoint. The run then sends the snapshot,
  made from the archives it already fetched, so nothing is downloaded twice. A refusal after the
  model has started reading fails the run as a provider error instead.

### The model reads the code itself

The run fetches each repository once, as described above, and holds its text files in memory as a
read-only workspace. The request carries the Loop's documents, each repository's name, commit and
file count, and the list of files the tools can read with their sizes. A list longer than 1 000
paths (or `TRALALA_GENERATION_TOOL_RESULT_CHARS` characters) ends with how many more there are, and
the model lists those itself. The model then has three tools:

| Tool | What it answers |
| --- | --- |
| `list_files` (`path`, `glob`) | The files below a directory with their size in bytes, sorted by path, optionally only those a glob matches; at most 1 000 per answer |
| `read_file` (`path`, `start_line`, `end_line`) | A file's text with line numbers. A file longer than one answer comes in parts, each ending with the line to continue from |
| `search` (`pattern`, `glob`, `regex`) | Matching lines as `path:line: text`, at most 200 per answer. Literal and case-sensitive by default; a regular expression is at most 200 characters, and one that repeats a repeated group, such as `(a+)+`, is refused |

Every path starts with the repository's name (`app/docs/setup.md`), so two repositories never mix.
The model reads as often as it needs, and the run ends when it answers without a tool call. That
answer is checked against the schema and, for a RoadMap, the plan rules, like any other; an answer
that breaks one goes back to the model with what was wrong, at most twice, in the same conversation.
A call that cannot be answered (an unknown path, a directory, a line range past the end, arguments
that are not JSON) gets an answer that says what was wrong and what to call instead, and the run goes
on.

The tools see what the snapshot would: the same noise filter (build output, dependencies, lock files,
binaries, images and empty files are not there), the board link's focus and exclude globs, and text
files only. The workspace holds at most 20 000 files, 64 MiB of text and 8 MiB per file, filled in
the snapshot's priority order. A file past those bounds is listed as *left out*, and reading it says
that it exists but cannot be read. These bounds are fixed, not settings.

### The limits

Besides those fixed bounds, a run that reads with tools has two kinds of limit: security, and the
model's context window. The run enforces both; neither is a rule the model is asked to keep.

**Security** is not a setting. The tools read only the in-memory index of the commit's archive:
nothing from the repository is unpacked to disk, run or changed, a path is a key in that index and
never a file name, and the request tells the model that repository text is material to analyse,
never instructions to follow.

**The context window**, and the memory and time a run may take, are settings:

| Setting | Default | What it protects |
| --- | --- | --- |
| `TRALALA_GENERATION_TOOL_STEPS` | `60` | The length of a run: after this many tool calls the model is asked for its answer from what it has read, with what it could not read under open questions |
| `TRALALA_GENERATION_TOOL_RESULT_CHARS` | `60000` | One answer's share of the context: a tool answer is at most this many characters, so a long file comes in parts |
| `TRALALA_GENERATION_CONTEXT_CHARS` | `400000` | The whole conversation: before every call, the oldest tool answers are replaced by a one-line note until it fits. The model can call the tool again to read one |
| `TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES` | `134217728` (128 MiB) | The server's memory: the largest archive a run downloads from GitHub or a mirror writes, held in memory while the model reads it. A larger one fails as `too_large`, for the snapshot as well |

Raise `TRALALA_GENERATION_CONTEXT_CHARS` for a model with a larger context window and lower it for a
smaller one; the default is about 100 k tokens. A model that still calls tools after the last one
allowed is told that no more calls are run and asked again; if it does it a second time, the run
fails with "The model kept calling tools after this run's tool calls were used up".

### The fixed snapshot

Every other run gets a fixed snapshot of each repository in the request: at most 200 files and
200 KB of text per repository, with build output, dependencies, lock files, binaries and images
skipped and the README, `AGENTS.md` and `docs/` first. The snapshots share
`TRALALA_GENERATION_CONTEXT_CHARS` with the Loop's documents, which come first. A file that does not
fit is left out and the next one is read, and the model also gets a manifest of every file it could
have read, each marked as sent or not (at most 5 000 entries), so a file it was not sent is never
taken for a missing one. The model is asked once; the same schema check and up to two repairs
follow.

### What the run records

- **The steps**, as `trace` on the run (`GET /boards/{board_id}/loops/{loop_id}/generation-runs/{run_id}`
  and the run list): one step for every event, written to the run as it happens. A step never holds
  a file's content: for a tool call it keeps the tool, its arguments and what the answer held (its
  one-sentence summary, its size, the files read, the line range, how many entries or matches,
  whether it was cut, an error code). [API.md](API.md#generation-run-steps) has the fields.
- **The repositories**, as `source_revisions.repositories`: each entry of a run that read with tools
  carries `reading: "tools"`, the commit, `file_count` (the files the model could read) and
  `left_out` (the files past the workspace's bounds). A snapshot entry carries the number of files
  sent and its share of the budget instead. Neither holds content.
- **The log line** `generation_run_finished` carries `tool_calls` (how many the model made) and
  `files_read` (how many different files it read), beside the duration and the token counts.

### Reading the steps

The document dialog's run panel shows the steps while the run works and keeps them afterwards: a
growing list of steps in plain words, grouped by stage. The stages come in this order, each one when
the run reaches it:

| Stage | What its steps say |
| --- | --- |
| Documents | Which of the Loop's documents the run read, by revision, and the plan's size |
| Repository | Each repository opened (commit, files, text), or the fixed selection sent and why; then every tool call in one sentence, such as `Read app/README.md, lines 1–120 of 120` or `Searched *.py for 'Settings': 3 matches in 2 files` |
| Writing | The model's answer: after how many tool calls, how long it is, and whether older tool answers were set aside |
| Checking | Whether the answer follows the schema and the rules, and every repair round |
| Saving | The draft saved for a person to review and approve, or why nothing was saved |

Each step also has a kind. Most are plain steps; the others stand out:

- **tool**: a tool call and the one-sentence summary of its answer;
- **note**: what the model wrote beside a tool call, in its own words ("I'll read the installation
  guide first");
- **repair**: an answer that broke a rule and was sent back;
- **limit**: a limit the run reached: the tool calls, the context window, or a provider that refused
  the tools;
- **error**: what failed, such as a provider call or a repository that could not be read, and why
  nothing was saved.

A run recorded before the steps existed has none (`trace` is `[]`).

### Cost

A run that reads with tools makes one provider call for every round of tool calls instead of one
call for the whole answer, and each call sends the conversation so far. It takes longer, and on a
hosted provider that bills by the token it costs more; `TRALALA_GENERATION_TOOL_STEPS` bounds both.
The run's usage adds up the tokens of every call.

## What Tralala keeps

Each repository that has been read has one directory under the data directory:

```text
<data>/repos/
  <repository id>/
    mirror.git/   Git over HTTPS: a bare, shallow mirror of one branch, one commit, no working tree
    state.json    Git over HTTPS: the URL (never a token), the branch, the default branch, the last
                  commit, when it was fetched, its size and the last error
    archive-<commit>.tar.gz
                  GitHub: the archive of a commit a run read, so the next run on it downloads nothing
```

Nothing else is written there. The GitHub archives of all repositories together stay under
`TRALALA_REPOSITORY_ARCHIVE_CACHE_MAX_BYTES`; the oldest go first. It is all a cache:

- **Backups leave it out.** A backup holds one board's database and its attachments, nothing from
  `repos/`.
- **It goes when nothing reads it.** Deleting the repository removes its directory in the same
  operation; so does unlinking it from its last board (a board that links it again clones it on its
  next run); and at every start Tralala removes each directory whose repository no longer exists.
- **Deleting it by hand is safe** while the stack is stopped: the next run clones the repository
  again. [Operations.md](Operations.md) lists it under disk housekeeping.

GitHub repositories keep nothing under `repos/`.

## Settings

| Variable | Default | What it does |
| --- | --- | --- |
| `TRALALA_REPOSITORY_HOSTS` | `github.com` | The hosts a mirror may fetch from, comma-separated. Checked when a repository is added or its URL changes, and before every fetch |
| `TRALALA_REPOSITORY_MIRROR_MAX_BYTES` | `1073741824` (1 GiB) | A mirror still larger than this after its clean-up is removed, and the run reports `too_large` |
| `TRALALA_REPOSITORY_FETCH_TIMEOUT_SECONDS` | `120` | How long one `git` command (ls-remote, clone, fetch, archive or a clean-up step) may take |
| `TRALALA_GENERATION_CONTEXT_CHARS` | `400000` | What one run sends the model. With the snapshot: documents and repository snapshots together; the documents come first, the repositories share the rest in link order, and what one does not use carries over to the next. With tools: the whole conversation; the oldest tool answers are set aside first |
| `TRALALA_GENERATION_TOOL_STEPS` | `60` | The tool calls one run answers; then the model is asked for its answer |
| `TRALALA_GENERATION_TOOL_RESULT_CHARS` | `60000` | The characters of one tool answer; a longer file comes in parts |
| `TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES` | `134217728` (128 MiB) | The largest archive of one commit a run downloads from GitHub or a mirror writes, held in memory while the run reads it; a larger one fails as `too_large` |
| `TRALALA_REPOSITORY_ARCHIVE_CACHE_MAX_BYTES` | `268435456` (256 MiB) | GitHub archives kept per repository and commit, all together at most this many bytes, the oldest removed first; `0` keeps none |
| `TRALALA_REPOSITORY_GIT_BINARY` | `git` | The `git` program the mirror runs. The backend image installs it; from source, `git` must be on `PATH` |

## Before every run: fetch and clean-up

For each linked, enabled Git over HTTPS repository, before the model is called:

1. Without a *Branch*, `git ls-remote --symref` asks the remote which branch its HEAD names.
2. The first run clones that branch (`--bare --depth 1 --single-branch`); every later run fetches it
   (`--depth 1 --prune`).
3. The clean-up runs after every fetch: `git reflog expire --expire=now --all`, then
   `git gc --prune=now`, so the mirror stays about one commit in size. A mirror still larger than
   `TRALALA_REPOSITORY_MIRROR_MAX_BYTES` is removed.
4. `git archive` of the branch, at most `TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES`, is read like the
   GitHub archive: the same filters and order, by the model's tools or into the snapshot.

One operation at a time runs per repository, so two runs never fetch the same mirror at once. The
row in **Settings → Repositories** shows the default branch, when the mirror was last fetched and its
size, and the run records the provider, branch, commit and fetch time.

## Stale mirror

When a fetch fails after an earlier one succeeded — the host is down, the token expired, the fetch
timed out — the run does not stop. It reads the last good mirror and says so:

- the "based on" line ends with "(stale mirror from 2026-11-02T08:00:00Z)", the time of the last
  good fetch;
- the run's `source_revisions.repositories` entry carries `stale_mirror: true` and that
  `fetched_at`;
- the repository's row shows "Last fetch failed:" with the code.

A repository that has never been fetched has no mirror to fall back on: it appears in the run as
unavailable, with its code, and the run goes on without it. Fix the cause (see
[Troubleshooting](#troubleshooting)); the next run fetches again.

## Rebuild mirror and Remove now

- **Rebuild mirror** (`POST /repositories/{id}/mirror/rebuild`) removes the mirror now; the next run
  clones it fresh. Use it when a mirror seems wrong. A changed URL or branch needs no rebuild: the
  next run clones the new one by itself.
- **Remove now** (`POST /repositories/{id}/mirror/remove`) appears when a removal failed because the
  host still held a file in the directory (a virus scanner, an indexer, an open shell). The row then
  shows `mirror_cleanup_failed`, and deleting the repository answers `409 mirror_cleanup_failed`
  without changing anything else. Once whatever held the file lets go, *Remove now* succeeds and the
  repository can be deleted.

Both need `boards:admin` and answer the repository; a GitHub repository answers
`409 repository_not_mirrored`.

## Tokens

Use a token that can only read, only the repositories it must, and that expires.

**GitHub** (either provider): GitHub → Settings → Developer settings → Personal access tokens →
Fine-grained tokens. *Resource owner*: the owner of the repository (for an organisation's
repository the organisation, which may have to approve the token); *Repository access*: *Only select
repositories*, this one; *Repository permissions* → **Contents: Read-only**; a short expiry. A token
created without choosing repositories reads public repositories only, so a private one answers as if
it did not exist. The dialog of a GitHub repository carries the same recipe and a command that
checks the token the way a run reads.

**Any other Git host**: create the host's read-only access token for the repository (a repository or
project access token with read access to the code, or a personal token limited to reading
repositories). Tralala sends it the way `git` sends `https://<user>:<token>@host/...`: HTTP Basic,
with the token as the password and the user name `x-access-token`. Hosts that take an access token as
the password ignore the user name. For a host that checks it, enter the token as `<user>:<token>` in
the *Access token* field, with the user name the host's documentation names for its tokens.

The token is sealed in the registry and travels only in the environment of the one `git` command
that needs it: never in the URL (a URL with credentials is refused), a command line, the mirror's
configuration, `state.json`, a log line or a run.

Check the token on your own machine before pasting it. The command sends the same header Tralala
sends; the first line of the answer names the main branch (`ref: refs/heads/main  HEAD`):

```bash
# bash, macOS, Linux
TOKEN=...
git -c http.extraHeader="Authorization: Basic $(printf 'x-access-token:%s' "$TOKEN" | base64 | tr -d '\n')" \
  ls-remote --symref https://git.example.com/team/app.git HEAD
```

```powershell
# PowerShell
$token = "..."
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("x-access-token:$token"))
git -c http.extraHeader="Authorization: Basic $basic" ls-remote --symref https://git.example.com/team/app.git HEAD
```

For a host that checks the user name, replace `x-access-token` with that name. SSH keys and SSH
URLs are not supported: the mirror speaks HTTPS only.

## Troubleshooting

A failure is named by a code, never by the host's or `git`'s own words, and a person reads it as
one sentence that says what went wrong and what to do: "The key cannot see app: give it read
access to the repository's contents". The check and the run use the same sentence. It appears on the
repository's row (the last check, or "Last fetch failed:"), in the run's steps and its "based on"
line, and the code in the run's `source_revisions.repositories` (`error`, with the sentence as
`problem`) and in the backend log (`repository_mirror_failed`, `repository_snapshot_failed`,
`repository_snapshot_empty`, and `git_command_failed` with a short excerpt of what `git` said).

A run whose repository could not be read goes on without that code, and says so everywhere: the
repository stage shows a cross (a warning when only one of several repositories failed), never a
check; a warning above the stages reads "Written without the code"; the "based on" line reads "no
code — written without the repository (...)"; and the analysis it saves opens its open questions
with the same notice, with `none: the code was not read` as its baseline revision.

| Code | What it means | What to do |
| --- | --- | --- |
| `host_not_allowed` | The URL's host is not in `TRALALA_REPOSITORY_HOSTS` | Add the host and restart the backend, or correct the URL |
| `invalid_url` | Not an `https` URL of a repository, or it carries a user name, token, query or fragment | Enter the plain `https://host/path` URL; the token goes in its own field |
| `auth_failed` | The host wants credentials, or refused the token | Add a token, check it with the command under [Tokens](#tokens), or enter it as `<user>:<token>` |
| `not_found` | The repository or branch does not exist, or the token cannot see it | Check the URL and the *Branch* field; give the token read access to this repository |
| `branch_missing` | *Test access* found the remote but not the branch in the *Branch* field | Correct the branch, or clear the field to read the main branch |
| `timeout` | A `git` command ran longer than `TRALALA_REPOSITORY_FETCH_TIMEOUT_SECONDS` | Check that the backend reaches the host; raise the timeout for a large first clone |
| `too_large` | The mirror is larger than `TRALALA_REPOSITORY_MIRROR_MAX_BYTES` after its clean-up, or the commit's archive (from GitHub or the mirror) is larger than `TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES` | Raise the limit, or read a smaller branch |
| `git_missing` | The `git` program is not installed where the backend runs | Use the backend image, or install `git` (or set `TRALALA_REPOSITORY_GIT_BINARY`) |
| `fetch_failed` | `git` could not read the repository for another reason | Read the `git_command_failed` log line; try *Rebuild mirror* |
| `stale_mirror` | The last fetch failed; the run read the last good mirror | See [Stale mirror](#stale-mirror) |
| `mirror_cleanup_failed` | The mirror's directory could not be removed: the host still holds a file in it | Close what holds it, then *Remove now* |
| `unauthorized`, `forbidden`, `rate_limited`, `unreachable` | GitHub provider: the token was rejected, lacks access, the API's limit was reached, or GitHub did not answer | Check the token with the dialog's command; add a token to raise the limit; try again later |
| `contents_hidden` | *Test access* only: the token sees the repository, but not its files | Give the token read access to the repository's contents (see [Tokens](#tokens)) |
| `empty_archive` | The commit holds no file at all: an empty branch, or only submodules, whose files an archive never carries | Check the *Branch* field, or link the repositories the submodules point to |
| `nothing_readable` | Every file is one a run skips: build output, dependencies, lock files, binaries | Link the repository that holds the source, or read another branch |
| `paths_match_nothing` | The board link's focus and exclude globs leave no file | Correct the globs under **Edit board → Repositories**; a folder is `docs/**`, not `docs` |

### When a run read the code differently than expected

The run's steps say how it read the code (see [Reading the steps](#reading-the-steps)). These are the
steps that need an operator:

| The step says | What it means | What to do |
| --- | --- | --- |
| "The key cannot see app: give it read access to the repository's contents", then "No code was read: the run goes on from the Loop's documents alone, and an analysis says so" | The host answered as if the repository did not exist: a private repository the token was not given, or a token without read access to its contents | Fix the token as the step says (see [Tokens](#tokens)), save it, which checks it at once, and run the analysis again |
| "app holds no files at this commit", "app has no file a run reads" or "The board's focus and exclude paths for app leave no file" | The run fetched the commit but found nothing to read, which it treats as a failed read | Do what the step says; the codes are `empty_archive`, `nothing_readable` and `paths_match_nothing` above |
| "Sent a fixed selection of app @ 1a2b3c4d: 42 of 412 files, the rest by name only (the agent's provider does not take tools; its connection test says so)" | The agent is not marked as calling tools, so the model got the snapshot | Run **Test connection** on the agent. If Settings still lists it as "no tool calling", the model or the server in front of it does not call tools: choose a model that supports tool calling, or switch it on in a local server (llama.cpp: `llama-server --jinja`; vLLM: `--enable-auto-tool-choice` with a `--tool-call-parser`), then test again |
| "Sent a fixed selection of … (an A2A agent cannot be offered tools)" | An A2A agent always gets the snapshot | Run the analysis or RoadMap on an OpenAI-compatible agent if the model should read the code itself |
| "Reached the 60 tool calls this run allows; asked the model for its answer now" | `TRALALA_GENERATION_TOOL_STEPS` ran out before the model finished reading. It answered from what it had read and should name the rest under open questions | Narrow what it has to read (the board link's focus and exclude globs, a more precise Info), or raise `TRALALA_GENERATION_TOOL_STEPS`. Every call costs time and, on a hosted provider, money |
| "Older tool answers were set aside to stay within the model's context window; it can read them again" | The conversation passed `TRALALA_GENERATION_CONTEXT_CHARS`, so the oldest tool answers were replaced by a note. Not an error: the model can read them again | Raise `TRALALA_GENERATION_CONTEXT_CHARS` if the model's context window is larger, or lower `TRALALA_GENERATION_TOOL_RESULT_CHARS` so each answer takes less. If the provider answers instead that the context is too long, the setting is larger than the model's window: lower it |
| "The provider refused tool calls, although the agent's connection test found them; sent a fixed selection of files instead (test the connection again)" | The provider refused the first call because of its tools (a `400` or `422` that names them), for example because another model now answers behind the endpoint. The run went on with the snapshot of what it had already fetched | Run **Test connection** again; it records the flag afresh. Test after every change of the agent's model or endpoint |
| "The model kept calling tools after this run's tool calls were used up" | After the last allowed call the model was asked for its answer twice and called tools both times; the run failed with `invalid_output` | Retry the run; a model that keeps doing it is a poor fit for reading with tools |

## Nothing is executed

The mirror runs `git` with a fixed list of arguments and no shell, and only six commands:
`ls-remote`, `clone`, `fetch`, `archive`, `reflog expire` and `gc`. Every command carries
`-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=never
-c protocol.https.allow=always`, so no hook, file-system monitor or protocol other than HTTPS can
run, and the environment keeps the system's and the account's Git configuration out and turns off
every prompt. The mirror is bare: nothing is checked out, so no file of the repository is ever on
disk as a file to run. What a run reads goes into the prompt as text, and the prompts call it
material to analyse, never instructions. The backend runs as the container's unprivileged user.

A model that reads with tools reads an index the run builds in memory from the commit's archive:
`list_files`, `read_file` and `search` look a path up in that index, never on disk, write nothing,
and a search pattern is bounded in length and shape so it cannot hold the run.
