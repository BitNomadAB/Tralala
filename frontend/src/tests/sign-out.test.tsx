import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { useAuth } from "@/features/auth/useAuth";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER, MEMBER_PASSWORD, memberSession } from "./msw/session";

/** A promise and the function that settles it, for a step the test decides when to take. */
function signal() {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

describe("signing out in the app", () => {
  let session: ReturnType<typeof memberSession>["state"];

  beforeEach(() => {
    // Fake time that also moves on its own, so the page can load; the tests then jump a minute.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // App.tsx owns a module-level QueryClient: a fresh module graph gives each test a fresh cache.
    vi.resetModules();
    const member = memberSession();
    session = member.state;
    server.use(...member.handlers);
    window.history.replaceState(null, "", "/settings");
  });

  afterEach(() => {
    vi.useRealTimers();
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

  /**
   * Clicks a button the server answers, then lets the answer and every redirect it causes happen,
   * all inside act. Not user-event: its wrapper hands React's act environment back on a fake-timer
   * tick that can also deliver the server's answer, so the redirect would land just outside act.
   */
  async function clickAndAwaitServer(name: string) {
    fireEvent.click(screen.getByRole("button", { name }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
  }

  const loginForm = () => screen.findByRole("form", { name: "Sign in" }, { timeout: 10_000 });

  it("shows the login page after a password change, then asks the server nothing", async () => {
    const user = await renderSettings();

    await user.type(screen.getByLabelText("Current password"), MEMBER_PASSWORD);
    await user.type(screen.getByLabelText("New password"), "new-password-2");
    await user.type(screen.getByLabelText("Repeat new password"), "new-password-2");
    await clickAndAwaitServer("Change password");

    expect(await loginForm()).toBeInTheDocument();
    expect(screen.getByText("Password changed")).toBeInTheDocument();
    // Not a single request with the ended session, and none in the minute after: no 401 loop.
    expect(session.requests.at(-1)).toBe("POST /auth/password");
    const sent = session.requests.length;
    await aMinuteLater();
    expect(session.requests.slice(sent)).toEqual([]);

    // The session is still observed, so signing in with the new password opens the workspace. The
    // server took the new password from the JSON body the client sent.
    await user.type(screen.getByLabelText("Password"), "new-password-2");
    await clickAndAwaitServer("Sign in");
    expect(await screen.findByRole("button", { name: "Sign out" })).toBeInTheDocument();
  }, 30_000);

  it("keeps the tab signed in when the current password is wrong", async () => {
    const user = await renderSettings();

    await user.type(screen.getByLabelText("Current password"), "not-my-password");
    await user.type(screen.getByLabelText("New password"), "new-password-2");
    await user.type(screen.getByLabelText("Repeat new password"), "new-password-2");
    await clickAndAwaitServer("Change password");

    expect(screen.getByText("Could not change the password")).toBeInTheDocument();
    expect(screen.getByText("Current password is incorrect")).toBeInTheDocument();
    // The session is still valid, so nothing ends it: the page stays, and so does the session.
    await aMinuteLater();
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Sign in" })).not.toBeInTheDocument();
    expect(session.signedIn).toBe(true);
  }, 30_000);

  it("shows the login page on a burst of 401s and stops every query, retries included", async () => {
    const user = await renderSettings();
    // Every cached query is stale (App's staleTime is 5 s), so the next page refetches as well.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    // The session ends on the server, e.g. it expired or was revoked from another device.
    session.signedIn = false;
    const expired = session.requests.length;

    await user.click(screen.getByRole("link", { name: "Boards" }));

    expect(await loginForm()).toBeInTheDocument();
    await aMinuteLater();
    const after = session.requests.slice(expired);
    // Several queries met the 401 at once; each asked once (App retries a failed query once).
    expect(after.length).toBeGreaterThan(1);
    expect(new Set(after).size).toBe(after.length);
    expect(after).not.toContain("GET /auth/me");
  }, 30_000);

  it("shows the login page after signing out from the header, then asks the server nothing", async () => {
    await renderSettings();

    await clickAndAwaitServer("Sign out");

    expect(await loginForm()).toBeInTheDocument();
    expect(session.requests.at(-1)).toBe("POST /auth/logout");
    const sent = session.requests.length;
    await aMinuteLater();
    expect(session.requests.slice(sent)).toEqual([]);
  }, 30_000);
});

describe("signOutLocally", () => {
  function Session() {
    const { actor, loading, login } = useAuth();
    if (loading) return <p>Loading session</p>;
    return (
      <>
        <p>{actor ? `Signed in as ${actor.name}` : "Signed out"}</p>
        <button type="button" onClick={() => void login("ada", MEMBER_PASSWORD)}>
          Sign in
        </button>
      </>
    );
  }

  function renderSession() {
    server.use(...memberSession().handlers);
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
    server.events.removeAllListeners();
  });

  it("runs once for a burst of 401s, and again for the next session", async () => {
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
    const client = renderSession();
    expect(await screen.findByText("Signed in as Ada Member")).toBeInTheDocument();

    // The next read of the session reaches the server and waits there until the test answers it.
    const arrived = signal();
    const answer = signal();
    const answered = signal();
    server.use(
      http.get(
        apiPath("/auth/me"),
        async () => {
          arrived.resolve();
          await answer.promise;
          return ok(MEMBER);
        },
        { once: true },
      ),
    );
    server.events.on("response:mocked", () => {
      answered.resolve();
    });
    void client.refetchQueries({ queryKey: ["me"] });
    await arrived.promise;

    unauthorized();
    expect(await screen.findByText("Signed out")).toBeInTheDocument();

    // The read answers with the session it started under, and the client reads that answer.
    await act(async () => {
      answer.resolve();
      await answered.promise;
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByText("Signed out")).toBeInTheDocument();
    expect(client.getQueryData(["me"])).toBeNull();
  });
});
