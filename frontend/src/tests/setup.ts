import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./msw/server";

// The announcer's live regions (components/ui/announcer.tsx) repeat for screen readers what a view
// already shows, so a query for text finds the view's own copy; a test reads an announcement from
// its region with `announcer()` (./announcer.ts).
configure({ defaultIgnore: "script, style, [data-announcer]" });

// The documented Node integration of MSW: one server per test file, a request no handler answers
// fails the test's fetch, and the handlers a test added are dropped once it has unmounted.
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
