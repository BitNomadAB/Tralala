# 0021 — Caddy instead of nginx for the web tier

- **Status:** accepted
- **Date:** 2026-11-02
- **Context:** `frontend/Caddyfile`, `frontend/Dockerfile`, `docker-compose.yml`,
  `.github/workflows/ci.yml`, `frontend/scripts/check-client-build.mjs`

## Problem

The web tier was an nginx container with a hand-written config. It served the SPA, proxied the API
and the worker surface, and set a security header policy — all correctly, but every one of those was
a separate hand-maintained list:

- TLS was not its business, so an operator adding HTTPS needed a second container or a host proxy,
  plus a decision about where the certificate lives and how it is renewed.
- The body limit existed twice and disagreed with itself: `client_max_body_size 8m` against a
  `TRALALA_ATTACHMENT_MAX_BYTES` default of 10 MiB. The promise in the documentation was larger than
  what the proxy accepted, and the proxy's refusal was an HTML page rather than the JSON envelope.
- `X-Forwarded-For` had to be wired by hand, and `TRALALA_TRUST_PROXY_HEADERS` was not passed through
  by compose, so the sign-in throttle keyed everybody on the proxy's address.
- The container build was accidentally broken and nobody noticed: `pnpm build` runs the client build
  guard as `node ../scripts/check-client-build.mjs`, and the image only copies `frontend/`, so
  `docker build` had been failing since the guard was added.
- The backend image was broken too, and for longer: `services/runtime.py` imports `httpx` for every
  provider and A2A call, but `httpx` was listed only in `requirements-dev.txt`, so the container died
  at import. `anyio`, imported directly by the event-stream endpoint, was likewise only transitive.
  Both are now runtime dependencies. A stack that builds but cannot start is worse than no stack, and
  this is exactly what the first real `docker compose up` exposed.

## Decision

**Caddy 2 serves the web tier**, configured by one `frontend/Caddyfile`.

1. **One site address decides everything about transport.** `TRALALA_SITE_ADDRESS` is `:80` by
   default (plain HTTP behind Tailscale Serve, a load balancer or any terminator). Given a hostname,
   Caddy obtains and renews the certificate itself — a public CA for a public name, its own local CA
   otherwise — and redirects HTTP to HTTPS. Certificates and ACME state live in
   `tralala-caddy-data`, so a redeploy does not re-issue them.
2. **One header policy for the whole origin**, including the CSP, and `-Server` so the tier does not
   advertise itself. A proxied response keeps the backend's own headers.
3. **One body ceiling above the backend's.** `request_body max_size 9MB` sits above
   `TRALALA_MAX_REQUEST_BYTES` (8 MiB) so the backend's JSON `413` is what a client normally sees;
   the proxy cuts off only a chunked body that never declared its size. `TRALALA_ATTACHMENT_MAX_BYTES`
   now defaults to the same 8 MiB, because a file cannot be larger than the body that carries it.
4. **The worker surface is matched before the SPA fallback** (`/mcp`, `/llms.txt`), so an agent
   fetching the bootstrap gets text rather than `index.html` with a 200.
5. **The client build guard moved into the package it protects** (`frontend/scripts/`), so the image
   build can run it and it can no longer disagree with the build context.
6. **Compression and HTTP/2+3 are defaults** rather than a directive nobody added: `encode zstd gzip`
   covers JSON and the shell, and assets keep `Cache-Control: public, immutable`.
7. **A CI job builds both images** and asserts what the tier is responsible for: `/` and a deep
   client route answer 200, the CSP is present and the `Server` header is not.

## Consequences

- An operator gets TLS by setting one variable; there is no certificate container and no renewal
  cron.
- A size limit that disagrees with the documentation is now visible in one place, and the defaults
  agree.
- The sign-in throttle sees the real client address (`TRALALA_TRUST_PROXY_HEADERS` defaults to
  `true` in compose, which is safe because the backend port is not published).
- A broken image build fails CI instead of failing a deploy.
- Caddy's configuration language is smaller than nginx's for this shape of site, but it is a new
  thing to learn; the whole tier is now one 60-line file with comments.
- The admin API is enabled on the container's loopback, because it is what the healthcheck uses. It
  is not published and is not reachable from another container.
- One behaviour differs from nginx: a chunked upload past the proxy ceiling has its connection
  closed instead of receiving a page. The backend's own limit is what clients normally hit, and it
  answers in the JSON envelope.

## Alternatives considered

- **Keep nginx and add a certificate container (certbot or acme-sh).** More moving parts, another
  volume, another renewal timer, and two configurations to keep aligned.
- **Keep nginx and document "put TLS in front".** Honest, but it makes the operator responsible for
  the part that is easiest to get wrong, and it leaves the body-limit mismatch in place.
- **Terminate TLS only at Tailscale and forbid anything else.** That is a valid deployment, and it is
  still the default here (`:80`); it just should not be the only one the image can do.
- **Move the guard under `frontend/` vs. widening the build context to the repository root.** The
  wider context would have to ship `.devdata` (real development data) past a new `.dockerignore` on
  every build; moving a build guard next to the build it guards is the smaller change.

## Verification

`docker build ./frontend` succeeds (it did not before), and a container run against the real backend
answered, in this session: `/` 200 `text/html` with the CSP and no `Server`; `/llms.txt` 200
`text/plain` starting `# Tralala`; `/api/v1/health` 200 JSON; `POST /mcp` 401 in the JSON envelope;
a deep route 200 HTML; an asset 200 with `Cache-Control: public, immutable` and gzip; a key created
through the proxy, used on `/mcp` (`tools/list` returned the scoped tools), then revoked; a board
created, archived and deleted through the proxy; a 40 MiB declared body refused in 0.28 s with
`413 payload_too_large`; a chunked 40 MiB body cut off at the proxy with no crash. `caddy validate`
passes for both `:80` and a hostname address.

Then the whole stack: `docker compose up -d --build` brought up a healthy backend and a healthy web
container on a scratch project, and through the proxy a real sign-in, a key issued in the UI's own
flow, `tools/list` (six scoped tools, discussions included), a `read_board` call returning the board
it had just created, and the cleanup. The scratch stack was removed with its volumes.
