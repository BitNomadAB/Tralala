# Release notes

What changed for someone running Tralala, newest first. Architecture and API detail lives in
[Architecture.md](Architecture.md) and [API.md](API.md); this page is the short version a person needs
before upgrading.

## Unreleased

First release on the Loop schema. Read these three lines before importing anything from an older
installation.

- **Data from before the Loop schema is not migrated.** A board database that still holds the old
  lists and cards refuses to upgrade and names the development reset command instead. There is no
  preservation path and none is planned. Export what you need from the old installation before you
  upgrade.
- **Board archives are format 2 only.** An archive exported by a pre-Loop build is rejected with
  `422 validation_failed` ("Unsupported board archive format") rather than half-imported.
- **One Python version.** 3.13 is the version of record — container image, CI's primary job and the
  documented setup. 3.14 is tested too; newer interpreters are refused by `install` rather than
  silently accepted.

Worth knowing when you look at the dashboard:

- **Board counters are cached**, because they live in each board's own database. A write through the
  app refreshes them immediately; a board file changed behind the app's back can show a number up to
  `TRALALA_BOARD_COUNTS_CACHE_SECONDS` (default 60) old. `GET /boards?with_counts=false` skips the
  counters entirely.
- **The web tier is Caddy**, not nginx: TLS, HTTP/2 and the body limit come from
  `frontend/Caddyfile`, and `TRALALA_SITE_ADDRESS` decides whether Caddy serves plain HTTP on `:80`
  or gets a certificate.
- **A held file no longer half-deletes a board.** Host filesystem behaviour follows
  `TRALALA_PLATFORM_PROFILE`, and a board delete that cannot remove its files answers
  `409 board_files_busy` with the leftover directory.
- **The connection test also calls the model.** It used to check only that the endpoint answered;
  a wrong model name passed the test and failed the first generation. It now sends one real
  completion, reports the provider's sentence when that is refused, and offers the model names
  it found as suggestions.
- **A failed generation now says why.** A provider rejection used to read only "HTTP 400", and the
  message lived in a toast that disappeared; the Loop's document dialog shows the last run for the
  purpose, with the provider's own sentence, until it is retried.
- **A discussion is capped at four rounds** per run, with default token and time budgets
  (`TRALALA_DISCUSSION_TOKEN_BUDGET`, `TRALALA_DISCUSSION_TIME_BUDGET_SECONDS`). There is no
  per-token rate limit. See
  [Security_defaults.md](Security_defaults.md#accepted-risks-on-purpose).

Known limitations are listed in [Security_defaults.md](Security_defaults.md) and in the operational
notes of [Architecture.md](Architecture.md#operational-notes).
