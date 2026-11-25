import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./msw/server";

// The announcer's live regions (components/ui/announcer.tsx) repeat for screen readers what a view
// already shows, so a query for text finds the view's own copy; a test reads an announcement from
// its region with `announcer()` (./announcer.ts).
configure({ defaultIgnore: "script, style, [data-announcer]" });

// jsdom loads no stylesheet, so it takes a `sr-only` element for inline text. Tailwind positions
// it absolutely, which makes it a block of its own, and an accessible name or description sets a
// block apart from the text around it with a space, as a browser does. This rule says so; without
// it "Error: Enter a name." is computed as "Error:Enter a name.".
const srOnly = document.createElement("style");
srOnly.textContent = ".sr-only { position: absolute; }";
document.head.append(srOnly);

/**
 * vitest 4 hands a request body that is a jsdom `Blob` or `File` on to Node by reading its bytes
 * from a private field, and jsdom 31 no longer has that field, so an upload fails before it
 * reaches a handler. The bytes are read through the file's own method and sent as the body
 * instead; the request still goes through MSW. Remove this once vitest reads a jsdom Blob itself.
 */
function sendFileBodiesAsBytes(): void {
  const send = globalThis.fetch;
  globalThis.fetch = async (input, init) =>
    init?.body instanceof Blob
      ? send(input, { ...init, body: new Uint8Array(await init.body.arrayBuffer()) })
      : send(input, init);
}

// The documented Node integration of MSW: one server per test file, a request no handler answers
// fails the test's fetch, and the handlers a test added are dropped once it has unmounted.
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  sendFileBodiesAsBytes();
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
