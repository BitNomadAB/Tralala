# Tralala (Work in progress, if you care about your data dont use this just yet.)

Tralala is a self-hosted, AI-native planning and delivery application. Humans work with Loops inside
Boards; agents get the same capabilities through a documented REST API (and, where the browser
supports it, WebMCP tools). Every board is its own SQLite database. No cloud services, no external
AI provider, no Redis or Postgres.

```
App  ->  Board  ->  Loop  ->  Loop-owned Kanban (Tickets) + Info / Analysis / RoadMap + Phases
```

- Spec: `Tralala — Product Requirements & Technical Architecture Specification v1.0`
- Development method: Ralph Loop (`.ralph/`, `AGENTS.md`)

## Test version: the administrator account

This build is a **test version**, so every instance started from the instructions below uses the same
administrator account. Nothing else has to be configured to get in:

| Username | Password |
| --- | --- |
| `admin` | `tralala-dev-1` |

Sign in at <http://localhost:5173>, then change it under **Settings → Your password** (fields
"Current password" and "New password", at least 8 characters). A password change revokes every
session, including your own, so sign in again with the new one.

Two things keep this honest:

- The value is not a built-in default. It works because `TRALALA_BOOTSTRAP_PASSWORD=tralala-dev-1` is
  set in `.env` (see [`.env.example`](.env.example)) or in the process environment. With no value, or
  with a placeholder such as `admin` or `change-me`, the server generates a random password into
  `<data>/.bootstrap-password` on first start.
- It only applies while no user exists. Once you have changed the password, the bootstrap value is
  ignored for that installation.

Change the password before the instance is reachable by anyone else, and never run a network-facing
instance on the shared test password.

### Invite people instead of sharing a password

An administrator creates the account under **Settings → Users** and presses the **invitation link**
icon next to it. The dialog shows a one-time link (`/enrol?token=…`) that is displayed once; send it
through a channel you already trust. The person opens it, chooses their own password and is signed
in — you never know that password, and the link stops working as soon as it is used (or replaced by a
new one, after `TRALALA_INVITE_TTL_HOURS`, default 72 hours). Tralala sends no e-mail; delivery is
yours. See [decisions/0014](docs/decisions/0014-enrolment-links-instead-of-email-verification.md).

## Features

- Boards with an isolated SQLite database each; create, rename, duplicate, archive, export/import,
  delete with confirmation and typed-name safety.
- Loops: each Board contains Loops, and each Loop owns its columns, Tickets and planning documents.
  A Loop moves through Draft, Analysis review, Planning, RoadMap review, Ready, In progress,
  Replanning, Awaiting QA and Completed, and Readiness explains every blocker.
- Revisioned planning documents: human-authored Info, an AI technical analysis with a
  plain-language human view, and a structured RoadMap whose numbered Phases and planned Tickets are
  published atomically after a human approval. Generated content is validated before it can be
  approved; approvals are bound to exact revisions and go stale when an input changes.
- Version-bound human gates: agents may generate, plan and execute eligible Tickets, but only a
  signed-in person approves plans, confirms human-only actions, accepts QA and finalizes a Loop.
- QA handover with one QA Task carrying an agent view and a human view of the same scenarios,
  scenario-level results, and a human acceptance decision.
- Board-local history: completed Loops become immutable, searchable snapshots; legacy material can
  be imported into the same read-only envelope and is always labelled as unvalidated.
- Reusable templates: save a Loop's columns and a board's labels, or compose one in Settings, then
  start a board from that template. Templates can be edited and deleted at any time.
- AI agent foundation: ten built-in role templates (editable, duplicable, restorable), including the
  Analytics agent that turns Info into an evidence-based analysis, and separate
  agent configurations with their own OpenAI-compatible or A2A endpoint, encrypted API key, model
  limits and connection test. Role templates are shared; each discussion keeps a snapshot of the
  prompt it used.
