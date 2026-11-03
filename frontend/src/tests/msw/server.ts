import { setupServer } from "msw/node";

/**
 * The network every test file runs against: `src/tests/setup.ts` starts it with unhandled requests
 * as errors and drops each test's handlers afterwards. It starts with no handlers on purpose, so a
 * request a test did not plan for fails instead of meeting a generic answer; a test installs what it
 * needs with `server.use(...)`.
 */
export const server = setupServer();
