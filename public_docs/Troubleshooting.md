# Troubleshooting

The command reference lives in [practical_commands.md](practical_commands.md). Start with the three
facts that explain most surprises:

1. **One backend process per data directory.** A second process refuses to start because a lock file
   is held. That is deliberate: the rate limiter, the per-board locks and the session secret live
   inside that process.
2. **The administrator password is generated, not published.** It is in `<data>/.bootstrap-password`
   until you change it.
3. **A board is a directory.** `<data>/boards/<uuid>/` holds the database and the uploaded files; if
   one is removed without the other, the board is broken. Use the API, never `rm`.

## Installation and tooling

- **`python` is not recognised (Windows)** — activate the virtual environment or call
  `.\.venv\Scripts\python.exe` explicitly.
- **`Activate.ps1 ... execution policy`** — run
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that shell.
- **`corepack` signature or download error** — `COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack prepare
  pnpm@10.33.0 --activate`, or install pnpm with `npm install -g pnpm@10`. See
  <https://pnpm.io/installation>.
- **`pnpm install` picks the wrong package manager** — this repository is pnpm-only; the version is
  pinned in `frontend/package.json` under `packageManager`.
- **Python is too old** — `backend/pyproject.toml` requires `>=3.13,<3.15`, and 3.13 is the version
  of record. Check with `python --version`; the error appears at install time, not at run time.

## Sign-in and accounts

- **Login fails after a fresh install** — the bootstrap password only applies while no account
  exists. If it was empty or a placeholder, read the generated one from `<data>/.bootstrap-password`.
- **Set a password in `.env` but it does not work** — `admin`, `password`, `change-me`, `changeme`,
  `tralala-dev-1` and an empty value are all treated as "no password chosen", so a generated one was
  written instead. Read the file.
- **Locked out after repeated attempts** — the sign-in throttle answers `429` with
  `details.retry_after_seconds`. Wait that long. Restarting the backend clears it, which also means a
  restart forgives an attacker; the throttle is a brake, not a lockout policy.
- **`403 csrf_failed` on a write** — a cookie-authenticated request needs the `X-CSRF-Token` header
  equal to the `tralala_csrf` cookie. Bearer-token requests never need it.
- **Everyone is throttled at once** — the backend is seeing one address for all clients. Behind a
  proxy set `TRALALA_TRUST_PROXY_HEADERS=true` (the compose default); the proxy must send
  `X-Forwarded-For`.

## The web tier (Caddy)

- **The UI loads but every API call 404s** — the web container is proxying somewhere else. Check
  `TRALALA_BACKEND` (default `backend:8000`), and that Caddy's container can resolve that name.
- **`/llms.txt` returns HTML** — the SPA fallback caught it. That means the Caddyfile is not the
  bundled one, or the site block is missing the `@worker` matcher. Rebuild the image.
- **HTTPS does not work on a hostname** — Caddy needs ports 80 and 443 reachable for the ACME
  challenge and the certificate. With a non-default mapping (`TRALALA_HTTPS_PORT=8443`) the redirect
  target does not follow; map `443:443` for a real certificate.
- **Certificates are re-issued on every deploy** — the `tralala-caddy-data` volume is missing, so
  Caddy starts with an empty certificate store. Repeated re-issues can hit CA rate limits.
- **`Server` header reappears** — another proxy in front of Caddy is adding it; Caddy itself sends
  none.
- **A large upload fails with an HTML page or a dropped connection** — the body exceeded the proxy
  ceiling (`request_body max_size 9MB`). The backend's own ceiling (`TRALALA_MAX_REQUEST_BYTES`,
  default 8 MiB) is what normally answers, in the JSON envelope. Raise both together.

## Tailscale

- **`tailscale serve` answers 502** — the local port is wrong: `tailscale serve --bg 8080` must match
  `TRALALA_HTTP_PORT`. Check with `docker compose ps` and `tailscale serve status`.
- **Login works but the session drops on every request** — cookies were issued for a different host.
  Use one address consistently, and set `TRALALA_COOKIE_SECURE=true` for the HTTPS name.
- **An agent on a laptop cannot reach `/mcp`** — the tailnet ACL must allow that device to the host,
  and the agent needs the token. Network first, then the key; the token cannot grant reachability.

## Boards, backups and files

- **Board shows `migration_failed`** — read the backend log event `migration_failed`, fix the cause,
  then use the retry button or `POST /api/v1/boards/<id>/migrate`. The pre-migration snapshot is
  kept.
- **`422 board_import_invalid` on an import** — the archive's `board.sqlite` is not a board this
  installation can take; `details.reason` says why and `details.detail` carries SQLite's answer.
  Nothing was created. `unknown_schema_revision` means the archive comes from a newer release: import
  it there, or upgrade this installation first.
- **`503 board_database_unreadable`, or the log event `board_database_unreadable`** — SQLite cannot
  read that board's `board.sqlite` (`details.sqlite_error`: `SQLITE_NOTADB` or `SQLITE_CORRUPT`). The
  board list and startup step past it, and the next start marks it `migration_failed`. Stop the
  backend, copy a snapshot from `data/backups/<board id>/` over `data/boards/<board id>/board.sqlite`
  and start again; or archive the board and delete it.
