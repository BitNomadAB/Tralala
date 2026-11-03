# Installing Tralala

Tralala runs as one backend process (FastAPI + SQLite) and one web tier (Caddy serving the built
React app and proxying the API). There are two supported ways to get there: **Docker** and **from
source**.

- In a hurry: [Docker](#docker-recommended).
- Developing or debugging the code: [From source](#from-source).
- Once it runs: [Onboarding](Onboarding.md) for the first hour, and
  [Practical commands](practical_commands.md) for start/stop, tests, database checks and updates.
- Something failing: [Troubleshooting](Troubleshooting.md).
- Before you expose it: [Security defaults](Security_defaults.md).

## Prerequisites

Tralala needs these; install them with their own official guides, because those change more often
than this document:

| Component | Version | Official install guide |
| --- | --- | --- |
| Python | 3.13 (3.13 and 3.14 are tested; 3.13 is the version of record) | <https://www.python.org/downloads/> |
| Node.js | 22 LTS or newer | <https://nodejs.org/en/download> |
| pnpm | the version in `frontend/package.json` (`packageManager`) | <https://pnpm.io/installation> |
| Git | recent | <https://git-scm.com/downloads> |
| Docker + Compose | optional, for the container route | <https://docs.docker.com/get-docker/> |

`backend/pyproject.toml` accepts Python `>=3.13,<3.15`. Use **3.13** unless you have a reason not
to: it is what the container image runs, so the container route and a local venv then behave
identically. On Ubuntu 24.04 the system interpreter is older than 3.13, so install one first, for
example with `uv python install 3.13` or the deadsnakes PPA, and create the venv with that
interpreter. The shortest route to the pinned pnpm is `corepack enable`; on Windows that may need
an elevated shell.

The interpreter's SQLite must be 3.37.0 or newer, because new tables are created `STRICT`; check it
with `python -c "import sqlite3; print(sqlite3.sqlite_version)"`. The backend build stops with a
message on an older one. On Linux this is the system library, which Ubuntu 22.04 and newer provide.

## Docker (recommended)

```bash
git clone https://github.com/BitNomadAB/Tralala.git
cd Tralala
cp .env.example .env
```

Edit `.env` and set at least:

```ini
TRALALA_SECRET_KEY=<a long random value>
TRALALA_BOOTSTRAP_PASSWORD=<your own strong password>
```

`TRALALA_SECRET_KEY` signs sessions and seals provider keys. Keep it stable: changing it invalidates
sessions and requires `TRALALA_PREVIOUS_SECRET_KEY` for one start so stored keys can be re-sealed.
`docker compose` refuses to start without an explicit `TRALALA_BOOTSTRAP_PASSWORD`, because shipping
a documented default is exactly what we removed.

```bash
docker compose up -d --build
docker compose ps          # backend and frontend should both be "healthy"
```

The UI is at <http://localhost:8080>. Two containers run:

| Container | Job |
| --- | --- |
| `backend` | FastAPI, the SQLite databases, the backup scheduler |
| `frontend` | Caddy: serves the built SPA, proxies `/api`, `/docs`, `/openapi.json`, `/mcp` and `/llms.txt` |

Volumes, so `docker compose down` keeps your work and `docker compose down -v` removes it:

| Volume | Contents |
| --- | --- |
| `tralala-data` | `registry.sqlite`, every board database, its files, backups |
| `tralala-caddy-data` | TLS certificates and ACME state |
| `tralala-caddy-config` | Caddy's autosaved configuration |

### TLS

TLS is configuration in the web container, not a second service. `TRALALA_SITE_ADDRESS` decides:

| Value | Behaviour |
| --- | --- |
| `:80` (default) | Plain HTTP. Right behind Tailscale Serve, a load balancer or another TLS terminator. |
| `tralala.example.com` | Automatic HTTPS: a public CA for a public name, Caddy's own local CA for a private one. Publish 443 (`TRALALA_HTTPS_PORT=443`) and leave 80 reachable for the ACME challenge and the redirect. |

Set `TRALALA_COOKIE_SECURE=true` once the site is served over HTTPS. Keep
`TRALALA_TRUST_PROXY_HEADERS=true` (the compose default): Caddy is the only caller of the backend, so
trusting its `X-Forwarded-For` is what keeps the sign-in throttle keyed on the real client rather
than on the proxy.

### Behind Tailscale

The simplest private setup keeps plain HTTP inside the tailnet and lets Tailscale terminate TLS:

```bash
docker compose up -d --build
sudo tailscale serve --bg 8080      # https://<host>.<tailnet>.ts.net -> 127.0.0.1:8080
tailscale serve status
```

Then verify the three surfaces through the tunnel, because they take different paths:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<host>.<tailnet>.ts.net/
curl -s https://<host>.<tailnet>.ts.net/llms.txt | head -3     # plain text, not the SPA shell
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Content-Type: application/json" -H "Authorization: Bearer <key>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  https://<host>.<tailnet>.ts.net/mcp
```

## From source

Use this when you want to change the code, run the test suites, or work offline. The commands below
are the same on Windows, macOS and Linux apart from the shell syntax noted in
[Shell differences](#shell-differences).

```bash
git clone https://github.com/BitNomadAB/Tralala.git
cd Tralala
```

### 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
```

Activation is optional: without it, call `.venv/bin/python` (macOS/Linux) or
`.\.venv\Scripts\python.exe` (Windows) explicitly. That is what `AGENTS.md` and the commands in this
documentation assume.

### 2. Frontend

```bash
cd frontend
pnpm install
cd ..
```

### 3. Configure the backend

Create `backend/.env` (gitignored). The values below are the ones that matter for a local install:

```ini
TRALALA_DATA_DIR=../data
TRALALA_BOOTSTRAP_USERNAME=admin
# Leave empty: a generated administrator password lands in <data>/.bootstrap-password
TRALALA_BOOTSTRAP_PASSWORD=
```

- `TRALALA_DATA_DIR` resolves from the working directory (`backend/`), so `../data` keeps the SQLite
  files at the repository root. The default is `backend/data`.
- `TRALALA_SECRET_KEY` is optional locally: without it a per-install secret is generated at
  `<data>/.session-secret`.
- Every setting is listed in [`.env.example`](../.env.example).

### 4. Generate the database rows

The backend's typed database rows are generated from the schema migrations, not stored in the
repository. Generate them once, and again whenever an update brings a new migration:

```bash
cd backend
../.venv/bin/python -m tools.dbgen
cd ..
```

It checks the migrations, writes `backend/app/db/generated/` and checks every SQL statement against
the schema; a second run with nothing changed finishes at once. Without it the backend stops at
start with "The generated database rows are missing: run python -m tools.dbgen". The container
image runs it during `docker compose up --build`.

### 5. Run both processes

```bash
# terminal 1
cd backend
../.venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload

# terminal 2
cd frontend
pnpm dev
```

The backend log shows the registry migration, the board migration batch and
`Application startup complete.`. Vite serves <http://localhost:5173> and proxies `/api`, `/docs`,
`/openapi.json`, `/mcp` and `/llms.txt` to the backend, so the browser only needs the one address.

### Shell differences

| Task | Windows (PowerShell) | macOS / Linux |
| --- | --- | --- |
| Activate the venv | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Run the interpreter | `.\.venv\Scripts\python.exe` | `.venv/bin/python` |
| Set a variable for one command | `$env:VITE_API_PROXY = "http://127.0.0.1:8010"` | `VITE_API_PROXY=http://127.0.0.1:8010` |
| Allow local scripts once | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` | not applicable |

## First sign-in

There is no shared password. On first start the backend creates `admin` with a unique generated
password and writes it to `<data>/.bootstrap-password` with owner-only permissions:

```bash
cat data/.bootstrap-password          # Windows: Get-Content data\.bootstrap-password
```

Sign in as `admin` with that value, change it under **Settings → Your password**, then delete the
file. A password change revokes every session, including your own.

To bring other people in, create the account under **Settings → Users** and hand over the
**invitation link** (`/enrol?token=…`) once. Tralala sends no e-mail. Details and the rules around
keys: [Security defaults](Security_defaults.md).

## Upgrading

```bash
git pull
pip install -r backend/requirements-dev.txt    # backend dependencies
(cd backend && ../.venv/bin/python -m tools.dbgen)  # rows for any new migration
cd frontend && pnpm install && cd ..           # frontend dependencies
docker compose up -d --build                   # Docker installs only
```

Schema migrations run at startup before requests are served, each board is snapshotted first, and a
board that fails is marked `migration_failed` with an admin retry endpoint. There is no ad-hoc DDL
and no manual migration step; schema changes are Alembic revisions. The workflow itself is in
[Loops.md](Loops.md).

Revision `0008_loops` is a structural redesign: a populated pre-Loop database is refused rather than
converted. For a throwaway development install, reset explicitly and deliberately:

```bash
cd backend
../.venv/bin/python -m app.dev_reset            # names the data directory and what it will erase
../.venv/bin/python -m app.dev_reset --confirm  # erases boards, backups and the registry
```

The session secret is kept, and the next start recreates a clean schema.

## Verify the installation

```bash
curl -s http://127.0.0.1:8000/api/v1/health        # {"success": true, "data": {"status": "ok"}}
```

Run what CI runs:

```bash
cd backend
../.venv/bin/python -m tools.dbgen                       # migrations, rows, SQL (always first)
../.venv/bin/python -m ruff check app tests migrations tools
../.venv/bin/python -m pyright                           # strict types
../.venv/bin/python -m pytest                            # unit tests
../.venv/bin/python -m pytest tests/infrastructure       # the small SQLite suite
cd ../frontend
pnpm typecheck
pnpm lint           # Prettier check, then ESLint with zero warnings (`pnpm format` fixes layout)
pnpm test
pnpm build          # also runs typecheck, ESLint and the client build guard
pnpm lint:md        # Markdown lint on the documentation
pnpm test:e2e       # the browser journeys against an isolated stack
```

`pnpm test:e2e` starts its own backend on `:8077` with `frontend/e2e/.data` and Vite on `:5273`, from
an empty data directory every run (`E2E_KEEP_DATA=1` keeps it). It reuses whichever Playwright install
already exists and only downloads Chromium when no browser build is present
(`PLAYWRIGHT_CLI=<path to cli.js>` overrides).

## Where the data lives

| Path | Contents |
| --- | --- |
| `<data>/registry.sqlite` | board metadata, board templates, role templates, actors, credentials |
| `<data>/boards/<uuid>/board.sqlite` | one database per board (schema revision in `alembic_version`) |
| `<data>/boards/<uuid>/attachments/` | uploaded files, named by attachment id |
| `<data>/backups/<board>/` | snapshots; each `backup-<UTC>.sqlite` may have a `-attachments.zip` partner |
| `<data>/exports/` | reserved for generated exports |
| `<data>/.session-secret` | generated session secret when `TRALALA_SECRET_KEY` is unset |
| `<data>/.bootstrap-password` | generated first-administrator password; delete after sign-in |
| `<data>/.process.lock` | OS file lock proving one backend process owns this directory |

A board is its directory: deleting a board removes its database and its files together, duplicating
it copies both, and a backup is the database plus its files.

Read [Architecture.md](Architecture.md) for how the pieces fit together, and
[Onboarding.md](Onboarding.md) for what to do in the first hour.
