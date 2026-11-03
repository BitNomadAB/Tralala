# Practical commands

Day-to-day commands after Tralala is installed: start and stop it, run the tests, inspect the
database and update the parts. One line per command explains what it does and when to use it.

- First-time setup: [Installation.md](Installation.md).
- Something broken: [Troubleshooting.md](Troubleshooting.md).
- Two rules that explain most surprises: **one backend process per data directory**, and **the tests
  are the contract** — if they fail, nothing else matters yet.

The stack has three layers; the commands below are grouped by layer, with the stack itself first.

| Layer | Technology | Where |
| --- | --- | --- |
| Frontend | React 19 + Vite 6 + TypeScript, served by Caddy in a container | `frontend/` |
| Backend | FastAPI + SQLAlchemy on Python 3.13 (3.14 also tested) | `backend/` |
| Database | one SQLite file per board, plus `registry.sqlite` | `<data>/` |

## The stack: start, stop, watch

### Docker (the way to run it on a server)

Run these from the repository root, where `docker-compose.yml` lives.

| Command | What it does |
| --- | --- |
| `docker compose up -d` | Start backend and web tier in the background; use after a config change. |
| `docker compose up -d --build` | Rebuild the images first; use after pulling new code or editing `Caddyfile`. |
| `docker compose ps` | Show both containers and whether they are `healthy` — the fastest first check. |
| `docker compose logs -f backend` | Follow the backend log; every request and every event is one JSON line. |
| `docker compose logs --tail=100 frontend` | Look at the web tier when a page or a proxy route misbehaves. |
| `docker compose restart backend` | Restart only the backend process; a changed `.env` needs `up -d` instead, because the environment is fixed when the container is created. |
| `docker compose stop` | Stop both containers and keep them; `docker compose start` brings them back. |
| `docker compose down` | Remove the containers and the network, **keep** the data volumes. |
| `docker compose down -v` | Remove the containers **and** the data volumes — this deletes every board. |
| `docker compose exec backend ls /data` | Look inside the data volume without leaving the host. |
| `curl -s localhost:8080/api/v1/health` | Prove the stack answers through the web tier. |

`restart: unless-stopped` is set, so containers come back after a reboot or a Docker restart; on a
server that is the whole supervision story unless you wrap it in your own service unit.

### From source (the way to work on the code)

Two processes, two terminals; `Ctrl+C` in each to stop.

| Command | What it does |
| --- | --- |
| `cd backend && ../.venv/bin/python -m uvicorn app.main:create_app --factory --port 8000 --reload` | Start the API on `:8000` and reload on every edit. |
| `cd frontend && pnpm dev` | Start Vite on `:5173`; it proxies `/api`, `/docs`, `/openapi.json`, `/mcp` and `/llms.txt`. |
| `Ctrl+C` | Stop the process in that terminal. |

Run the backend **without** `--reload` to reproduce production behaviour, and never with more than one
worker: the rate limiter, the board locks and the session secret are process-local.

## Layer 1 — Frontend

Run these from `frontend/`.

| Command | What it does |
| --- | --- |
| `pnpm install --frozen-lockfile` | Install exactly the locked dependency versions; what CI does. |
| `pnpm install` | Install and update the lockfile if `package.json` changed. |
| `pnpm dev` | Development server with hot reload on `:5173`. |
| `pnpm typecheck` | `tsc --noEmit`: types only, no output. |
| `pnpm lint` | ESLint with type information (`eslint.config.js`); every rule is an error and any warning fails. |
| `pnpm exec eslint . --fix` | Apply the fixes ESLint can make on its own (import order, braces), then re-run `pnpm lint`. |
| `pnpm test` | Vitest unit and component tests, one run. |
| `pnpm exec vitest` | The same tests in watch mode while you edit. |
| `pnpm exec vitest run src/tests/theme.test.ts` | Only one test file. |
| `pnpm build` | Typecheck, lint, production build and the client build guard (no source maps, no server-only strings). |
| `pnpm preview` | Serve the built bundle locally to check a production build. |
| `pnpm lint:md` | markdownlint on `README.md`, `AGENTS.md`, `docs/` and `public_docs/`; what CI runs. |

### Playwright journeys

The suite is 30 browser journeys across the pages (auth, boards, board lifecycle, drag and drop,
Loops, discussions, mentions, templates, users, agents, repositories, settings). It starts its own stack: backend on
`:8077` with `frontend/e2e/.data`, Vite on `:5273`, serial, from an empty data directory.

