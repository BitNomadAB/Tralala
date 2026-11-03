import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { Link, MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { reportCaughtError } from "@/app/errorReporting";
import { RouteErrorBoundary } from "@/app/RouteErrorBoundary";
import { ApiError } from "@/lib/api";

function Layout() {
  return (
    <>
      <header>Workspace header</header>
      <nav>
        <Link to="/fine">Fine page</Link>
        <Link to="/broken">Broken page</Link>
      </nav>
      <Outlet />
    </>
  );
}

function Thrower({ error }: { error: unknown }): ReactElement {
  throw error;
}

function BoardName({ load }: { load: () => Promise<string> }) {
  const query = useQuery({ queryKey: ["board-name"], queryFn: load, throwOnError: true });
  return <p>{query.data ?? "Loading board"}</p>;
}

/** The route tree of App.tsx in miniature: a boundary around the layout and one around the pages. */
function renderApp(path: string, broken: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<RouteErrorBoundary />}>
            <Route element={<Layout />}>
              <Route element={<RouteErrorBoundary />}>
                <Route path="/fine" element={<p>Everything is fine</p>} />
                <Route path="/broken" element={broken} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
    // What main.tsx passes to createRoot.
    { onCaughtError: reportCaughtError },
  );
}

describe("RouteErrorBoundary", () => {
  let consoleError: MockInstance<typeof console.error>;

  beforeEach(() => {
    consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    consoleError.mockRestore();
  });

  it("replaces a page that throws with a fallback and keeps the layout mounted", async () => {
    const user = userEvent.setup();
    const failure = new TypeError("board.lists is undefined");
    renderApp("/fine", <Thrower error={failure} />);

    await user.click(screen.getByRole("link", { name: "Broken page" }));

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("This page could not be shown");
    expect(alert).toHaveTextContent("Something went wrong while showing it.");
    expect(alert).not.toHaveTextContent("board.lists");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
    expect(screen.getByText("Workspace header")).toBeInTheDocument();
    // An unknown error is logged once, although the navigation and the throw were one update.
    expect(consoleError).toHaveBeenCalledTimes(1);
    expect(consoleError.mock.calls[0]?.[0]).toBe(failure);

    await user.click(screen.getByRole("link", { name: "Fine page" }));

    expect(screen.getByText("Everything is fine")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(consoleError).toHaveBeenCalledTimes(1);
  });

  it("shows an API error's message and request id and leaves its logging to the server", () => {
    const failure = new ApiError("Board not found", {
      code: "not_found",
      status: 404,
      requestId: "7d4f0c2e-request",
    });
    renderApp("/broken", <Thrower error={failure} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Board not found");
    expect(alert).toHaveTextContent("Request id: 7d4f0c2e-request");
    expect(screen.getByText("Workspace header")).toBeInTheDocument();
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("leaves the request id out when the response named none", () => {
    renderApp(
      "/broken",
      <Thrower error={new ApiError("Request failed (502)", { code: "http_502", status: 502 })} />,
    );

    expect(screen.getByRole("alert")).not.toHaveTextContent("Request id");
  });

  it("catches an error in the layout itself with the outer boundary", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/fine"]}>
          <Routes>
            <Route element={<RouteErrorBoundary />}>
              <Route element={<Thrower error={new Error("layout broke")} />}>
                <Route path="/fine" element={<p>Everything is fine</p>} />
              </Route>
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
      { onCaughtError: reportCaughtError },
    );

    expect(screen.getByRole("alert")).toHaveTextContent("This page could not be shown");
    expect(consoleError).toHaveBeenCalledTimes(1);
  });

  it("resets the failed queries below it on Try again, so they fetch again", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(
        new ApiError("Service unavailable", { code: "unavailable", status: 503, requestId: "r-1" }),
      )
      .mockResolvedValueOnce("Roadmap board");
    renderApp("/broken", <BoardName load={load} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    expect(load).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Roadmap board")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });
});
