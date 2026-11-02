# 0017 — Interaction agent access belongs to the person who issued it

- **Status:** accepted
- **Date:** 2026-11-02
- **Context:** Accounts, sessions and keys ([0007](0007-accounts-sessions-and-keys.md)), the worker
  surface ([0015](0015-worker-surface-mcp-and-llms-txt.md)), worker-authored Info
  ([0016](0016-worker-authored-info-while-speculative.md))

## Problem

The worker surface made an external agent useful, but only an administrator could issue the key for
one, and the key belonged to nobody:

- `AuthService._issue` created a fresh `agent` actor per token and stored no link to the account that
  created it, so "how many keys does this person have" had no answer and no way to revoke by person;
- disabling a person revoked their sessions but left their tokens working, because a token is its own
  actor — the disable was only half a switch;
- `member` already held every working scope, so a member who *could* mint a token could have granted
  it board restructuring and agent management.

The people who do the work are the members: they sit with their agent, agree what to build, and need
a key for it. Making them ask an administrator for every key is friction with no security benefit,
because the administrator cannot tell which scopes the work needs anyway.

## Decision

1. **A token records its owner.** `api_credentials.owner_actor_id` (registry revision
   `0013_credential_owner`, nullable for tokens issued before it) names the account that created it.
   The token stays its own `agent` actor, so audit entries keep naming the machine ("michael desktop")
   rather than the person; ownership is a separate fact, not a replacement for identity.
2. **Any signed-in person may issue their own agent access.** An administrator keeps the ability to
   grant any scope a token can hold; a member may only grant `MEMBER_TOKEN_SCOPES` — read boards,
   work Loops and Tickets, comment, ask agents. Structure (`boards:write`, `boards:admin`), agents,
   accounts and tokens are outside it, and asking for one of those returns `422 forbidden_scope`.
3. **A personal key is bounded by design.** It must carry an expiry (default 30 days, ceiling
   `TRALALA_MEMBER_TOKEN_MAX_DAYS`), and the number of live keys per person is capped
   (`TRALALA_MEMBER_TOKEN_LIMIT`, default 10, `409 agent_access_limit`). A self-service key that never
   expires is a long-lived credential nobody remembers; the cap makes rotation the normal path.
4. **Ownership decides who may look and revoke.** `GET /credentials` returns your own keys; an
   administrator gets the installation-wide list and may narrow it with `?owner_id=`. Rotate and
   revoke are allowed for the owner or an administrator; anything else answers `404`, so a member
   cannot probe for other people's keys.
5. **Disabling an account revokes the access it issued.** `PATCH /users/{id}` with `disabled: true`
   revokes the person's sessions *and* every live token they own, disabling the agent actors behind
   them. Re-enabling the account does not resurrect a revoked key: revocation is a recorded decision,
   not a paused permission.
6. **The user list shows the number, not the secrets.** `GET /users` adds `agent_access_count` and
   `agent_access_last_used_at`, so an administrator can see who holds what and when it last connected
   without seeing any token.

## Consequences

- A member opens *Settings → Interaction agent access*, names a key after their machine, grants the
  working scopes, copies the ready-made MCP block and starts working — with no administrator in the
  loop, and with a key that cannot touch the installation's structure.
- The administrator keeps the only two levers that matter at that level: how many keys exist per
  person (visible) and whether the person may act at all (disable, which now really stops their
  agent).
- "Last used" becomes the practical answer to "is that really my desktop's agent?" — a bearer token
  proves possession, never a device. Binding to a device would need an identity in front of the API
  (for example Tailscale Serve headers); that is a separate decision.
- Scopes stay installation-wide. A member's agent reads every board, because there is no per-board
  membership yet; private boards are their own feature and are deliberately excluded here.

## Alternatives considered

- **Administrators issue keys on request.** Simplest to reason about, but it makes the admin a
  bottleneck for work they cannot scope better than the member, and it hides the count anyway.
- **Give every member the full token vocabulary.** Tempting because members already hold those
  scopes in their session, but a key outlives the session and travels to a machine; the narrower
  vocabulary is the point of a separate token.
- **Tokens owned by the agent actor only, revocation by name.** No migration, but then "disable this
  person" can never be complete, and the user list cannot say anything truthful about keys.
- **Expire-never tokens with the cap alone.** The cap bounds the number, not the exposure; an expiry
  turns an old key into a support question instead of a permanent liability.
