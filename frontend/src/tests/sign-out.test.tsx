import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { useAuth } from "@/features/auth/useAuth";
import { api } from "@/lib/api";
import type { Actor, ApiMeta } from "@/lib/types";

const MEMBER: Actor = {
  id: "user-1",
  type: "user",
  name: "Ada Member",
  role: "member",
  scopes: [],
  preferences: null,
};

const META: ApiMeta = {
  api_version: "v1",
  scopes: [],
  token_scopes: [],
  member_token_scopes: [],
  member_token_limits: { live: 5, default_days: 30, max_days: 365 },
  can_issue_tokens: true,
  features: {},
};

const PAGE = { total: 0, limit: 50, offset: 0, has_more: false };

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "req-test" },
  });
}

const ok = (data: unknown, meta?: unknown) =>
  reply(200, { success: true, data, meta, request_id: "req-test" });

const failure = (status: number, code: string, message: string) =>
  reply(status, { success: false, error: { code, message }, request_id: "req-test" });

function field(body: unknown, name: string): string {
  const value = (body as Record<string, unknown> | undefined)?.[name];
  return typeof value === "string" ? value : "";
}

/**
 * The server side of a member's session, behind `fetch`: the settings page and the dashboard are
 * answered, a password change and a logout end the session, and once it has ended every request
 * except a sign-in is a 401. `requests` is everything the app sent, as "METHOD /path".
 */
function fakeServer() {
  const server = { signedIn: true, password: "old-password-1", requests: [] as string[] };

  function answer(method: string, path: string, body: unknown): Response {
    if (method === "POST" && path === "/auth/login") {
      if (field(body, "password") !== server.password) {
        return failure(401, "invalid_credentials", "Invalid username or password");
      }
      server.signedIn = true;
      return ok({ actor: MEMBER, csrf_token: "csrf-test" });
    }
    if (!server.signedIn) return failure(401, "unauthorized", "Authentication required");
    switch (`${method} ${path}`) {
      case "GET /auth/me":
        return ok(MEMBER);
      case "GET /meta":
        return ok(META);
      case "GET /templates":
        return ok({ items: [] });
      case "GET /role-templates":
      case "GET /agents":
      case "GET /credentials/mine":
        return ok([]);
      case "GET /boards":
        return ok([], PAGE);
      case "POST /auth/password":
        server.password = field(body, "new_password");
        server.signedIn = false;
        return ok({ changed: true, revoked_sessions: 1 });
      case "POST /auth/logout":
        server.signedIn = false;
        return ok({ logged_out: true });
      default:
        return failure(404, "not_found", "Not found");
    }
  }

  const fetch = vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const href = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    const url = new URL(href, "http://localhost");
    const method = init?.method ?? "GET";
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    server.requests.push(`${method} ${path}`);
    return Promise.resolve(answer(method, path, body));
  });

  return { server, fetch };
}

