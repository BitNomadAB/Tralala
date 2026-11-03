import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ComponentType } from "react";
import { Link, MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { lazyPage, watchStaleChunks } from "@/app/chunkLoading";
import { reportCaughtError } from "@/app/errorReporting";
import { RouteErrorBoundary } from "@/app/RouteErrorBoundary";

const RELOAD_FLAG = "tralala:stale-chunk-reload";

type PageModule<Name extends string> = Record<Name, ComponentType>;

/** A chunk the server no longer has, worded as Chromium words it. */
function missingChunk() {
  return new TypeError(
    "Failed to fetch dynamically imported module: https://example.com/assets/BrokenPage-1a2b3c4d.js",
  );
}

/** What `vite:preloadError` looks like: an Event carrying the import's error as `payload`. */
function preloadError(error: Error): VitePreloadErrorEvent {
  return Object.assign(new Event("vite:preloadError", { cancelable: true }), { payload: error });
}

/**
 * What Vite's build wraps every dynamic import in (its preload helper): a failed import is
 * announced on `window` before it rejects.
 */
async function viteImport<Module>(load: () => Promise<Module>): Promise<Module> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof Error) window.dispatchEvent(preloadError(error));
    throw error;
  }
}

function FinePage() {
  return <p>Everything is fine</p>;
}

function finePage() {
  return lazyPage(() => viteImport(() => Promise.resolve({ FinePage })), "FinePage");
}

function brokenPage() {
  return lazyPage(
    () => viteImport<PageModule<"BrokenPage">>(() => Promise.reject(missingChunk())),
    "BrokenPage",
  );
}

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

/** App.tsx's route shape in miniature, with lazy pages as App.tsx declares them. */
function renderApp(path: string, Fine: ComponentType, Broken: ComponentType) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<RouteErrorBoundary />}>
            <Route element={<Layout />}>
              <Route element={<RouteErrorBoundary />}>
                <Route path="/fine" element={<Fine />} />
                <Route path="/broken" element={<Broken />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
    { onCaughtError: reportCaughtError },
  );
}

describe("stale page chunks", () => {
  let consoleError: MockInstance<typeof console.error>;
  let reload: ReturnType<typeof vi.fn<() => void>>;
  let unwatch: () => void;

  beforeEach(() => {
    sessionStorage.clear();
    consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    reload = vi.fn<() => void>();
    unwatch = watchStaleChunks(window, reload);
  });

  afterEach(() => {
    unwatch();
    consoleError.mockRestore();
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("reloads once, and again only after a page has loaded", async () => {
    window.dispatchEvent(preloadError(missingChunk()));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(RELOAD_FLAG)).not.toBeNull();

    // The reloaded tab still cannot load the chunk: the flag stops a second reload, so no loop.
    window.dispatchEvent(preloadError(missingChunk()));
    window.dispatchEvent(preloadError(missingChunk()));
    expect(reload).toHaveBeenCalledTimes(1);

    const Fine = finePage();
    render(
      <Suspense fallback={null}>
        <Fine />
      </Suspense>,
    );
    expect(await screen.findByText("Everything is fine")).toBeInTheDocument();
    expect(sessionStorage.getItem(RELOAD_FLAG)).toBeNull();

    // A later upgrade may reload the tab again.
    window.dispatchEvent(preloadError(missingChunk()));
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("shows a page's loading state inside the layout while its chunk loads", async () => {
    let resolvePage: (module: { FinePage: typeof FinePage }) => void = () => undefined;
    const Slow = lazyPage(
      () =>
        new Promise<{ FinePage: typeof FinePage }>((resolve) => {
          resolvePage = resolve;
        }),
      "FinePage",
    );
    renderApp("/fine", Slow, brokenPage());

    expect(await screen.findByRole("status")).toHaveTextContent("Loading page…");
    expect(screen.getByText("Workspace header")).toBeInTheDocument();

    resolvePage({ FinePage });

    expect(await screen.findByText("Everything is fine")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reloads when a page's chunk is gone, says so instead of failing and logs nothing", async () => {
    const user = userEvent.setup();
    renderApp("/fine", finePage(), brokenPage());
    expect(await screen.findByText("Everything is fine")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Broken page" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Loading the new version");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
    // React keeps a failed lazy import, so "Try again" could only fail again.
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Workspace header")).toBeInTheDocument();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("shows and logs the failure that remains after the reload, without reloading again", async () => {
    // The tab has reloaded once for this chunk already.
    sessionStorage.setItem(RELOAD_FLAG, "2026-11-03T10:00:00.000Z");
    renderApp("/broken", finePage(), brokenPage());

    expect(await screen.findByRole("alert")).toHaveTextContent("This page could not be shown");
    expect(screen.getByText("Workspace header")).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalledTimes(1);
    expect(consoleError.mock.calls[0]?.[0]).toBeInstanceOf(TypeError);
  });

  it("never reloads when session storage is unavailable, because nothing could stop a loop", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    });

    window.dispatchEvent(preloadError(missingChunk()));

    expect(reload).not.toHaveBeenCalled();
  });
});
