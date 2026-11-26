import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { addressOf } from "@/features/auth/returnPath";
import { dashboardHandlers } from "./msw/boards";
import { apiPath, failure } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER_PASSWORD, memberSession } from "./msw/session";

/**
 * Sign out in the header when the server does not answer the logout with a success: the session
 * had already ended (a 401), the server failed (a 500), or the network is down. The person asked to
 * leave and is signed out in the tab either way, so nothing is left over: no error on screen, and
 * no rejected promise that nobody handles, which a browser writes to its console as an error.
 */
describe("Sign out in the header when the server does not end the session", () => {
  let session: ReturnType<typeof memberSession>["state"];
  /** Every rejected promise nobody handled while the test ran, as Node reports it. */
  let unhandled: unknown[];
  const observe = (reason: unknown) => {
    unhandled.push(reason);
  };

  beforeEach(() => {
    // App.tsx owns a module-level QueryClient: a fresh module graph gives each test a fresh cache.
    vi.resetModules();
    // The dashboard a sign-in may open; the member's session answers before it.
    server.use(...dashboardHandlers([]).handlers);
    const member = memberSession();
    session = member.state;
    server.use(...member.handlers);
    window.history.replaceState(null, "", "/settings");
    unhandled = [];
    process.on("unhandledRejection", observe);
  });

  afterEach(() => {
    process.off("unhandledRejection", observe);
  });

  async function openSettings() {
    const { App } = await import("@/app/App");
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Settings" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    return userEvent.setup();
  }

  /** Signs out from the header and waits for the login page, with no error shown on it. */
  async function signOut(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(
      await screen.findByRole("form", { name: "Sign in" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // Node reports a rejection nobody handled once the task that rejected it has ended.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
  }

  it("opens the login page when the session had already ended, and then the dashboard", async () => {
    const user = await openSettings();
    // The server ended the session first (it expired, or was revoked): the logout is a 401.
    session.signedIn = false;

    await signOut(user);
    expect(session.requests.at(-1)).toBe("POST /auth/logout");
    expect(unhandled).toEqual([]);

    // As after any Sign out, the next sign-in opens the dashboard, not the page the person left.
    await user.type(screen.getByLabelText("Username"), "ada");
    await user.type(screen.getByLabelText("Password"), MEMBER_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", { name: "Boards", level: 1 }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    expect(addressOf(window.location)).toBe("/");
    expect(unhandled).toEqual([]);
  }, 30_000);

  it.each([
    ["the server fails the logout", () => failure(500, "internal_error", "Internal server error")],
    ["the network is down", () => HttpResponse.error()],
  ])(
    "signs the person out in the tab when %s",
    async (_case, answer) => {
      let asked = false;
      server.use(
        http.post(apiPath("/auth/logout"), () => {
          asked = true;
          return answer();
        }),
      );
      const user = await openSettings();

      await signOut(user);
      expect(asked).toBe(true);
      expect(unhandled).toEqual([]);
    },
    30_000,
  );
});