- Alembic-managed schema chains for the registry and boards: eager startup migration, verified
  pre-migration backups, integrity checks and a `migration_failed` state with an admin retry.
- Lists with drag-and-drop ordering and gap-based integer positions.
- Tickets (cards) with stable keys, Markdown descriptions, priority, due dates, labels, checklists,
  comments, activity history, archive/restore and optimistic-concurrency versions. Transfer between
  Loops or Boards is intentionally not supported; amend the plan instead.
- Dashboard search, board filtering, FTS5 ticket search (with `LIKE` fallback), global search across
  boards and Loops, overdue filters, an activity panel and full-text history search.
- Three theme kits: CareNomad (midnight navy), MatchMap (ink and ember) and Classic (the original
  flat palette, no motion), each with dark, light and system modes. Colour and the pulsing CSS-only
  motion change; the font and layout stay the same and `prefers-reduced-motion` turns motion off.
  The choice is saved per account, so it follows the person rather than the browser.
- Local accounts with two roles: every signed-in person works with boards, agents and
  discussions; only an administrator creates, disables or resets accounts and manages the global
  API keys. Server-side sessions
  (revocable, CSRF double-submit) and expiring, rotatable bearer tokens for agents; the session
  secret is generated per install when not configured.
- Idempotent creation, structured agent-facing errors, per-actor rate limiting, `Idempotency-Key`
  replay protection, JSON logs with request ids.
- Backups with verified snapshots, restore, and integrity validation.
- WebMCP capability detection with context-scoped tool registration behind a replaceable adapter.

## Schema migrations