| Command | What it does |
| --- | --- |
| `pnpm test:e2e` | Run every journey against a throwaway stack. |
| `pnpm test:e2e -- auth.spec.ts` | Run one spec file; any argument is passed to Playwright. |
| `pnpm test:e2e -- --headed settings.spec.ts` | Watch the browser run one file. |
| `pnpm test:e2e -- --last-failed` | Re-run only what failed in the previous run. |
| `E2E_KEEP_DATA=1 pnpm test:e2e` | Keep `frontend/e2e/.data` to inspect boards after a run (PowerShell: `$env:E2E_KEEP_DATA = "1"`). |
| `npx playwright install chromium` | Install the browser if the runner reports none (it also does this itself). |
| `pnpm test:e2e -- --reporter=html` then `npx playwright show-report` | Write an HTML report and open it; locally the default reporter is the terse list (CI adds HTML). |

Environment variables the config reads: `E2E_PYTHON` (interpreter for the test backend; by default the
repository `.venv`, else `python`/`python3`), `E2E_BACKEND_PORT`, `E2E_FRONTEND_PORT`,
`E2E_ADMIN_PASSWORD` (default `e2e-password`).

If Playwright is not present at all, the runner exits with a message and does not silently skip:
`cd frontend && pnpm add -D playwright` adds it to this package (that is also what CI's e2e job does
with `npx playwright install --with-deps chromium`).

## Layer 2 — Backend

Run these from `backend/`.

| Command | What it does |
| --- | --- |
| `python -m venv .venv` | Create the virtual environment once (from the repository root). |
| `source .venv/bin/activate` / `.\.venv\Scripts\Activate.ps1` | Activate it; optional if you call the interpreter by path. |
| `pip install -r requirements-dev.txt` | Install backend dependencies, including the test tools. |
| `pip install --upgrade -r requirements-dev.txt` | Upgrade them to the newest allowed versions. |
| `pip list --outdated` | Show what could be upgraded; read before upgrading a production install. |
| `python --version` | Check the interpreter; `pyproject.toml` accepts 3.13 and 3.14, and 3.13 is the version of record. |
| `python -m uvicorn app.main:create_app --factory --port 8000 --reload` | Development server. |
| `python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-server-header` | What the container runs: no reload, no banner advertising the server. |
| `python -m pytest` | The whole backend suite — the primary gate. |
| `python -m pytest tests/test_boards.py` | One file. |
| `python -m pytest tests/test_boards.py::test_delete_requires_archive_and_matching_name` | One test. |
| `python -m pytest -k "backup or restore"` | Tests matching a keyword. |
| `python -m pytest -x --lf` | Stop at the first failure, starting with the last failing tests. |
| `python -m pytest -q --tb=short` | Short output for a quick loop. |
| `python -m ruff check app tests migrations` | Lint everything; what CI runs. |
| `python -m ruff check app --fix` | Apply the mechanical fixes. |
| `python -m app.dev_reset` | List what a development reset would erase — it changes nothing. |
| `python -m app.dev_reset --confirm` | Erase boards, backups and the registry; the schema is recreated on next start. |

## Layer 3 — Database

There is no `alembic.ini` and no manual migration step: `MigrationManager` migrates the registry and
then every board **at startup**, each board behind a verified pre-migration snapshot, and marks a
board `migration_failed` if anything goes wrong. Adding a revision happens in code
(`backend/migrations/{registry,board}`), never as ad-hoc DDL.

The SQLite CLI is not required — the Python below ships with the backend's dependencies. Run it from
the repository root and adjust the data directory.

| Command | What it does |
| --- | --- |
| `python -c "import sqlite3; print(sqlite3.sqlite_version)"` | Version of the SQLite engine Python uses (upgrading Python may upgrade it). |
| `python -c "import sqlite3; c=sqlite3.connect('file:data/registry.sqlite?mode=ro', uri=True); print(c.execute('select count(*) from boards').fetchone()[0])"` | How many boards the registry knows, read-only. |
| `python -c "import sqlite3; c=sqlite3.connect('file:data/registry.sqlite?mode=ro', uri=True); print(c.execute('select name, status from boards order by name').fetchall())"` | Every board with its status (`active`, `archived`, `migration_failed`). |
| `python -c "import sqlite3; c=sqlite3.connect('file:data/registry.sqlite?mode=ro', uri=True); print(c.execute('select version_num from alembic_version').fetchone())"` | Registry schema revision in force. |
| `python -c "import sqlite3; c=sqlite3.connect('file:data/boards/<uuid>/board.sqlite?mode=ro', uri=True); print(c.execute('select version_num from alembic_version').fetchone(), c.execute('pragma integrity_check').fetchone())"` | One board's revision and integrity. |
| `curl -s localhost:8000/api/v1/boards/<uuid>/validate` | The same integrity check as an API call, with counts per table (session required). |
| `curl -X POST localhost:8000/api/v1/boards/<uuid>/migrate` | Retry a failed migration (admin); safe to repeat. |
| `curl -X POST localhost:8000/api/v1/boards/<uuid>/backups` | Take a snapshot now; the response lists the files and whether uploads came along. |
| `curl localhost:8000/api/v1/boards/<uuid>/backups` | List snapshots with `created_at`, `has_attachments` and size. |
| `curl -X POST localhost:8000/api/v1/boards/<uuid>/backups/<name>/restore` | Restore a snapshot: database **and** its uploaded files (admin). |
| `python -m app.dev_reset --confirm` | Nuclear option for a throwaway install; recreates the schema on next start. |

