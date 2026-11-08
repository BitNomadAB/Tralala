import { render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Actor, ApiMeta } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER, memberSession } from "./msw/session";

const ADMIN: Actor = { ...MEMBER, id: "admin-1", name: "Ada Admin", role: "admin" };

const META: ApiMeta = {
  api_version: "v1",
  scopes: [],
  token_scopes: [],
  member_token_scopes: [],
  member_token_limits: { live: 5, default_days: 30, max_days: 365 },
  can_issue_tokens: true,
  features: {},
};

const BANNER = /generated administrator password is still stored/;
// Each test imports the whole App afresh (below), and the first import of a file pays for the
// module graph; the page's own wait is 10 s, so the test may take longer than vitest's 5 s default.
const IMPORTS_THE_APP = { timeout: 15_000 };

// The first test imports the whole app, which the heading's 10 s wait allows for; the test's own
// limit has to allow for it too, or a loaded machine fails it before the wait is over.
describe("the bootstrap password banner on Settings", { timeout: 15_000 }, () => {
  let metaAnswered: boolean;

  beforeEach(() => {
    // App.tsx owns a module-level QueryClient: a fresh module graph gives each test a fresh cache.
    vi.resetModules();
    metaAnswered = false;
    window.history.replaceState(null, "", "/settings");
  });

  /** Settings for `actor`, with `/meta` answering `meta`; resolves once the page is up. */
  async function renderSettings(actor: Actor, meta: ApiMeta) {
    server.use(...memberSession().handlers);
    server.use(
      http.get(apiPath("/auth/me"), () => ok(actor)),
      http.get(apiPath("/meta"), () => {
        metaAnswered = true;
        return ok(meta);
      }),
      // What an administrator's Settings page reads besides a member's.
      http.get(apiPath("/users"), () => ok([])),
      http.get(apiPath("/credentials"), () => ok([])),
    );
    const { App } = await import("@/app/App");
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Settings" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
  }

  /** The flag has arrived and the page had time to show the banner, and it did not. */
  async function expectNoBanner() {
    await waitFor(() => expect(metaAnswered).toBe(true));
    await expect(screen.findByText(BANNER, {}, { timeout: 300 })).rejects.toThrow();
  }

  it(
    "tells an administrator while the generated password file is there",
    IMPORTS_THE_APP,
    async () => {
      await renderSettings(ADMIN, { ...META, bootstrap_password_file_present: true });

      const banner = await screen.findByText(BANNER);
      expect(banner).toHaveTextContent("<data>/.bootstrap-password");
      expect(banner).toHaveTextContent(/change that password under Your password/);
    },
  );

  it("says nothing to an administrator once the file is gone", IMPORTS_THE_APP, async () => {
    await renderSettings(ADMIN, { ...META, bootstrap_password_file_present: false });

    await expectNoBanner();
  });

  it("never shows a member the banner", IMPORTS_THE_APP, async () => {
    // The server does not send a member the flag; the page does not show it to one either.
    await renderSettings(MEMBER, { ...META, bootstrap_password_file_present: true });

    await expectNoBanner();
  });
});
