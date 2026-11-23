import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Link, MemoryRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppLayout } from "@/app/AppLayout";
import { useRouteFocus } from "@/app/useRouteFocus";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { ThemeProvider } from "@/themes/ThemeProvider";
import { MEMBER } from "./msw/session";

/** A promise and the function that settles it, for a page the test decides when to show. */
function signal() {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function RouteFocus() {
  useRouteFocus();
  return null;
}

function Home() {
  return (
    <>
      <h1>Boards</h1>
      <Link to="/slow">Slow page</Link>
      <Link to="/editor">New template</Link>
      <Link to="/?tab=plan">Plan tab</Link>
    </>
  );
}

/** A page that renders at once and shows its heading when its data arrives, as the pages do. */
function SlowPage({ loaded }: { loaded: Promise<void> }) {
  const query = useQuery({ queryKey: ["slow"], queryFn: () => loaded.then(() => "Slow page") });
  return query.data ? <h1>{query.data}</h1> : <p>Loading page…</p>;
}

/** A dialog that stays open while the path changes, as one beside the routes would. */
function OpenDialog() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Pick a page">
          <button type="button" onClick={() => void navigate("/settings")}>
            Go to Settings
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** The workspace layout of App.tsx with stand-in pages, signed in as the member. */
function renderLayout(path: string, loaded: Promise<void> = Promise.resolve()) {
  const auth = {
    actor: MEMBER,
    loading: false,
    login: () => Promise.resolve(MEMBER),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(MEMBER),
    signOutLocally: () => undefined,
  };
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthContext.Provider value={auth}>
        <ThemeProvider>
          <ToastProvider>
            <MemoryRouter initialEntries={[path]}>
              <RouteFocus />
              <Routes>
                <Route element={<AppLayout />}>
                  <Route path="/" element={<Home />} />
                  <Route path="/old" element={<Navigate to="/" replace />} />
                  <Route path="/settings" element={<h1>Settings page</h1>} />
                  <Route path="/slow" element={<SlowPage loaded={loaded} />} />
                  <Route
                    path="/editor"
                    element={
                      <>
                        <h1>New board template</h1>
                        <input aria-label="Name" autoFocus />
                      </>
                    }
                  />
                </Route>
              </Routes>
              <OpenDialog />
            </MemoryRouter>
          </ToastProvider>
        </ThemeProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe("the workspace layout", () => {
  it("offers a skip link on the first Tab that moves focus to the main content", async () => {
    const user = renderLayout("/");

    await user.tab();
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveFocus();
    expect(skip).toHaveAttribute("href", "#main");

    await user.keyboard("{Enter}");
    const main = screen.getByRole("main");
    expect(main).toHaveFocus();
    expect(main).toHaveAttribute("id", "main");
  });
});

describe("focus after a navigation", () => {
  it("stays where it is on the first page and moves to the new page's heading", async () => {
    const user = renderLayout("/");
    expect(document.body).toHaveFocus();

    await user.click(screen.getByRole("link", { name: "Settings" }));

    const heading = screen.getByRole("heading", { level: 1, name: "Settings page" });
    expect(heading).toHaveFocus();
    expect(heading).toHaveAttribute("tabindex", "-1");
  });

  it("is not moved by a redirect while the app starts", () => {
    renderLayout("/old");
    expect(screen.getByRole("heading", { level: 1, name: "Boards" })).toBeInTheDocument();
    expect(document.body).toHaveFocus();
  });

  it("waits on the main region for a page that is still loading, then takes its heading", async () => {
    const slow = signal();
    const user = renderLayout("/", slow.promise);

    await user.click(screen.getByRole("link", { name: "Slow page" }));
    expect(screen.getByText("Loading page…")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveFocus();

    await act(async () => {
      slow.resolve();
      await slow.promise;
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Slow page" })).toHaveFocus();
  });

  it("leaves a field the new page focused itself", async () => {
    const user = renderLayout("/");
    await user.click(screen.getByRole("link", { name: "New template" }));
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveFocus();
  });

  it("stays on the page when only the query changes", async () => {
    const user = renderLayout("/");
    const link = screen.getByRole("link", { name: "Plan tab" });
    await user.click(link);
    expect(link).toHaveFocus();
  });

  it("never leaves an open dialog", async () => {
    const user = renderLayout("/");
    await user.click(screen.getByRole("button", { name: "Open dialog" }));
    const go = screen.getByRole("button", { name: "Go to Settings" });
    await user.click(go);

    expect(
      screen.getByRole("heading", { level: 1, name: "Settings page", hidden: true }),
    ).toBeInTheDocument();
    expect(go).toHaveFocus();
  });
});
