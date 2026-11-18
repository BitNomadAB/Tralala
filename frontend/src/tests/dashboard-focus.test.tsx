import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { DashboardPage } from "@/features/boards/DashboardPage";
import { boardCountWords } from "@/features/boards/resultAnnouncements";
import type { Board } from "@/lib/types";
import { announcer } from "./announcer";
import { board, dashboardHandlers } from "./msw/boards";
import { apiPath, ok } from "./msw/envelope";
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

/**
 * The dashboard over boards the server keeps: `GET /boards` filters them by name (`q`) and status,
 * as the server does, and archiving or restoring one changes it.
 */
function renderDashboard(initial: Board[]) {
  const boards = initial.map((entry) => ({ ...entry }));
  const { handlers } = dashboardHandlers([]);
  server.use(...handlers);
  server.use(
    http.get(apiPath("/boards"), ({ request }) => {
      const params = new URL(request.url).searchParams;
      const q = (params.get("q") ?? "").toLowerCase();
      const status = params.get("status") ?? "";
      const items = boards.filter(
        (entry) =>
          entry.name.toLowerCase().includes(q) && (status === "" || entry.status === status),
      );
      return ok(items, { total: items.length, limit: 50, offset: 0, has_more: false });
    }),
    http.post(apiPath("/boards/:boardId/:action"), ({ params }) => {
      const target = boards.find((entry) => entry.id === params.boardId);
      if (!target) return ok(null);
      target.status = params.action === "archive" ? "archived" : "active";
      return ok(target);
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={AUTH}>
        <ToastProvider>
          <MemoryRouter>
            <DashboardPage />
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const PLATFORM = board("board-1", "Platform");
const WEBSITE = board("board-2", "Website");

describe("the dashboard's boards", () => {
  it("names each board with a link to its page", async () => {
    renderDashboard([PLATFORM]);

    const tiles = await screen.findByRole("list", { name: "Boards" });
    expect(within(tiles).getByRole("link", { name: "Platform" })).toHaveAttribute(
      "href",
      "/boards/board-1",
    );
  });

  it("says how many boards a search finds, and when none does", async () => {
    const user = renderDashboard([PLATFORM, WEBSITE]);
    await screen.findByRole("link", { name: "Website" });

    await user.type(screen.getByRole("textbox", { name: "Search boards" }), "web");
    await waitFor(() => expect(announcer()).toHaveTextContent("1 board matches."));

    await user.type(screen.getByRole("textbox", { name: "Search boards" }), "x");
    await waitFor(() => expect(announcer()).toHaveTextContent("No board matches."));
    expect(screen.getByText("No board matches.")).toBeInTheDocument();
  });

  it("keeps focus with a board that archiving and restoring move to the other list", async () => {
    const user = renderDashboard([PLATFORM, WEBSITE]);
    await screen.findByRole("link", { name: "Website" });

    await user.click(screen.getByRole("button", { name: "More actions for Website" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive board" }));

    const archived = await screen.findByRole("list", { name: "Archived boards" });
    const moved = within(archived).getByRole("button", { name: "More actions for Website" });
    await waitFor(() => expect(moved).toHaveFocus());
    expect(screen.getByText("Board archived")).toBeInTheDocument();

    await user.click(moved);
    await user.click(screen.getByRole("menuitem", { name: "Restore board" }));
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Boards" })).getByRole("button", {
          name: "More actions for Website",
        }),
      ).toHaveFocus(),
    );
  });
});

describe("undoing an archive", () => {
  it("offers Undo in the toast, which restores the board and keeps focus with its tile", async () => {
    const user = renderDashboard([PLATFORM, WEBSITE]);
    await screen.findByRole("link", { name: "Website" });
    await user.click(screen.getByRole("button", { name: "More actions for Website" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive board" }));
    const archived = await screen.findByRole("list", { name: "Archived boards" });
    expect(within(archived).getByRole("link", { name: "Website" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Board restored")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("list", { name: "Archived boards" })).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Boards" })).getByRole("button", {
          name: "More actions for Website",
        }),
      ).toHaveFocus(),
    );
    // Undo is offered for an archive only: the restore's own toast has none.
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });
});

describe("boardCountWords", () => {
  it("counts the boards a search or filter found, and names the archived among them", () => {
    expect(boardCountWords(2, 1, true)).toBe("3 boards match (1 archived).");
    expect(boardCountWords(1, 0, true)).toBe("1 board matches.");
    expect(boardCountWords(0, 0, true)).toBe("No board matches.");
    expect(boardCountWords(4, 0, false)).toBe("4 boards.");
    expect(boardCountWords(0, 0, false)).toBe("No boards yet.");
  });
});
