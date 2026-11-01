2026-10-31

# Accounts, sessions and key handling

## Context

Tralala is meant to be installed once, privately, with its own users and its own model endpoints.
That asks for a small, understandable account model rather than a permission matrix: somebody
installs it, becomes the administrator, creates accounts for the people who should use it, and
everyone signed in can do the work.

At the same time the earlier increments had gaps that matter for a private install: sessions could
not be revoked, there was no way to change or reset a password, API tokens could not be rotated,
there was no limit on repeated sign-in attempts, and a changed session secret made every stored
provider key unreadable.

## Decision

1. **Two roles, one working set.** `admin` holds every scope. `member` holds every scope except
   `users:admin` and `credentials:admin`. Everyone signed in can work with boards, agents and
   discussions; only administrators create, rename, disable, re-role or reset other accounts, and
   only administrators issue, rotate and revoke the installation-wide API keys.
2. **Sessions live in the registry.** A login writes a `sessions` row keyed by the hash of a random
   session id; the cookie carries a signed `<id>.<expiry>.<hmac>` value. Logout, a password change,
   a role change and disabling an account revoke rows, so a stolen cookie stops working. Expired
   sessions are purged at startup.
3. **Passwords** are scrypt hashes with a configurable minimum length (default 8, never below 8)
   and are rejected when they are published words or the username. Changing your own password requires the current
   one and signs out every device; an administrator can reset another account's password.
4. **The last administrator is protected.** Demoting or disabling the only enabled administrator
   returns `409` so an install cannot lock itself out.
5. **Sign-in is throttled per username and per client address** with exponential backoff, on top of
   the general per-actor rate limiter. `X-Forwarded-For` is only trusted when
   `TRALALA_TRUST_PROXY_HEADERS` is enabled.
6. **API tokens expire by default** (90 days, `TRALALA_CREDENTIAL_DEFAULT_TTL_DAYS`, `0` for none)
   and can be rotated in one step: a new token is issued and the old one revoked. Tokens may hold
   every scope except `credentials:admin` and `users:admin`, and only administrators manage them.
7. **A weak or missing session secret is replaced** by a per-install secret in
   `<data>/.session-secret`. Provider keys stay sealed with a key derived from the session secret;
   setting `TRALALA_PREVIOUS_SECRET_KEY` lets the server open keys sealed with the old secret and
   re-seal them with the new one at startup, after which the old value can be deleted.
8. **The first administrator's password is never a published word.** A generated password is
   written to `<data>/.bootstrap-password` (owner-only) instead of the log; the file is deleted after
   the first sign-in.

## Consequences

- Existing installations upgrade in place: `0005_accounts_and_sessions` adds the role column (default
  `admin`, so the existing account keeps its access) and the `sessions` table.
- There is no invitation or self-service registration flow. The administrator creates accounts with
  an initial password; the account holder can change it afterwards. This keeps the install small and
  avoids e-mail infrastructure.
- Session rows are server state, so a deployment running two backend processes against one data
  directory still works, but the login throttle is per process. That matches the single-process
  deployment model in [0001](0001-per-board-sqlite.md).
- The frozen HKDF material in `core/secrets.py` stays as shipped; it is key-derivation input, not a
  brand name. See [0006](0006-product-rename-tralala.md).
