import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, type HttpHandler } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { DashboardPage } from "@/features/boards/DashboardPage";
import type { Board, DiscussionInboxRow, LoopSummary } from "@/lib/types";
import { board, dashboardHandlers, summary } from "./msw/boards";
import { inboxRow } from "./msw/discussionInbox";
import { apiPath, failure, ok } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";

const AUTH = {
  actor: MEMBER,
  loading: false,
  login: () => Promise.resolve(MEMBER),
  logout: () => Promise.resolve(),
  refresh: () => Promise.resolve(MEMBER),
  signOutLocally: () => undefined,
};

/** Where a button took the person: the path and the query. */
function Location() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname + location.search}</p>;
}

/** Renders the dashboard; `overrides` answer before the default handlers. */
function renderDashboard(
  boards: Board[],
  summaries: Record<string, LoopSummary[]> = {},
  overrides: HttpHandler[] = [],
  discussions: DiscussionInboxRow[] = [],
) {
  const { state, handlers } = dashboardHandlers(boards, summaries, discussions);
  server.use(...handlers);
  server.use(...overrides);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={AUTH}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/"]}>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="*" element={<Location />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return { state, user: userEvent.setup() };
}

const PLATFORM = board("board-1", "Platform", { description: "The shared services" });
const WEBSITE = board("board-2", "Website");

/** A Loop whose analysis waits for a person's approval. */
const REVIEW = summary("loop-1", "Session expiry", {
  stage: "analysis_review",
  waiting_on: "person",
  documents: {
    info: "approved r1",
    analysis_ai: "ready_for_review r1",
    analysis: "ready_for_review r1",
    roadmap_ai: "empty",
    roadmap: "empty",
  },
});

/** A Loop in delivery with Tickets ready for anyone: nothing waits for a decision. */
const DELIVERY = summary("loop-2", "Checkout", {
  stage: "in_progress",
  waiting_on: "anyone",
  tickets: { ready: 2, total: 4, completed: 2 },
});

