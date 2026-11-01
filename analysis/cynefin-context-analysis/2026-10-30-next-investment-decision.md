2026-10-30

# Cynefin Context Analysis: next investment decision

## At a glance

Context: Complicated (hardening) with a Complex element (adoption and scope) and one Chaotic risk path (data loss during restore) · confidence: medium · review point: after the first two bounded probes and the next release

- Users and agents are exposed to known, fixable integrity and security defects, so the team should ship the bounded hardening set before adding features (priority 1, observed, Context assessment).
- Whether agents actually use the API and WebMCP enough to justify more agent features is unknown from the repository, so it needs a small, instrumented trial rather than a large commitment (priority 2, unknown, Recommended response).
- If a restore or disk failure ever destroys a board, the immediate response must be to stop writes and recover from a verified backup, not to analyze causes first (priority 3, inferred, Recommended response).

## Decision or situation

**Decision:** choose the next 4-6 weeks of work for the AI-native Kanban product: (a) reliability and security hardening of the current single-host design, (b) multi-user and multi-host expansion, or (c) more agent-facing features (WebMCP depth, automation).

**Decision owner:** product owner of this repository. Not available for this analysis; the framing below is derived from the specification and the repository state.

**Affected parties:** the single self-hosting operator, human users of the board UI, external agents holding tokens, and the small development team maintaining the code.

**Desired outcome:** the smallest investment that protects existing users' data and trust while producing evidence for the larger direction.

**Time horizon:** one release cycle (weeks). Constraints: one backend process per data directory today; no external infrastructure (no Redis/Postgres) per the specification; the team is small; every option is reversible except data loss.

## Evidence and perspectives

**Observed (repository):**
- Security and integrity gaps are concrete and local: default session secret (`backend/app/core/config.py`), non-exclusive restore (`backend/app/services/backups.py`), unvalidated `due_at` (`backend/app/schemas/cards.py`), unidempotent bulk creation (`backend/app/api/v1/cards.py`), size-limit mismatch (`frontend/nginx.conf` vs `backend/app/core/config.py`).
- The architecture is deliberately single-host and single-process: in-memory rate limiter (`backend/app/core/ratelimit.py`), per-board SQLite, one backend container in `docker-compose.yml`.
- Test coverage exists for the core journeys: 38 backend tests, 15 frontend unit tests, 14 Playwright journeys including agent scopes and audit.
- There is no telemetry, no usage metrics and no incident log in the repository.

**Inferred:** the product is pre-adoption. No evidence shows which agent workflows are used, how many boards exist in practice, or whether multi-user is required.

**Unknown:** actual operator demand for multi-user access; whether external agents use REST directly or WebMCP; tolerance for a single-process deployment; regulatory or audit retention requirements for activity history.

**Perspectives that disagree:** the specification's "AI-native, agent-first" ambition pushes toward agent features (c), while the concrete defects and the single-operator MVP push toward hardening (a). Both are defensible; the causal structure of each differs, which is why they are analyzed separately below.

## Context assessment

The decision decomposes into three sub-decisions with different causal characteristics:

| Sub-decision | Best-supported context | Reasoning | Confidence | Plausible alternative |
| --- | --- | --- | --- | --- |
| Fix the identified security/integrity defects | **Complicated** | Cause and effect are knowable and already documented in `analysis/atam-architecture-analysis/` and `analysis/fmea/`; fixes are standard practice with clear verification (tests). Expert analysis is sufficient; no experimentation needed. | High | Clear for a few items (e.g. raising a body limit), but grouping them as "apply known good practice" is more accurate. |
| Decide how much to invest in agent features / WebMCP | **Complex** | Value depends on emergent agent behaviour and user workflows that cannot be predicted from the code; multiple plausible outcomes; evidence only appears after real usage. | Medium | Complicated if the team already has stakeholder-confirmed demand; that evidence is absent. |
| Multi-user / multi-host expansion | **Complicated for design, Complex for demand** | The technical path (shared coordination store, session model, data isolation) is analyzable; demand and operational burden are not. Choosing it now would be a large, partly irreversible commitment. | Medium | Clear only if a known customer requires it. |
| Recovering from an actual data-loss incident | **Chaotic** | While a board is being corrupted or lost, delay makes it worse; stabilization precedes analysis. This is a possible state, not the current state. | High (for the state) | Not applicable today: no incident is active. |

