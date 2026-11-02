# Tralala (Work in progress, if you care about your data dont use this just yet.)

Tralala is a self-hosted, AI-native planning and delivery application. Humans work with Loops inside
Boards; agents get the same capabilities through a documented REST API and a curated MCP surface.
Every board is its own SQLite database. No cloud services, no external AI provider, no Redis or
Postgres.

```
App  ->  Board  ->  Loop  ->  Loop-owned Kanban (Tickets) + Info / Analysis / RoadMap + Phases
```

## Start here

| I want to… | Read |
| --- | --- |
| install and run it | [public_docs/Installation.md](public_docs/Installation.md) |
| start, stop, test, update it day to day | [public_docs/practical_commands.md](public_docs/practical_commands.md) |
| do the first hour: my account, a person, an agent, a repository, one Loop | [public_docs/Onboarding.md](public_docs/Onboarding.md) |
| fix something that broke | [public_docs/Troubleshooting.md](public_docs/Troubleshooting.md) |
| know what is protected and what is my decision | [public_docs/Security_defaults.md](public_docs/Security_defaults.md) |
| connect a coding agent to it | [public_docs/Agent_usage.md](public_docs/Agent_usage.md) |
| understand the design | [public_docs/Architecture.md](public_docs/Architecture.md), [docs/decisions/](docs/decisions) |
| call the API | [docs/api.md](docs/api.md) |

Prerequisites and the installation of Python, Node, pnpm and Docker live in the installation guide,
with links to each tool's own documentation — those change more often than this repository does.

## Quick start

With Docker:

```bash
git clone https://github.com/BitNomadAB/Tralala.git
cd Tralala
cp .env.example .env                 # set TRALALA_SECRET_KEY and TRALALA_BOOTSTRAP_PASSWORD
docker compose up -d --build         # UI on http://localhost:8080
```

From source:

```bash
python -m venv .venv && .venv/bin/activate
pip install -r backend/requirements-dev.txt
(cd frontend && pnpm install)

# terminal 1
cd backend && ../.venv/bin/python -m uvicorn app.main:create_app --factory --port 8000

# terminal 2
cd frontend && pnpm dev              # UI on http://localhost:5173
```

Windows uses `.venv\Scripts` paths; the installation guide lists the differences for each shell.

Either way you sign in as `admin` with the generated password in `<data>/.bootstrap-password`: there
is no shared password. See [the first sign-in](public_docs/Installation.md#first-sign-in).

## Features

- **Boards** with an isolated SQLite database each: create, rename, duplicate, archive, export and
  import, and delete behind a typed-name confirmation. A board carries its uploaded files with it.
- **Loops**: each Board contains Loops, and each Loop owns its columns, Tickets and planning
  documents. A Loop moves through Draft, Analysis review, Planning, RoadMap review, Ready, In
  progress, Replanning, Awaiting QA and Completed, and Readiness explains every blocker.
- **Revisioned planning documents**: human-authored Info, an AI technical analysis with a
  plain-language human view, and a structured RoadMap whose numbered Phases and planned Tickets are
  published atomically after a human approval. Generated content is validated before it can be
  approved, and approvals bind to exact revisions.
- **Version-bound human gates**: agents may generate, plan and execute eligible Tickets, but only a
  signed-in person approves plans, confirms human-only actions, accepts QA and finalizes a Loop.
- **QA handover** with one QA Task carrying an agent view and a human view of the same scenarios,
  scenario-level results, and a human acceptance decision.
- **Discussions** per Ticket with the role agents: sequential rounds, a duplicate guard, consensus
  that needs an actual review round, pause/resume/stop, and a cap of four rounds plus a default
  token and time budget per run.
- **Tickets** with labels, checklists, comments, mentions, due dates, a stable ticket key, an
  attachment allowlist and complete activity history.
- **Agents** as registry resources: a shared, editable role prompt plus identity, connection and a
  sealed credential; OpenAI-compatible and A2A transports.
- **People**: `admin`/`member` roles, invitation links instead of email, sessions that revoke on a
  password change, and self-service "interaction agent access" keys.
- **One worker surface**: thirteen curated tools behind `/mcp`, generated from a single catalogue,
  with a public `/llms.txt` bootstrap so a URL and a token are enough to start working.

## Layout

```
backend/app/{api,core,schemas,services,storage}   FastAPI service layer and SQLite storage
frontend/src/{app,features,lib,webmcp,themes}     React UI, typed API client, WebMCP adapter
frontend/Caddyfile                                web tier: SPA, API proxy, TLS
public_docs/                                      installation, onboarding, commands, architecture, security, agents
docs/                                             architecture, API, database, decisions
.ralph/                                           progress.txt (log) and the Loop specification
```

Read [AGENTS.md](AGENTS.md) before changing code: it holds the architecture rules and the
verification contract. Decisions are recorded in [docs/decisions/](docs/decisions).

## Known limitations

- Accounts are administrator-provisioned: there is no self-registration, and a person joins through an
  invitation link.
- One backend process per data directory; the rate limiter, board locks and session secret are
  process-local, so horizontal scaling needs a shared coordination store.
- No per-board access control yet: a member sees every board in the installation. Private boards are
  a separate feature.
- Attachments have a complete API but no upload UI yet.
- Search and board views page at 200 items; deeper result sets use `offset`/`limit` or filters.
- No real-time collaboration, notifications or cloud sync (explicit MVP exclusions).
- WebMCP execution is not automated because the browser API is experimental and absent from the test
  Chromium; the adapter contract is unit-tested and the UI degrades gracefully.

## Licence and contributing

Tralala is **source-available, not open source**. It is published under the
[PolyForm Noncommercial License 1.0.0](LICENSE): you may use, change and share it for any
noncommercial purpose — personal projects, study, experiment and research, and use by charities,
educational institutions, public research bodies, public safety and health organizations,
environmental organizations and government institutions.

**Any commercial use requires a commercial licence from BitNomad AB** — including internal use in a
business and evaluating the software for a commercial purpose. Contact
[tralala@bitnomad.se](mailto:tralala@bitnomad.se) for terms.

Copyright 2026 BitNomad AB. Attribution and the required notice are in [NOTICE](NOTICE).

Contributions are welcome. Because the project is licensed to different recipients under different
terms, non-trivial contributions require a signed [Contributor License Agreement](CLA.md) — you keep
your copyright and grant BitNomad AB the right to relicense your work — plus a DCO sign-off on each
commit (`git commit -s`). Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and report security issues
privately to [tralala@bitnomad.se](mailto:tralala@bitnomad.se) rather than in a public issue.