Registry and board schemas are Alembic chains under `backend/migrations`. The app migrates the
registry, then every board, at startup before serving requests; each board is snapshotted first,
validated afterwards, and marked `migration_failed` (with an admin retry endpoint) if anything
fails. Add schema changes as a new revision - never as ad-hoc DDL. See
[docs/database.md](docs/database.md#schema-migrations-alembic).

Revision `0008_loops` is a structural redesign and refuses to convert a populated pre-Loop
database. Reset development data explicitly, never automatically:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.dev_reset            # lists the data directory and targets
..\.venv\Scripts\python.exe -m app.dev_reset --confirm  # erases boards, backups and the registry
```

The command keeps the session secret and the next start recreates a clean schema. The Loop
workflow itself is described in [docs/loops.md](docs/loops.md).

## Requirements

| Component | Version | Why |
| --- | --- | --- |
| Python | 3.13 or newer | `backend/pyproject.toml` requires `>=3.13` |
| Node.js | 22 LTS or newer | Vite 6 dev server and production build |
| pnpm | 10.x (10.33 through corepack) | frontend package manager (`packageManager` field) |
| Git | recent version | clone the repository |
| Docker + Compose | optional | alternative to a local Python/Node install |

If your machine already has a newer Python (3.14 or later), use it instead of 3.13 in the commands
below; the backend accepts any version from 3.13 up.

The application runs as two processes: FastAPI on `http://127.0.0.1:8000` and Vite on
`http://127.0.0.1:5173`. Vite proxies `/api`, `/docs` and `/openapi.json` to the backend, so the
browser only ever needs <http://localhost:5173>.

## Install and run on Windows (PowerShell)

Tested on Windows 10/11 with PowerShell 7; Windows PowerShell 5.1 works with the same commands.

### 1. Install Python 3.13

```powershell
winget install -e --id Python.Python.3.13
py -3.13 --version
```

If `py` is not available, install from <https://www.python.org/downloads/windows/> and enable
"Add python.exe to PATH".

### 2. Install Node.js 22 and pnpm

```powershell
winget install -e --id OpenJS.NodeJS.LTS
node --version
corepack enable
corepack prepare pnpm@10.33.0 --activate
pnpm --version
```

`corepack enable` may need an elevated PowerShell. Alternatively run `npm install -g pnpm@10`.

### 3. Get the code

```powershell
git clone https://github.com/BitNomadAB/Tralala.git
cd Tralala
```

### 4. Create the virtual environment and install the backend

```powershell
py -3.13 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements-dev.txt
```

Activation is optional. Without it, replace `python` below with `.\.venv\Scripts\python.exe`.

### 5. Install the frontend

```powershell
cd frontend
pnpm install
cd ..
```

### 6. Configure the backend

Create `backend\.env` (gitignored) with:

```ini
TRALALA_SECRET_KEY=replace-with-a-long-random-string
TRALALA_BOOTSTRAP_USERNAME=admin
TRALALA_BOOTSTRAP_PASSWORD=tralala-dev-1
TRALALA_DATA_DIR=..\data
```

- `TRALALA_SECRET_KEY` is optional; without it a per-install secret is generated at
  `data\.session-secret`.
- If `TRALALA_BOOTSTRAP_PASSWORD` is empty or a placeholder such as `admin` or `change-me`, a random
  password is generated on first start and written to `data\.bootstrap-password` (owner-only).
  Sign in, change it under Settings, then delete the file.
- `TRALALA_DATA_DIR` is resolved from the working directory (`backend\`), so `..\data` keeps the
  SQLite files at the repository root. The default is `backend\data`.

### 7. Start the backend (terminal 1)

```powershell
cd backend
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

The startup log shows the Alembic registry migration, the board migration batch and
`Application startup complete.`.

### 8. Start the frontend (terminal 2)

```powershell
cd frontend
pnpm dev
```

### 9. Open the application

<http://localhost:5173> - sign in as `admin` with the test password from [Test version](#test-version-the-administrator-account). API documentation:
<http://localhost:5173/docs> after sign-in. Stop both processes with `Ctrl+C`.

## Install and run on Ubuntu / Debian (bash)

Tested on Ubuntu 24.04. Python 3.13 is not in the 24.04 archive, so the deadsnakes PPA is used.

### 1. Install Python 3.13, Git and build tools

```bash
sudo apt update
sudo apt install -y software-properties-common git curl build-essential
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.13 python3.13-venv
python3.13 --version
```

On Ubuntu 25.04+ or Debian trixie the two `python3.13` packages are usually available without the
PPA.

### 2. Install Node.js 22 and pnpm

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node --version
sudo corepack enable
corepack prepare pnpm@10.33.0 --activate
pnpm --version
```

If corepack stops with a signature error, run
`COREPACK_ENABLE_DOWNLOAD_PROMPT=0 sudo -E corepack prepare pnpm@10.33.0 --activate`, or
`sudo npm install -g pnpm@10`.

### 3. Get the code

```bash
git clone https://github.com/BitNomadAB/Tralala.git
cd Tralala
```

### 4. Create the virtual environment and install the backend

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
```

### 5. Install the frontend

```bash
cd frontend && pnpm install && cd ..
```

### 6. Configure the backend

```bash
cat > backend/.env <<'EOF'
TRALALA_SECRET_KEY=replace-with-a-long-random-string
TRALALA_BOOTSTRAP_USERNAME=admin
TRALALA_BOOTSTRAP_PASSWORD=tralala-dev-1
TRALALA_DATA_DIR=../data
EOF
```

Generate a secret with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`. Leaving the secret out is also
supported (a per-install secret is generated).

### 7. Start the backend (terminal 1)

```bash
cd backend
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

### 8. Start the frontend (terminal 2)

```bash
cd frontend
pnpm dev
```

### 9. Open the application

<http://localhost:5173> - sign in as `admin` with the test password from [Test version](#test-version-the-administrator-account). API documentation:
<http://localhost:5173/docs> after sign-in. Stop both processes with `Ctrl+C`.

## Install and run on macOS (zsh/bash)

Tested on macOS 14/15 on Apple Silicon and Intel.

### 1. Install Homebrew (if missing), Python 3.13, Node.js 22 and pnpm

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.13 node@22 pnpm git

# python@3.13 and node@22 are keg-only in Homebrew, so put them on PATH for this shell:
export PATH="$(brew --prefix python@3.13)/bin:$PATH"
export PATH="$(brew --prefix node@22)/bin:$PATH"

python3.13 --version
node --version
pnpm --version
```

Add the two `export PATH` lines to `~/.zshrc` to keep them in new shells.

### 2. Get the code

```bash
git clone https://github.com/BitNomadAB/Tralala.git
cd Tralala
```

### 3. Create the virtual environment and install the backend

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
```

### 4. Install the frontend

```bash
cd frontend && pnpm install && cd ..
```

### 5. Configure the backend

```bash
cat > backend/.env <<'EOF'
TRALALA_SECRET_KEY=replace-with-a-long-random-string
TRALALA_BOOTSTRAP_USERNAME=admin
TRALALA_BOOTSTRAP_PASSWORD=tralala-dev-1
TRALALA_DATA_DIR=../data
EOF
```

Generate a secret with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`, or omit the line to let the server
generate one.

### 6. Start the backend (terminal 1)

```bash
cd backend
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

### 7. Start the frontend (terminal 2)

```bash
cd frontend
pnpm dev
```

### 8. Open the application

<http://localhost:5173> - sign in as `admin` with the test password from [Test version](#test-version-the-administrator-account). API documentation:
<http://localhost:5173/docs> after sign-in. Stop both processes with `Ctrl+C`.

## Run with Docker (any operating system)

```bash
cp .env.example .env
# the copied file already carries the shared test password (README: "Test version"); set
# TRALALA_SECRET_KEY to a long random string, then start and change the password after sign-in
docker compose up --build
```

The UI is served at <http://localhost:8080>; `/api`, `/docs` and `/openapi.json` are proxied to
the backend container. Data lives in the `tralala-data` volume, so `docker compose down` keeps it
and `docker compose down -v` removes it.

## Where the data lives

| Path | Contents |
| --- | --- |
| `<data>/registry.sqlite` | board metadata, board templates, actors and API credentials |
| `<data>/boards/<uuid>/board.sqlite` | one database per board (schema revision in `alembic_version`) |
| `<data>/backups/<board>/` | on-demand and pre-migration snapshots |
| `<data>/.session-secret` | generated session secret (when `TRALALA_SECRET_KEY` is unset) |
| `<data>/.bootstrap-password` | generated first-administrator password; delete after sign-in |

Schema migrations run at startup, before requests are accepted. If one fails, the board is marked
`migration_failed`, writes are rejected and the pre-migration backup is kept; fix the cause and
retry with `POST /api/v1/boards/<id>/migrate` (admin) or restore the backup.

## Verify the installation

Health check:

```bash
# Linux / macOS
curl -s http://127.0.0.1:8000/api/v1/health
```

```powershell
# Windows
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Run the automated checks:

```bash
# Linux / macOS
cd backend && ../.venv/bin/python -m pytest && ../.venv/bin/python -m ruff check app tests migrations
cd ../frontend && pnpm test && pnpm build
```

```powershell
# Windows
cd backend; ..\.venv\Scripts\python.exe -m pytest; ..\.venv\Scripts\python.exe -m ruff check app tests migrations
cd ..\frontend; pnpm test; pnpm build
```

`pnpm build` also runs the client build guard (no source maps, no server-only strings).
`pnpm test:e2e` runs the 27 Playwright journeys against an isolated stack (backend `:8077` with
`frontend/e2e/.data`, Vite `:5273`). The stack starts from an empty data directory on every run, so
a previous run's boards and appearance preferences cannot change the result (`E2E_KEEP_DATA=1`
keeps them for inspection). It reuses whichever Playwright install already exists (local
dependency, global install or npx cache), links it into `frontend/node_modules`, and only downloads
Chromium when no browser build is present; override with `PLAYWRIGHT_CLI=<path to cli.js>`.

## Troubleshooting

- **`python` is not recognised (Windows)** - activate the virtual environment or call
  `.\.venv\Scripts\python.exe` explicitly.
- **`Activate.ps1 ... execution policy`** - run
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that shell.
- **`corepack` signature or download error** - run
  `COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack prepare pnpm@10.33.0 --activate`, or install pnpm
  with npm.
- **Port already in use** - start uvicorn on another port and point Vite at it:
  `--port 8010` plus `VITE_API_PROXY=http://127.0.0.1:8010 pnpm dev` (PowerShell:
  `$env:VITE_API_PROXY = "http://127.0.0.1:8010"`).
- **Login fails after a fresh install** - the bootstrap password only applies while no user exists.
  If it was empty or a placeholder, read the generated one from `<data>/.bootstrap-password`.
- **Locked out after repeated sign-in attempts** - the throttle returns `429` with
  `details.retry_after_seconds`; wait that long or restart the backend.
- **Board shows `migration_failed`** - read the backend log event `migration_failed`, fix the
  cause, then use the retry button in the UI or `POST /api/v1/boards/<id>/migrate`.

## Security defaults


- The session secret is generated per install (`<data>/.session-secret`, owner-only) when
  `TRALALA_SECRET_KEY` is unset; the published fallback is never used.
- The application ships no built-in password: without an explicit
  `TRALALA_BOOTSTRAP_PASSWORD` (and for placeholders such as `admin` or `change-me`) a random
  password is written once to `<data>/.bootstrap-password`. In this **test version** the value in
  [`.env.example`](.env.example) is a shared starting password, so change it on first sign-in
  ([Test version](#test-version-the-administrator-account)); it is honoured only while no account
  exists.
- Sessions are rows in the registry; logout, a password change, a role change and disabling an
  account revoke them. Expired sessions are purged at startup.
- Sign-in is throttled per username and per client address with exponential backoff
  (`X-Forwarded-For` is only trusted with `TRALALA_TRUST_PROXY_HEADERS=true`).
- Passwords need at least 8 characters (`TRALALA_PASSWORD_MIN_LENGTH`, the floor is 8) and cannot
  equal the username. Changing your own password requires the current one and signs out every device.
- API tokens expire after 90 days by default (`TRALALA_CREDENTIAL_DEFAULT_TTL_DAYS`, `0` for none),
  can be rotated with one click, and can never hold `credentials:admin` or `users:admin`. Only
  administrators see and manage them.
- Provider keys are sealed with a key derived from the session secret. After rotating
  `TRALALA_SECRET_KEY`, set `TRALALA_PREVIOUS_SECRET_KEY` for one start: stored keys are re-sealed
  with the new secret, then the old value can be removed.
- `/docs` and `/openapi.json` require a session (`TRALALA_DOCS_REQUIRE_AUTH=true`); set
  `TRALALA_ENABLE_DOCS=false` to remove them entirely.
- `/api/v1/meta` and `/api/v1/auth/scopes` require authentication; API responses carry
  `Cache-Control: no-store`; 401 responses advertise `WWW-Authenticate: Bearer`.
- API errors never echo server paths or driver text; details stay in the server log.
- The production bundle is checked by `scripts/check-client-build.mjs` for source maps and
  server-only strings as part of `pnpm build`.
- Containers start uvicorn with `--no-server-header` and nginx with `server_tokens off`.

## Agent usage

An agent that works with Tralala rather than inside it — a coding agent on a developer's machine —
needs two things: the URL and a token.

```text
GET  /llms.txt                  # public bootstrap: envelope, Loop lifecycle, rules, tool list
POST /mcp                       # the curated worker tools, MCP over JSON-RPC 2.0 (Bearer)
GET  /api/v1/boards/<id>/actors  # people you may assign, agents you may ask
```

```bash
# 1. Create an "interaction agent access" key in Settings -> New agent access. Any signed-in person
#    may issue one for their own machine; it is shown once and belongs to that account. A worker
#    needs boards:read, loops:read, cards:read, cards:write, comments:write, discussions:read and
#    discussions:write; add loops:write and loops:generate to start Loops and analyses.
export TRALALA_TOKEN="trl_..."

# 2. Take the ids from the tools - never guess one.
curl -s -X POST "http://localhost:8000/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"read_board",
       "arguments":{"board_id":"<board-uuid>"}}}'
```

The ten worker tools are `read_board`, `read_loop`, `read_ticket`, `create_loop`, `write_info`,
`run_analysis`, `assign_ticket`, `move_ticket`, `comment_ticket` and `ask_agents`. Together they let a
person and their agent agree an intent, open a Loop for it, write the Info while the Loop is still
speculative, ask the agents for an Analysis and then track the Tickets it produces. They cannot
create boards or Tickets, archive anything, write a RoadMap, or approve a gate; changing Info after
planning has started is a person's decision. The REST API stays available for everything else:
discover boards and Loops, list columns and Tickets, search, submit Analysis and RoadMap candidates,
read readiness, update checklists, read activity, find overdue work. Approving a document, confirming
a human Ticket, accepting QA and finalizing a Loop stay with a signed-in person, and card text is
never treated as instructions.

The local role agents are readers and discussion partners: a run invokes them, they never
authenticate, and they never change a Ticket or a line of code. The worker surface is described in
[docs/api.md](docs/api.md) and decided in
[docs/decisions/0015-worker-surface-mcp-and-llms-txt.md](docs/decisions/0015-worker-surface-mcp-and-llms-txt.md).

## Layout

```
backend/app/{api,core,schemas,services,storage}   FastAPI service layer and SQLite storage
frontend/src/{app,features,lib,webmcp,themes}     React UI, typed API client, WebMCP adapter
docs/                                             architecture, API, database, decisions
.ralph/                                           prd.json, progress.txt, prompt.md
scripts/ralph/run.ps1                             bounded Ralph Loop harness
```

Read `AGENTS.md` before changing code. Architecture decisions live in `docs/decisions/`.

## Known limitations

- Accounts are administrator-provisioned: there is no self-registration, and a person joins through an
  invitation link. One backend process per data directory, multiple worker tokens.
- Run one backend process per data directory: rate limiting, board locks and SQLite writes assume a
  single writer (no horizontal scaling yet).
- Search and board views page at 200 items; deeper result sets use `offset`/`limit` or filters.
- No real-time collaboration, attachments, notifications or cloud sync (explicit MVP exclusions).
- WebMCP execution is not automated because the browser API is experimental and unavailable in
  the test Chromium; the adapter contract is unit-tested and the UI degrades gracefully.
- E2E runs are serial (`workers: 1`) against a fresh data directory; they are not yet wired into a
  CI workflow.

## Licence and contributing

Tralala is **source-available, not open source**. It is published under the
[PolyForm Noncommercial License 1.0.0](LICENSE): you may use, change and share it for any
noncommercial purpose — personal projects, study, experiment and research, and use by charities,
educational institutions, public research bodies, public safety and health organizations,
environmental organizations and government institutions.

**Any commercial use requires a commercial licence from BitNomad AB** — including internal use in a
business and evaluating the software for a commercial purpose. Contact
[tralala@bitnomad.se](mailto:tralala@bitnomad.se) for terms.

Copyright 2026 BitNomad AB. Attribution and the required notice are in [NOTICE](NOTICE).

Contributions are welcome. Because the project is licensed to different recipients under different
terms, non-trivial contributions require a signed [Contributor License Agreement](CLA.md) — you keep
your copyright and grant BitNomad AB the right to relicense your work — plus a DCO sign-off on each
commit (`git commit -s`). Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and report security issues
privately to [tralala@bitnomad.se](mailto:tralala@bitnomad.se) rather than in a public issue.