describe("the dashboard", () => {
  it("lists what waits for the person first, then the boards with their Loops in words", async () => {
    const { state, user } = renderDashboard([PLATFORM, WEBSITE], {
      "board-1": [REVIEW, DELIVERY],
      "board-2": [],
    });

    const waits = await screen.findByRole("list", { name: "Waits for you" });
    const rows = within(waits).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    const row = within(rows[0] ?? waits);
    expect(row.getByText("Platform")).toBeInTheDocument();
    expect(row.getByText("Session expiry")).toBeInTheDocument();
    expect(row.getByText("Waits for you to approve the analysis")).toBeInTheDocument();

    const tiles = screen.getByRole("list", { name: "Boards" });
    const platform = within(tiles).getByRole("button", { name: "Platform" });
    const tile = within(platform.closest("li") ?? tiles);
    expect(tile.getByText("The shared services")).toBeInTheDocument();
    expect(tile.getByText("2 Loops in progress · 1 waits for you")).toBeInTheDocument();
    expect(within(tiles).getByText("No Loops in progress")).toBeInTheDocument();
    // No board is archived, so there is no read-only group.
    expect(screen.queryByRole("heading", { name: /^Read only/ })).toBeNull();

    // One request for the boards (the tiles and the waiting list share it), one a board.
    expect(state.requests.filter((request) => request === "GET /boards")).toHaveLength(1);
    expect(state.requests.filter((request) => request.endsWith("/loop-summaries")).sort()).toEqual([
      "GET /boards/board-1/loop-summaries",
      "GET /boards/board-2/loop-summaries",
    ]);

    // The button opens the Loop page on the tab where the decision is made.
    await user.click(row.getByRole("button", { name: "Approve analysis: Session expiry" }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/boards/board-1/loops/loop-1?tab=plan",
    );
  });

  it("lists a discussion that waits for a decision after the Loop rows, and opens it", async () => {
    const waiting = inboxRow("wait-1", { question: "Should the key rotate every week?" });
    const talking = inboxRow("talk-1", { waits_for: "agents", run_state: "running" });
    const decided = inboxRow("done-1", { waits_for: "nobody", status: "approved" });
    const { user } = renderDashboard(
      [PLATFORM],
      { "board-1": [REVIEW] },
      [],
      [waiting, talking, decided],
    );

    const waits = await screen.findByRole("list", { name: "Waits for you" });
    await within(waits).findByText("Should the key rotate every week?");
    const rows = within(waits).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Session expiry");
    const row = within(rows[1] ?? waits);
    expect(row.getByText("Waits for your decision on a discussion")).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent("Platform · SES-1-PH01-001");
    expect(screen.getByRole("heading", { name: "Waits for you 2" })).toBeInTheDocument();

    await user.click(
      row.getByRole("button", { name: "Open discussion: Should the key rotate every week?" }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/boards/board-1/loops/loop-1/tickets/card-1/discussions/wait-1",
    );
  });

  it("says nothing waits when neither a Loop nor a discussion needs a decision", async () => {
    renderDashboard(
      [PLATFORM],
      { "board-1": [DELIVERY] },
      [],
      [
        inboxRow("talk-1", { waits_for: "agents", run_state: "running" }),
        inboxRow("done-1", { waits_for: "nobody", status: "vetoed" }),
      ],
    );

    expect(await screen.findByText("Nothing waits for you.")).toBeInTheDocument();
    expect(screen.queryByText("Waits for your decision on a discussion")).toBeNull();
  });

  it("lists an archived board under Read only, apart from the boards in use", async () => {
    const archived = board("board-3", "Old site", { status: "archived" });
    // The archived board is the most recent, yet it does not sit among the boards in use.
    renderDashboard([archived, WEBSITE], {
      "board-2": [DELIVERY],
      // An archived board decides nothing, so its review is not listed.
      "board-3": [REVIEW],
    });

    expect(await screen.findByText("Nothing waits for you.")).toBeInTheDocument();
    const tiles = screen.getByRole("list", { name: "Boards" });
    expect(within(tiles).getByRole("button", { name: "Website" })).toBeInTheDocument();
    expect(within(tiles).queryByRole("button", { name: "Old site" })).toBeNull();
    expect(within(tiles).queryByText("Read only")).toBeNull();

    expect(screen.getByRole("heading", { name: "Read only 1" })).toBeInTheDocument();
    const readOnly = screen.getByRole("list", { name: "Read only boards" });
    const old = within(
      within(readOnly).getByRole("button", { name: "Old site" }).closest("li") ?? readOnly,
    );
    expect(old.getByText("Read only")).toBeInTheDocument();
    expect(await old.findByText("1 Loop in progress")).toBeInTheDocument();
    // The status filter chooses among the boards in use; the archived ones have their own group.
    const filter = screen.getByRole("combobox", { name: "Filter by status" });
    expect(within(filter).queryByRole("option", { name: "Archived" })).toBeNull();
  });

  it("says no board is active when every board is archived", async () => {
    const { user } = renderDashboard([board("board-3", "Old site", { status: "archived" })], {
      "board-3": [],
    });

    expect(await screen.findByText("No active boards.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Boards" })).toBeNull();
    const readOnly = screen.getByRole("list", { name: "Read only boards" });
    expect(within(readOnly).getByRole("button", { name: "Old site" })).toBeInTheDocument();

    // The archived board keeps its way back and its way out.
    await user.click(screen.getByRole("button", { name: "More actions for Old site" }));
    const menu = screen.getByRole("menu", { name: "More actions for Old site" });
    expect(within(menu).getByRole("menuitem", { name: "Restore board" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Delete board/ })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("renders the tiles before a slow board has answered, and names a board that failed", async () => {
    renderDashboard([PLATFORM, WEBSITE], {}, [
      http.get(apiPath("/boards/board-1/loop-summaries"), () =>
        failure(500, "internal_error", "Something failed"),
      ),
      // Never answers: the tile shows that it is still reading.
      http.get(apiPath("/boards/board-2/loop-summaries"), async () => {
        await delay("infinite");
        return ok({});
      }),
    ]);

    const tiles = await screen.findByRole("list", { name: "Boards" });
    expect(within(tiles).getByRole("button", { name: "Website" })).toBeVisible();
    expect(await within(tiles).findByText("Reading Loops…")).toBeInTheDocument();
    expect(await within(tiles).findByText("Loops could not be read")).toBeInTheDocument();
    expect(screen.getByText("Looking through your boards…")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/1 board could not be read/)).toBeInTheDocument();
    });
  });

  it("says a new installation has no boards yet, and offers New board", async () => {
    const { user } = renderDashboard([], {}, [
      http.get(apiPath("/templates"), () => ok({ items: [] })),
      http.get(apiPath("/agents"), () => ok([])),
      http.get(apiPath("/repositories"), () => ok([])),
    ]);

    expect(await screen.findByText("No boards yet.")).toBeInTheDocument();
    expect(screen.getByText("Nothing waits for you.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New board" }));
    expect(await screen.findByRole("dialog", { name: "New board" })).toBeInTheDocument();
  });

  it("keeps the lifecycle actions in the tile's quiet menu", async () => {
    const { user } = renderDashboard([PLATFORM], { "board-1": [] });

    await user.click(await screen.findByRole("button", { name: "More actions for Platform" }));
    const menu = screen.getByRole("menu", { name: "More actions for Platform" });
    expect(within(menu).getByRole("menuitem", { name: "Archive board" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Delete board/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});
