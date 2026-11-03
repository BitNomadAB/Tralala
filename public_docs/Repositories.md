# Repositories

An analysis or RoadMap run can read the code a board is about. Tralala keeps one list of
repositories; each board links the ones it concerns, and every run reads a bounded snapshot of each
linked, enabled repository and puts it in the prompt as material to analyse. This page is the
operator's guide: which way of reading a repository fits, how to add one, what Tralala keeps on disk,
the settings, and what to do when a repository cannot be read.

**Nothing from a repository is ever executed.** Tralala reads files as text and nothing else: no
build, no install step, no script, no hook and no Git configuration from the repository runs, and the
prompts tell the model that repository content is data, never instructions. The details are under
[Nothing is executed](#nothing-is-executed).

## Which way fits

A repository is read through one of two providers, chosen when it is added:

- **GitHub** (`github`, the default) reads a `github.com` repository through the GitHub API.
- **Git over HTTPS** (`git_https`) keeps a mirror of the repository's main branch under the data
  directory and brings it up to date before every run. It works with any Git host that serves
  HTTPS and is listed in `TRALALA_REPOSITORY_HOSTS`, including a host on a closed network.

| Scenario | What you need | Provider | What Tralala reads | How to see what a run used | How to narrow it |
| --- | --- | --- | --- | --- | --- |
| Public GitHub repository | The URL | GitHub | The branch head through the GitHub API, no token | The document dialog's "based on" line; `source_revisions.repositories` on the run | The *Branch* field; link it only to the boards it concerns; untick *Enabled for analysis* |
| Private GitHub repository | The URL and a fine-grained token for that repository with *Contents: read* | GitHub | The same, with the token | The same | The same |
| Any HTTPS Git host | The HTTPS URL, the host in `TRALALA_REPOSITORY_HOSTS`, and a read-only token if the host wants one | Git over HTTPS | The main branch, fetched into the mirror before every run | The same, plus when the mirror was fetched and whether it was stale | The same |

A public GitHub repository needs no token. Without one, GitHub allows 60 API calls an hour per
address; each run of a linked repository makes one to resolve its branch. When that limit is reached,
the check and the run say so (`rate_limited`), and a token raises it to 5 000 an hour: a fine-grained
token with *Contents: read* is enough, even for a public repository. The archive of a commit is
downloaded once and kept (see the layout below), so a retry or a second Loop on the same commit costs
only that one call. A token that passed an earlier check and is then rejected has most likely
expired: the check says so, and you replace it under **Edit**. `github.com` is in `TRALALA_REPOSITORY_HOSTS` by default, so
a GitHub repository can also be read through the mirror, for example one whose archive is larger
than the API path accepts.

Either way, a run reads at most 200 files and 200 KB of text per repository, skips build output,
dependencies, lock files, binaries and images, puts the README, `AGENTS.md` and `docs/` first, and
shares `TRALALA_GENERATION_CONTEXT_CHARS` with the Loop's documents (the documents come first). The
GitHub download is capped at 2 MB of archive; the mirror's archive of one commit at 128 MB.

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
4. **Test access**: the row's *Test access* button, or `POST /repositories/{id}/check`. For Git over
   HTTPS this runs `git ls-remote` only: it clones nothing, names the main branch and stores it as
   the row's *Default branch*. `status` is `ok`, `branch_missing` when the *Branch* field names a
   branch the remote does not have, or one of the codes under [Troubleshooting](#troubleshooting).
5. **Link it to a board**: open the board → **Edit board → Repositories**, or
   `PATCH /boards/{id}` with `{"repository_ids": ["<id>", ...]}`. The list replaces the board's
   selection; an empty list unlinks every repository. A board may link several repositories and a
   repository may serve several boards.
6. **Run an analysis.** The first run clones the mirror; every later run fetches the newest commit
   first. The document dialog then says what the run read: "based on app @ 1a2b3c4d, 42 files,
   96 KB".

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
| `TRALALA_GENERATION_CONTEXT_CHARS` | `400000` | What one run sends the model, documents and repository snapshots together. The documents come first; the repositories share the rest in link order, and what one does not use carries over to the next |
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
4. `git archive` of the branch is read like the GitHub archive: the same filters, caps, order and
   budget.

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
Fine-grained tokens. *Resource owner*: the owner of the repository; *Repository access*: *Only select
repositories*, this one; *Repository permissions* → **Contents: Read-only**; a short expiry. The
dialog of a GitHub repository carries the same recipe and a command that checks the token.

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

A failure is named by a code, never by the host's or `git`'s own words. The code appears on the
repository's row (the last check, or "Last fetch failed:"), in the run's "based on" line and in the
backend log (`repository_mirror_failed`, `repository_snapshot_failed`, and `git_command_failed` with
a short excerpt of what `git` said).

| Code | What it means | What to do |
| --- | --- | --- |
| `host_not_allowed` | The URL's host is not in `TRALALA_REPOSITORY_HOSTS` | Add the host and restart the backend, or correct the URL |
| `invalid_url` | Not an `https` URL of a repository, or it carries a user name, token, query or fragment | Enter the plain `https://host/path` URL; the token goes in its own field |
| `auth_failed` | The host wants credentials, or refused the token | Add a token, check it with the command under [Tokens](#tokens), or enter it as `<user>:<token>` |
| `not_found` | The repository or branch does not exist, or the token cannot see it | Check the URL and the *Branch* field; give the token read access to this repository |
| `branch_missing` | *Test access* found the remote but not the branch in the *Branch* field | Correct the branch, or clear the field to read the main branch |
| `timeout` | A `git` command ran longer than `TRALALA_REPOSITORY_FETCH_TIMEOUT_SECONDS` | Check that the backend reaches the host; raise the timeout for a large first clone |
| `too_large` | The mirror is larger than `TRALALA_REPOSITORY_MIRROR_MAX_BYTES` after its clean-up (or a GitHub archive over 2 MB) | Raise the limit, or read a smaller branch |
| `git_missing` | The `git` program is not installed where the backend runs | Use the backend image, or install `git` (or set `TRALALA_REPOSITORY_GIT_BINARY`) |
| `fetch_failed` | `git` could not read the repository for another reason | Read the `git_command_failed` log line; try *Rebuild mirror* |
| `stale_mirror` | The last fetch failed; the run read the last good mirror | See [Stale mirror](#stale-mirror) |
| `mirror_cleanup_failed` | The mirror's directory could not be removed: the host still holds a file in it | Close what holds it, then *Remove now* |
| `unauthorized`, `forbidden`, `rate_limited`, `unreachable` | GitHub provider: the token was rejected, lacks access, the API's limit was reached, or GitHub did not answer | Check the token with the dialog's command; add a token to raise the limit; try again later |

## Nothing is executed

The mirror runs `git` with a fixed list of arguments and no shell, and only six commands:
`ls-remote`, `clone`, `fetch`, `archive`, `reflog expire` and `gc`. Every command carries
`-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=never
-c protocol.https.allow=always`, so no hook, file-system monitor or protocol other than HTTPS can
run, and the environment keeps the system's and the account's Git configuration out and turns off
every prompt. The mirror is bare: nothing is checked out, so no file of the repository is ever on
disk as a file to run. What a run reads goes into the prompt as text, and the prompts call it
material to analyse, never instructions. The backend runs as the container's unprivileged user.