- **`409 board_files_busy` when deleting a board** — a file in the board directory is held by
  another process (on Windows a scanner or an indexer; elsewhere a permission, a read-only volume or a
  network share). The board was **not** deleted and still has its data; the response names the
  leftover directory in `details.leftover`. Release the file and retry.
- **`TRALALA_PLATFORM_PROFILE`** — `auto` follows the operating system, `windows` expects a held file
  to be retryable, `posix` does not, `network` adds the transient retries an NFS/SMB share needs.
  It changes retry policy only, never the locking mechanism. Do not put a live board on a share:
  SQLite's WAL mode needs shared memory and will answer `disk I/O error`.
- **`422 board_backup_invalid` on a restore** — the snapshot failed SQLite's checks and was not
  restored; the board kept its database. `details.reason` says which check (`not_a_database`,
  `integrity_check_failed`, `foreign_key_check_failed`) and `details.detail` what SQLite found.
  Restore an older snapshot from the same list instead.
- **`board.sqlite-wal` and `board.sqlite-shm` next to `board.sqlite`** — normal. SQLite's WAL mode
  writes changes to the `-wal` file first and coordinates readers through the `-shm` file; both are
  part of the database while it is open, and SQLite removes them when the last connection closes.
  The backend empties the `-wal` file when a board goes idle, is restored or the backend stops, so it
  stays small. Never delete or copy them by hand while the backend runs: committed changes can still
  be in the `-wal` file. To copy a board, use a backup or an export.
- **Restore said `attachments.skipped: true`** — the snapshot predates the file archive. The database
  was restored and the current files were kept; the response carries a `warning` saying so.
- **A restored board misses recent uploads** — expected for a snapshot older than the uploads. Check
  `has_attachments` and `created_at` in `GET /api/v1/boards/<id>/backups` before restoring.

## Processes, ports and startup

- **"The generated database rows are missing: run python -m tools.dbgen"** — a backend run from
  source imports typed rows generated from the schema migrations (the unit tests say "... are
  stale" when a migration is newer than the rows). From `backend/`, run the tool with the venv's
  interpreter, `../.venv/bin/python -m tools.dbgen` (Windows: `..\.venv\Scripts\python.exe`), after
  cloning and after every pull that brings a migration. The container image generates them while it
  is built.
- **"This data directory is already in use by another Tralala process"** — a second backend is
  running against the same directory, or a container and a local process share a bind mount. Stop
  one. The lock is an OS file lock and is released when the process exits, so there is no stale lock
  to delete.
- **Port already in use** — start uvicorn elsewhere (`--port 8010`) and point Vite at it:
  `VITE_API_PROXY=http://127.0.0.1:8010 pnpm dev`
  (PowerShell: `$env:VITE_API_PROXY = "http://127.0.0.1:8010"`).
- **`413 payload_too_large` on an upload** — the request body exceeded
  `TRALALA_MAX_REQUEST_BYTES` (default 8 MiB). Attachments cannot exceed it either.
- **`503 generation_unavailable`** — no usable generation agent: configure an OpenAI-compatible or
  A2A agent in **Settings → Agents**, enable it, and make it a member of the board.

## Reading the backend log

Every line the backend writes is one JSON object: `ts` (UTC), `level`, `event` (what happened, such
as `http_request` or `backup_failed`), `logger`, `request_id`, then the event's own fields. A logged
exception adds its traceback as `exc_info`.

- **Everything one request did** — every line written while a request is served carries its id, so
  the `X-Request-ID` of a response finds the `http_request` line and whatever else that request
  logged: `docker compose logs backend | grep <id>`. Work outside a request (startup, scheduled
  backups, queued agent runs) has `"request_id": null`.
- **More or less detail** — `TRALALA_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING` or `ERROR`; default
  `INFO`) is the lowest level written. `WARNING` drops the per-request lines.
- **`[redacted]` in a line** — the value of a field named `token`, `api_key`, `authorization` or
  `password`, at any depth, is never written.
- **`backup_created` has no `name`** — the snapshot's file name is `backup_name`: a log field cannot
  be called `name`.
- **A line that is not JSON** — it is uvicorn's, in uvicorn's format: the startup banner, the access
  log unless it is off (the container runs with `--no-access-log`), and the traceback of an
  exception the backend did not handle, after the backend's own `unhandled_exception` line.

## Tests

- **`pnpm test:e2e` cannot find a browser** — the runner reuses a local Playwright install and only
  downloads Chromium when none is present. Install it with `npx playwright install chromium`, or
  point at an existing CLI with `PLAYWRIGHT_CLI=<path to cli.js>`.
- **A journey fails only on a busy machine** — the suites are serial (`workers: 1`) and some
  journeys wait on timers. Re-run before investigating; a real failure reproduces.
- **The backend suite fails on a fresh clone** — it needs `backend/requirements-dev.txt`, not
  `requirements.txt`, and it writes into a temporary directory, so it needs nothing pre-configured.

If none of this fits, capture the failing request's `X-Request-ID` from the response and the backend
log lines whose `request_id` matches it: that pair is what makes a report actionable. Security issues
go to <tralala@bitnomad.se>, privately.
