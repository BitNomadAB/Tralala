# Contributing to Tralala

Thanks for your interest. Tralala is developed and maintained by **BitNomad AB**, which also offers
the software under commercial terms. That dual model is what this document protects, so please read
the licensing part before you open a pull request.

## Before you start

- Read `AGENTS.md`. The architecture rules there (one service layer, board isolation, registry
  authority, version-checked card mutations, Alembic-only schema changes) are review criteria, not
  suggestions.
- For anything larger than a bug fix, open an issue first so we can agree on scope.

## Licensing of contributions

Tralala is published under the PolyForm Noncommercial License 1.0.0 (see `LICENSE` and `NOTICE`) and
BitNomad AB sells commercial licences for it. That model only works if BitNomad AB holds sufficient
rights in **all** of the code — and here the public licence is unusually demanding:

> The PolyForm licence gives recipients no right to sublicense and implies no other licences. A pull
> request merged without a CLA would therefore be code that BitNomad AB may not be able to offer
> commercially at all.

Therefore:

1. **Sign the CLA.** Non-trivial contributions require the Contributor License Agreement in
   [`CLA.md`](CLA.md). It gives BitNomad AB a perpetual, irrevocable, sublicensable licence that
   includes the right to relicense your contribution under any terms, while **you keep your
   copyright**. Sign it once and it covers all your future contributions to the project.
2. **Sign off every commit.** Use `git commit -s` so each commit carries the Developer Certificate
   of Origin line:

   ```
   Signed-off-by: Your Name <your@email>
   ```

   This certifies you wrote the contribution or otherwise have the right to submit it. It is a
   statement of provenance; it is not a substitute for the CLA.
3. **Disclose anything you did not write.** If a contribution contains code from another project,
   say where it came from, under which licence, and whether you modified it. Code under a copyleft
   licence (GPL, AGPL, SSPL) or a proprietary licence cannot be accepted, and neither can code whose
   terms would prevent BitNomad AB from licensing the combined work.
4. **Disclose AI assistance.** Say in the pull request if a model generated part of the change. You
   remain responsible for reviewing it and for being entitled to submit it.

Trivial contributions — typo fixes, comment wording, documentation corrections — do not need a
signed CLA, but they still need the sign-off line.


We keep signed agreements on file and never publish them.

## What a good pull request looks like

- One concern per pull request, with a test that fails before the change and passes after it.
- Behavioural changes need an API-level test; user-journey changes extend `frontend/e2e/*.spec.ts`.
- Schema changes need an Alembic revision under `backend/migrations/{registry,board}` plus tests for
  fresh install, upgrade from the previous revision, data preservation and failure recovery.
- Update the relevant file in `docs/` when you change behaviour, and add a record under
  `docs/decisions/` for anything a future maintainer would otherwise have to re-derive. Anything a
  user or operator follows ? installation, troubleshooting, security defaults, agent usage ? lives in
  `public_docs/` and must stay true as well.

## Validation

Set up the environment once with [public_docs/Installation.md](public_docs/Installation.md), then run
the smallest relevant command before pushing. CI runs the full set.

```powershell
# backend, from backend/
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\python.exe -m ruff check app tests migrations

# frontend, from frontend/
pnpm test
pnpm typecheck
pnpm build          # includes the client build guard
```

Please do not open a pull request with a failing backend test, a ruff finding or a type error.

## Reporting security issues

Do **not** open a public issue for a security problem. Report it privately to
tralala@bitnomad.se with steps to reproduce, affected version or commit, and impact. We aim to
acknowledge within five business days.
