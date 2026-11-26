import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { LoginPage } from "@/features/auth/LoginPage";
import { addressOf, returnPath, safeReturnPath } from "@/features/auth/returnPath";
import { dashboardHandlers } from "./msw/boards";
import { server } from "./msw/server";
import { MEMBER_PASSWORD, memberSession } from "./msw/session";

const ORIGIN = "https://tralala.example";
const DECISION = "/boards/b-1/loops/l-1?dialog=completion";

describe("the address the sign-in goes back to", () => {
  it("keeps the path, the query and the fragment of the address that was opened", () => {
    expect(
      addressOf({ pathname: "/boards/b-1/loops/l-1", search: "?dialog=completion", hash: "#qa" }),
    ).toBe("/boards/b-1/loops/l-1?dialog=completion#qa");
    expect(addressOf({ pathname: "/settings", search: "", hash: "" })).toBe("/settings");
  });

  it("follows a relative address that starts with one slash, query and fragment included", () => {
    for (const path of [
      "/",
      DECISION,
      "/boards/b-1/loops/l-1/tickets/c-1?focus=confirm",
      "/boards/b-1/loops/l-1?tab=plan&doc=analysis#top",
      // Encoded, the slashes are one segment of a path inside Tralala.
      "/%2F%2Fevil.example/x",
    ]) {
      expect(safeReturnPath(path, ORIGIN)).toBe(path);
    }
  });

  it("refuses another host, a scheme and anything that is not a relative path", () => {
    for (const refused of [
      "//evil.example/x",
      "///evil.example/x",
      "/\\evil.example/x",
      "https://evil.example/x",
      `${ORIGIN}/boards`,
      "javascript:alert(1)",
      "data:text/html,hi",
      "boards/b-1",
      "?dialog=completion",
      "",
      // A browser drops a tab or a line break from an address, which leaves "//evil.example".
      "/\t/evil.example/x",
      "/\n/evil.example/x",
      "/\r/evil.example/x",
      "/boards\u0000/b-1",
    ]) {
      expect(safeReturnPath(refused, ORIGIN), refused).toBe("/");
    }
  });

  it("reads only a string from the location state, else goes home", () => {
    expect(returnPath({ from: DECISION })).toBe(DECISION);
    expect(returnPath({ from: "//evil.example/x" })).toBe("/");
    expect(returnPath({ from: 42 })).toBe("/");
    expect(returnPath({ from: null })).toBe("/");
    expect(returnPath({})).toBe("/");
    expect(returnPath(null)).toBe("/");
    expect(returnPath(undefined)).toBe("/");
    expect(returnPath(DECISION)).toBe("/");
  });
});

/** Where the memory router is after the sign-in: the path, the query and the fragment. */
function Landed() {
  const location = useLocation();
  return <output aria-label="Landed">{addressOf(location)}</output>;
}

/** The login page over a member's session, opened by `RequireAuth` with `from` in its state. */
function renderLogin(from: unknown) {
  server.use(...memberSession().handlers);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[{ pathname: "/login", state: { from } }]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="*" element={<Landed />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

async function signIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Username"), "ada");
  await user.type(screen.getByLabelText("Password"), MEMBER_PASSWORD);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return screen.findByRole("status", { name: "Landed" });
}

describe("the sign-in", () => {
  it("goes to the address that was opened, with its query and fragment", async () => {
    const user = renderLogin(`${DECISION}#qa`);
    expect(await signIn(user)).toHaveTextContent(`${DECISION}#qa`);
  });

  it("goes home instead of to another host", async () => {
    const user = renderLogin("//evil.example/steal?dialog=completion");
    expect(await signIn(user)).toHaveTextContent(/^\/$/);
  });

  it("goes home instead of to a full address", async () => {
    const user = renderLogin("https://evil.example/steal");
    expect(await signIn(user)).toHaveTextContent(/^\/$/);
  });
});

describe("a signed-out person who opens an address in the app", () => {
  let session: ReturnType<typeof memberSession>["state"];

  beforeEach(() => {
    // App.tsx owns a module-level QueryClient: a fresh module graph gives each test a fresh cache.
    vi.resetModules();
    const member = memberSession();
    session = member.state;
    session.signedIn = false;
    server.use(...member.handlers);
    window.history.replaceState(null, "", "/settings?section=keys#tokens");
  });

  it("signs in on the login page and lands on that address, query and fragment kept", async () => {
    const { App } = await import("@/app/App");
    render(<App />);
    const user = userEvent.setup();
    expect(
      await screen.findByRole("form", { name: "Sign in" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/login");

    await user.type(screen.getByLabelText("Username"), "ada");
    await user.type(screen.getByLabelText("Password"), MEMBER_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { name: "Settings" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    expect(addressOf(window.location)).toBe("/settings?section=keys#tokens");
  });
});

describe("the sign-in after a session in the app ended", () => {
  let session: ReturnType<typeof memberSession>["state"];

  beforeEach(() => {
    // App.tsx owns a module-level QueryClient: a fresh module graph gives each test a fresh cache.
    vi.resetModules();
    // The dashboard a sign-in may open; the member's session answers before it.
    server.use(...dashboardHandlers([]).handlers);
    const member = memberSession();
    session = member.state;
    server.use(...member.handlers);
    window.history.replaceState(null, "", "/settings?section=keys#tokens");
  });

  async function openSettings() {
    const { App } = await import("@/app/App");
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Settings" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    return userEvent.setup();
  }

  async function signInAgain(user: ReturnType<typeof userEvent.setup>, password: string) {
    expect(
      await screen.findByRole("form", { name: "Sign in" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Username"), "ada");
    await user.type(screen.getByLabelText("Password"), password);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
  }

  const dashboard = () =>
    screen.findByRole("heading", { name: "Boards", level: 1 }, { timeout: 10_000 });

  it("opens the dashboard after Sign out, not the page the person signed out from", async () => {
    const user = await openSettings();
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(
      await screen.findByRole("form", { name: "Sign in" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    // Forgotten, not only passed over: a reload of the login page has no address to go back to.
    await waitFor(() => {
      const entry: unknown = window.history.state;
      expect(JSON.stringify(entry)).not.toContain("/settings");
    });
    expect(window.location.pathname).toBe("/login");

    await signInAgain(user, MEMBER_PASSWORD);
    expect(await dashboard()).toBeInTheDocument();
    expect(addressOf(window.location)).toBe("/");
  });

  it("opens the dashboard after a password change, which signs the person out", async () => {
    const user = await openSettings();
    await user.type(screen.getByLabelText("Current password"), MEMBER_PASSWORD);
    await user.type(screen.getByLabelText("New password"), "new-password-2");
    await user.type(screen.getByLabelText("Repeat new password"), "new-password-2");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    await signInAgain(user, "new-password-2");
    expect(await dashboard()).toBeInTheDocument();
    expect(addressOf(window.location)).toBe("/");
  });

  it("returns to the page after a session that ended by itself, also once Sign out forgot one", async () => {
    const user = await openSettings();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await signInAgain(user, MEMBER_PASSWORD);
    expect(await dashboard()).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Settings" }));
    expect(
      await screen.findByRole("heading", { name: "Settings" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    // The session ends on the server (it expired, or was revoked elsewhere); the next read is a 401.
    session.signedIn = false;
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await signInAgain(user, MEMBER_PASSWORD);
    expect(
      await screen.findByRole("heading", { name: "Settings" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    expect(addressOf(window.location)).toBe("/settings");
  });
});
