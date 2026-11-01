# 0006 — Rename the product to Tralala

- Status: accepted
- Date: 2026-10-30

## Context

The product shipped as "AI Kanban" / "AI-Native Kanban". The owner asked for a rename to
**Tralala** and chose a full rename without backwards compatibility, while keeping "kanban" as a
generic description of the board type.

## Decision

1. Brand text becomes **Tralala** in the UI (logo, page title, login), README, docs and the
   OpenAPI title. Descriptive sentences may still say "kanban board".
2. Technical identifiers are renamed with no compatibility layer:
   - environment prefix `KANBAN_*` → `TRALALA_*` (config, `.env.example`, Compose, Playwright,
     documentation, Ralph harness);
   - cookies `kanban_session`/`kanban_csrf` → `tralala_session`/`tralala_csrf`;
   - browser storage `kanban-theme` → `tralala-theme`; the unauthorized event is
     `tralala:unauthorized`;
   - logger names `kanban*` → `tralala*`;
   - API token prefix `knb_` → `trl_` (only newly issued tokens; stored hashes are unaffected);
   - package names, Docker user, volume `tralala-data`.
3. Two things intentionally stay as shipped:
   - the credential key-derivation material in `core/secrets.py` (`b"kanban-agent-credentials"`)
     because changing it would make every sealed provider key undecryptable;
   - historical records: `analysis/` reports, released migrations and `.ralph/progress.txt` keep
     the old name.
4. The repository/remote name (`MyBoards`) was out of scope at the time; renaming it was a hosting
   decision. It has since been renamed to `BitNomadAB/Tralala`.

## Consequences

- Existing deployments must rename their `.env` keys and will be signed out by the cookie rename;
  an existing Docker volume named `kanban-data` is not reused under the new name.
- Newly issued API tokens start with `trl_`; previously issued tokens keep working because only
  their SHA-256 is stored.
- The seed role prompts use the new product name for fresh installs; existing installations keep
  their seeded prompt until **Restore factory prompt** is used.