**Why not Complex for the whole decision:** the defect list has stable, knowable causes and deterministic verification. Treating it as Complex would invite experiments where straightforward engineering is cheaper.

**Why not Disorder:** the evidence is sufficient to separate the parts; disagreement is about priorities, not about what the situation is.

## Recommended response

**1. Act in the Complicated domain for hardening (now).**
- Apply the bounded fix set from the ATAM and FMEA: per-install secret handling, exclusive restore, transfer finalization fallback, ISO 8601 due dates, bulk idempotency, board-creation reservation, truthful capability reporting, aligned body limits, deployment constraint documented.
- Rationale: each change has a known cause, a small blast radius, an automated test, and no new infrastructure. This is good practice applied to evidence, not experimentation.
- Constraints: no schema-breaking changes to released migrations (add new migrations only); keep the single-process constraint explicit.
- Learning: the test suite and a new failure-injection test for interrupted creation and restore concurrency.

**2. Probe in the Complex domain for agent adoption (next two weeks, bounded).**
- Probe hypothesis: "Operators and their agents get enough value from REST + WebMCP tools to justify deeper agent features."
- Bounded probe: instrument the existing API (request counts per endpoint and actor type, already logged in structured JSON) and ask two or three real operators to run one scripted agent workflow each. Keep the probe to read-only analysis of logs the system already emits; no new product surface.
- Observations that decide: number of distinct agent actors per install, share of mutations from agents, WebMCP availability in the operators' browsers, and qualitative friction reports.
- Decision criteria: if agents produce a meaningful share of mutations and operators ask for more tooling, invest in (c); if not, keep agent features frozen and continue hardening/multi-user discovery.
- Downside limits: no schema changes, no new dependencies, no commitments to external users.

**3. Treat data loss as Chaotic when it happens.**
- Immediate stabilization: stop writes to the affected board (archive it or take the backend out of service), preserve the current files (copy `board.sqlite`, `-wal`, `-shm`), then restore the newest verified backup and run `GET /boards/{id}/validate` before reopening.
- Reassess only after the board is stable and verified; then run a post-incident analysis that feeds FMEA and ATAM updates.

**4. Defer multi-user/multi-host (Complicated design, Complex demand).**
- Do not start it without stakeholder-confirmed demand, because it invalidates the single-process assumptions (rate limiter, per-board locks, SQLite write contention) and is expensive to reverse.

## Reassessment

- **Review point:** after the hardening release and after the first two probe reports, target 2026-11-27.
- **Indicators that confirm this assessment:** defects fixed with tests passing; operator feedback showing low agent usage; no demand for multi-user access.
- **Indicators that would change it:**
  - A real data-loss or corruption incident → move immediately to the Chaotic playbook, then re-run FMEA.
  - Two or more operators requesting shared access → promote multi-user from deferred to Complicated design work with a spike.
  - Agent mutations dominating usage or explicit requests for deeper automation → shift investment to agent features.
  - A security incident involving session forgery → treat the related defect as an incident, not a backlog item, and re-check the security controls as a theme.
- **Context shifts to watch:** deployments moving behind TLS/reverse proxies (raises security expectations), data volumes approaching the 10,000-card target (performance sensitivity), and any move to multiple backend processes.

## Open questions

1. Who is the decision owner, and does the organization require multi-user access within the next two quarters? (Unknown; changes the priority of option b.)
2. How many real installs/operators exist today, and which agent workflows do they actually run? (Unknown; decides the probe sample.)
3. Is there an audit-retention obligation for activity history? (Unknown; affects the retention design and the data-loss playbook.)
4. What is the acceptable recovery point objective for a board? (Unknown; determines backup cadence, currently manual/on demand.)
5. Is a single backend process per install acceptable operationally? (Inferred yes from the Docker Compose design, unconfirmed.)
