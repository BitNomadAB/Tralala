# 0004 — WebMCP as an optional adapter over the same REST client

- Status: accepted
- Date: 2026-10-30

## Context

WebMCP is experimental and only available in some Chromium builds. The application must keep
working without it, tools must never duplicate business rules, and an actor must not be offered
tools it cannot execute.

## Decision

- `getModelContext()` feature-detects `document.modelContext` / `navigator.modelContext`; absence is
  a normal state, not an error.
- Each UI context (dashboard, board, open card) builds its tool list with pure builders in
  `src/webmcp/tools.ts`. Every `execute` calls `src/lib/api.ts`, i.e. the same REST endpoints as the
  UI; no direct database or service access.
- `createRegistry` registers tools with an `AbortController` signal and unregisters on context exit;
  identical names are not registered twice.
- Tools declare `requiredScope`; registration filters them against the authenticated actor before
  touching the browser API.
- Tests cover capability detection, registration/de-registration and tool definitions.

## Consequences

- WebMCP can be replaced or removed without touching application logic.
- Agent behaviour through WebMCP and through REST stays identical because both hit the same
  authorization and validation path.
- Browser-level tool execution is not covered by automated tests in this environment (WebMCP is
  unavailable in the test browser); the adapter contract is unit-tested instead.