describe("signing out in the app", () => {
  let server: ReturnType<typeof fakeServer>["server"];

  beforeEach(() => {
    // Fake time that also moves on its own, so the page can load; the tests then jump a minute.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // App.tsx owns a module-level QueryClient: a fresh module graph gives each test a fresh cache.
    vi.resetModules();
    const fake = fakeServer();
    server = fake.server;
    vi.stubGlobal("fetch", fake.fetch);
    window.history.replaceState(null, "", "/settings");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function renderSettings() {
    const { App } = await import("@/app/App");
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Settings" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    return userEvent.setup({
      advanceTimers: (delay) => {
        vi.advanceTimersByTime(delay);
      },
    });
  }

  async function aMinuteLater() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
  }

  const loginForm = () => screen.findByRole("form", { name: "Sign in" }, { timeout: 10_000 });

  it("shows the login page after a password change, then asks the server nothing", async () => {
    const user = await renderSettings();

    await user.type(screen.getByLabelText("Current password"), "old-password-1");
    await user.type(screen.getByLabelText("New password"), "new-password-2");
    await user.type(screen.getByLabelText("Repeat new password"), "new-password-2");
    // In act, because the handler navigates once the server has answered, after the click returns.
    await act(() => user.click(screen.getByRole("button", { name: "Change password" })));

    expect(await loginForm()).toBeInTheDocument();
    expect(screen.getByText("Password changed")).toBeInTheDocument();
    // Not a single request with the ended session, and none in the minute after: no 401 loop.
    expect(server.requests.at(-1)).toBe("POST /auth/password");
    const sent = server.requests.length;
    await aMinuteLater();
    expect(server.requests.slice(sent)).toEqual([]);

    // The session is still observed, so signing in with the new password opens the workspace.
    await user.type(screen.getByLabelText("Password"), "new-password-2");
    await act(() => user.click(screen.getByRole("button", { name: "Sign in" })));
    expect(await screen.findByRole("button", { name: "Sign out" })).toBeInTheDocument();
  }, 30_000);

  it("shows the login page on a burst of 401s and stops every query, retries included", async () => {
    const user = await renderSettings();
    // Every cached query is stale (App's staleTime is 5 s), so the next page refetches as well.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    // The session ends on the server, e.g. it expired or was revoked from another device.
    server.signedIn = false;
    const expired = server.requests.length;

    await user.click(screen.getByRole("link", { name: "Boards" }));

    expect(await loginForm()).toBeInTheDocument();
    await aMinuteLater();
    const after = server.requests.slice(expired);
    // Several queries met the 401 at once; each asked once (App retries a failed query once).
    expect(after.length).toBeGreaterThan(1);
    expect(new Set(after).size).toBe(after.length);
    expect(after).not.toContain("GET /auth/me");
  }, 30_000);

  it("shows the login page after signing out from the header, then asks the server nothing", async () => {
    const user = await renderSettings();

    await act(() => user.click(screen.getByRole("button", { name: "Sign out" })));

    expect(await loginForm()).toBeInTheDocument();
    expect(server.requests.at(-1)).toBe("POST /auth/logout");
    const sent = server.requests.length;
    await aMinuteLater();
    expect(server.requests.slice(sent)).toEqual([]);
  }, 30_000);
});

describe("signOutLocally", () => {
  function Session() {
    const { actor, loading, login } = useAuth();
    if (loading) return <p>Loading session</p>;
    return (
      <>
        <p>{actor ? `Signed in as ${actor.name}` : "Signed out"}</p>
        <button type="button" onClick={() => void login("ada", "secret-password")}>
          Sign in
        </button>
      </>
    );
  }

  function renderSession() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <Session />
        </AuthProvider>
      </QueryClientProvider>,
    );
    return client;
  }

  const unauthorized = () => {
    act(() => {
      window.dispatchEvent(new CustomEvent("tralala:unauthorized"));
    });
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("runs once for a burst of 401s, and again for the next session", async () => {
    vi.spyOn(api, "me").mockResolvedValue(MEMBER);
    vi.spyOn(api, "login").mockResolvedValue(MEMBER);
    const client = renderSession();
    expect(await screen.findByText("Signed in as Ada Member")).toBeInTheDocument();
    client.setQueryData(["boards"], []);
    const remove = vi.spyOn(client, "removeQueries");

    act(() => {
      for (let count = 0; count < 5; count += 1) {
        window.dispatchEvent(new CustomEvent("tralala:unauthorized"));
      }
    });

    expect(await screen.findByText("Signed out")).toBeInTheDocument();
    expect(client.getQueryData(["boards"])).toBeUndefined();
    expect(remove).toHaveBeenCalledTimes(1);

    // A 401 while signed out (a wrong password on the login page) has nothing left to forget.
    unauthorized();
    expect(remove).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Signed in as Ada Member")).toBeInTheDocument();
    unauthorized();
    expect(await screen.findByText("Signed out")).toBeInTheDocument();
    expect(remove).toHaveBeenCalledTimes(2);
  });

  it("does not let a read of the session still on its way sign the user back in", async () => {
    const me = vi.spyOn(api, "me").mockResolvedValueOnce(MEMBER);
    const client = renderSession();
    expect(await screen.findByText("Signed in as Ada Member")).toBeInTheDocument();

    let answer: (actor: Actor) => void = () => undefined;
    me.mockImplementationOnce(
      () =>
        new Promise<Actor>((resolve) => {
          answer = resolve;
        }),
    );
    void client.refetchQueries({ queryKey: ["me"] });
    expect(me).toHaveBeenCalledTimes(2);

    unauthorized();
    expect(await screen.findByText("Signed out")).toBeInTheDocument();

    // The read answers with the session it started under.
    await act(async () => {
      answer(MEMBER);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByText("Signed out")).toBeInTheDocument();
    expect(client.getQueryData(["me"])).toBeNull();
  });
});
