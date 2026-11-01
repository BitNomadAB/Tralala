# 0005 — Reuse the machine's Playwright install for E2E

- Status: accepted
- Date: 2026-10-30

## Context

The host already has Playwright 1.62.1 (installed through `npx`) with Chromium builds under
`%LOCALAPPDATA%\ms-playwright`. Vendoring another copy would duplicate hundreds of megabytes and
risk a second, mismatched browser download. Node's ESM resolver also ignores `NODE_PATH`, and the
frontend package is `"type": "module"`, so tests cannot import `playwright/test` from an
arbitrary directory.

## Decision

`scripts/run-playwright.mjs` resolves Playwright in this order:

1. `PLAYWRIGHT_CLI` (explicit override)
2. `frontend/node_modules` (when the project itself installs it)
3. global npm root
4. the npm/npx cache (`_npx`), preferring stable releases over nightlies and the newest version

It then:

- creates a directory junction `frontend/node_modules/playwright` to the discovered package so ESM
  imports resolve without installing anything,
- exports `NODE_PATH` for CJS consumers,
- installs Chromium only when no browser build exists.

`pnpm test:e2e` wraps the Playwright CLI through this launcher. The suite itself runs against an
isolated stack: backend on `:8077` with data in `frontend/e2e/.data` and Vite on `:5273`, so it
never collides with a developer's dev servers.

## Consequences

- No Playwright dependency is added to `package.json`; `pnpm install` stays lean.
- The suite is reproducible on any machine that has any Playwright install; on a clean machine the
  launcher reports the exact command to install one.
- Tests must avoid imports that only exist in `@playwright/test` beyond the shared `playwright/test`
  entry point (both packages expose it).
- The junction lives inside the gitignored `node_modules`; a later `pnpm install` may remove it and
  the launcher recreates it on the next run.
