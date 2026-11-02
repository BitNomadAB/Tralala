# 0014 — Enrolment links instead of e-mail verification

- **Status:** accepted
- **Date:** 2026-11-01
- **Context:** Accounts and sessions ([0007](0007-accounts-sessions-and-keys.md)), no new
  infrastructure without a decision ([AGENTS.md](../../AGENTS.md) rule 10)

## Problem

Tralala ships no self-service registration: an administrator creates an account with an initial
password (`POST /users`) and hands it over. That keeps the installation free of e-mail infrastructure,
which `0007` states on purpose, but it has a real cost: **the administrator knows every user's
password**, and a shared starting password is what people actually use.

The Loop "Email verification" asked for the literal mechanism (confirm the address by e-mail). That
solves a problem this product does not have — there is no public sign-up to protect — while adding an
SMTP relay, sender domain, SPF/DKIM/DMARC, a retry queue, bounce handling and personal data to look
after.

## Decision

**One-time enrolment links, with no e-mail anywhere in Tralala.**

1. **The administrator issues a link.** `POST /api/v1/users/{user_id}/invite` requires `users:admin`
   and returns the token **once**; the database stores only its hash, exactly like API credentials.
   The reply carries `path: "/enrol?token=…"` so a client can build the full URL.
2. **One live link per account.** Creating a new link deletes any unused one, so an old message cannot
   be replayed. The default lifetime is `TRALALA_INVITE_TTL_HOURS` (72 h).
3. **The person sets their own password.** `POST /api/v1/auth/enrol` is public by design, throttled
   with the same limiter as login, and answers with generic codes (`invite_invalid`, `invite_used`,
   `invite_expired`) so a caller cannot learn whether a token ever existed. Success sets the password,
   marks the link used, revokes other sessions and starts a session.
4. **A rejected password does not burn the link.** Validation happens before the invite is marked
   used, so a person who misses the length rule can try again.
5. **Delivery is the operator's business.** Whoever invited the person sends the link through a channel
   they already trust. Tralala never sends anything, so it needs no mail server and holds no
   addresses.
6. **The initial-password path stays.** Administrators may still create an account with a password,
   for the first administrator and for automation. The invite is the recommended path.

## Consequences

- The administrator no longer needs to invent or remember a user's password; the account is claimed by
  whoever holds the link, and the link is single use with an expiry.
- No new infrastructure, no new outbound dependency, nothing to configure per installation. The whole
  feature is one table, two endpoints and one page.
- The link is a bearer secret for a short window. Anyone who reads the message can claim the account,
  which is why it is single use, short-lived, hashed at rest and replaced on re-issue. That risk is
  visible to the operator ("Send it once through a channel you already trust").
- An installation that later wants federation can add OIDC next to this without removing it: the
  invite stays the bootstrap path for accounts outside the directory.
- If the product ever offers **public** self-service sign-up, e-mail verification becomes a real
  requirement and needs its own decision. It should then use a relay or provider, never a mail server
  inside the backend process.

## Alternatives considered

- **SMTP verification (what the Loop literally said).** Rejected for now: an external dependency, a
  sender domain with SPF/DKIM/DMARC, an outbox with retry and bounce handling, and address data to
  protect — all for a signup flow that does not exist.
- **OIDC / SSO.** The strongest option when an organisation already runs Authentik, Keycloak or a
  hosted identity provider, and the natural next step for MFA and passkeys. Not first: it adds an
  external dependency and a configuration surface every self-hoster would have to fill in, while the
  open problem is simply "the admin should not know the password".
- **Passkeys (WebAuthn) without an invite.** Cannot bootstrap: the first credential has to be enrolled
  on a device by someone, which is what the invite solves. A natural follow-up on top of this decision.
- **Keep initial passwords only.** Cheapest, but it is the status quo that produced the problem.
- **A shared "first login must change password" flag.** Still requires the administrator to invent a
  password and still transmits it.