Notes worth knowing before you type any of these:

- Stop writing before you touch a file by hand. A live board is owned by the running process; a snapshot
  taken behind the API is consistent, a copy taken with `cp` is not.
- A board is a directory: `<data>/boards/<uuid>/board.sqlite` plus `attachments/`. Delete through the
  API so both go together, or you get a board that cannot be opened — or rows pointing at nothing.
- Do not put `<data>` on a network share: SQLite's WAL mode needs shared memory and will answer
  `disk I/O error`. `TRALALA_PLATFORM_PROFILE=network` fixes transient removals, not WAL.
- Backups are automatic every `TRALALA_BACKUP_INTERVAL_HOURS` (default 24) and the newest
  `TRALALA_BACKUP_KEEP` (default 10) are kept.

## Updating

### Tralala itself

| Command | What it does |
| --- | --- |
| `git status` | Confirm you have no uncommitted work worth keeping before an update. |
| `git fetch --tags --prune` | Download new commits and tags without changing your files. |
| `git pull --ff-only` | Fast-forward to the newest `master`; refuses if your branch diverged. |
| `git tag --sort=-v:refname \| head -5` | Show the newest release tags; an empty answer means this repository has none yet, so `master` is the version. |
| `git checkout <tag>` | Pin your server to a release; `git checkout master` returns to the tip. |
| `pip install -r backend/requirements-dev.txt` | Install any backend dependency the update added. |
| `(cd frontend && pnpm install)` | Install any frontend dependency the update added. |
| `docker compose up -d --build` | Apply it in Docker; migrations run during backend startup. |
| `curl -s localhost:8080/api/v1/health` | Confirm the new version answers before you walk away. |

Before an update on anything you care about: take a backup (`docker compose exec backend ls /data/backups`
to see them, or hit the backups endpoint per board) and note the tag you came from, since rolling back
is `git checkout <previous tag>` plus `docker compose up -d --build`. The data directory is not
downgraded by that, so a rollback across a schema change needs a snapshot from before the upgrade.

### Frontend dependencies (React, Vite, TypeScript)

| Command | What it does |
| --- | --- |
| `pnpm outdated` | List packages with newer versions, and what the current ranges allow. |
| `pnpm update` | Move within the declared ranges (patch and minor). |
| `pnpm up react react-dom @types/react @types/react-dom` | The deliberate React upgrade; rewrites `package.json` ranges. |
| `pnpm up vite vitest typescript` | The same for the build and test toolchain. |
| `pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm test:e2e` | The gate: types, lint, unit tests, build and the journeys. |
| `pnpm rebuild` | Re-run install scripts, e.g. if a native dependency broke after an upgrade. |

React is pinned to `^19.2` (the code uses `useEffectEvent`), Vite to `^6`, TypeScript to `~5.7` in `frontend/package.json`. Update the
range and the code together, never only the lockfile.

### Backend dependencies (FastAPI, SQLAlchemy, Alembic, httpx)

| Command | What it does |
| --- | --- |
| `pip install -r requirements.txt --upgrade` | Upgrade the runtime dependencies within their ranges. |
| `pip install -r requirements-dev.txt --upgrade` | The same, plus the test tools. |
| `python -m pytest && python -m ruff check app tests migrations` | The gate after an upgrade. |
| `pip install "fastapi==<version>"` | Pin one package deliberately when a range is too wide for you. |

`requirements.txt` holds what the app imports at runtime (`httpx` and `anyio` included, because the
provider calls and the event stream need them). `requirements-dev.txt` adds pytest and ruff.

### Python and SQLite

| Command | What it does |
| --- | --- |
| `python --version` | 3.13 is the version of record; 3.14 is also tested. |
| `python -c "import sqlite3; print(sqlite3.sqlite_version)"` | SQLite is compiled into Python; there is no separate package to update. |
| `python -m venv .venv --upgrade` | Re-point an existing virtual environment at a newer interpreter. |
| `python -m pip install --upgrade pip` | Keep pip itself current before upgrading anything else. |

A newer Python usually brings a newer SQLite. That is safe here: the databases are ordinary SQLite
files and the app checks integrity on every migration and restore. Take a backup before a Python
upgrade on a server anyway — it costs one command.
