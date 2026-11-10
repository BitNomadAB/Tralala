import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { BoardLoopsPage } from "@/features/loops/BoardLoopsPage";
import type { Board, Loop, LoopSummary } from "@/lib/types";
import { board, loop, summary } from "./msw/boards";
import { apiPath, ok } from "./msw/envelope";
import { NOW } from "./msw/loops";
import { server } from "./msw/server";

function Location() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname + location.search}</p>;
}

const PLATFORM = board("board-1", "Platform", { description: "The shared services" });

function renderBoard(shown: Board, loops: Loop[], summaries: LoopSummary[]) {
  server.use(
    http.get(apiPath("/boards/board-1"), () => ok(shown)),
    http.get(apiPath("/boards/board-1/loops"), () => ok(loops)),
    http.get(apiPath("/boards/board-1/loop-summaries"), () =>
      ok({ board_id: "board-1", loops: summaries, count: summaries.length }),
    ),
    http.get(apiPath("/agents"), () => ok([])),
    http.get(apiPath("/repositories"), () => ok([])),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/boards/board-1"]}>
          <Routes>
            <Route path="/boards/:boardId" element={<BoardLoopsPage />} />
            <Route path="*" element={<Location />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const REVIEW = loop("loop-1", "Session expiry", { stage: "roadmap_review" });
const DRAFT = loop("loop-2", "Checkout", { stage: "draft" });
const DELIVERY = loop("loop-3", "Search", {
  stage: "in_progress",
  progress: { ticket_total: 4, ticket_completed: 1, ticket_archived_incomplete: 0 },
});
const DONE = loop("loop-4", "Login", { stage: "completed", completed_at: NOW });

const SUMMARIES = [
  summary("loop-1", "Session expiry", { stage: "roadmap_review", waiting_on: "person" }),
  summary("loop-2", "Checkout"),
  summary("loop-3", "Search", {
    stage: "in_progress",
    waiting_on: "person",
    tickets: { needs_input: 1, needs_person: 1, total: 4, completed: 1 },
  }),
];

/** The list item of the Loop called `name`. */
function row(list: HTMLElement, name: string) {
  const link = within(list).getByRole("link", { name });
  return within(link.closest("li") ?? list);
}

describe("the board page", () => {
  it("shows the board's name and description, and its Loops as rows with stage and next action", async () => {
    const user = renderBoard(PLATFORM, [REVIEW, DRAFT, DELIVERY, DONE], SUMMARIES);

    expect(await screen.findByRole("heading", { name: "Platform", level: 1 })).toBeVisible();
    expect(screen.getByText("The shared services")).toBeInTheDocument();
    const current = await screen.findByRole("list", { name: "Current Loops" });
    expect(within(current).getAllByRole("listitem")).toHaveLength(3);

    const review = row(current, "Session expiry");
    expect(review.getByText("K-loop-1")).toBeInTheDocument();
    expect(review.getByText("Planning")).toBeInTheDocument();
    expect(await review.findByText("Waits for you to approve the RoadMap")).toBeInTheDocument();

    const draft = row(current, "Checkout");
    expect(draft.getByText("Draft")).toBeInTheDocument();
    expect(draft.getByText("Waits for its Info")).toBeInTheDocument();
    expect(draft.getByRole("button", { name: "Write Info: Checkout" })).toBeInTheDocument();

    const delivery = row(current, "Search");
    expect(delivery.getByText("In progress")).toBeInTheDocument();
    expect(delivery.getByText("Waits for your answer on 1 Ticket")).toBeInTheDocument();
    expect(delivery.getByText("1 of 4 Tickets done")).toBeInTheDocument();

    // The row's name opens the Loop page; the button opens it on the tab the action needs.
    expect(within(current).getByRole("link", { name: "Search" })).toHaveAttribute(
      "href",
      "/boards/board-1/loops/loop-3",
    );
    await user.click(review.getByRole("button", { name: "Approve RoadMap: Session expiry" }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/boards/board-1/loops/loop-1?tab=plan",
    );
  });

  it("folds completed Loops under a collapsed Completed (N), and the agents and repositories", async () => {
    renderBoard(PLATFORM, [DRAFT, DONE], SUMMARIES);

    const completed = (await screen.findByText("Completed (1)")).closest("details");
    expect(completed).not.toBeNull();
    expect(completed).not.toHaveAttribute("open");
    const finished = within(completed ?? document.body).getByRole("list", {
      name: "Completed Loops",
    });
    const done = row(finished, "Login");
    expect(done.getByText("Completed")).toBeInTheDocument();
    expect(done.queryByRole("button")).toBeNull();

    const context = screen.getByText("Agents and repositories").closest("details");
    expect(context).not.toHaveAttribute("open");
    expect(within(context ?? document.body).getByText("any enabled agent")).toBeInTheDocument();
  });

  it("opens today's New Loop dialog from the primary button", async () => {
    const user = renderBoard(PLATFORM, [DRAFT], SUMMARIES);

    await user.click(await screen.findByRole("button", { name: "New Loop" }));
    const dialog = await screen.findByRole("dialog", { name: "New Loop" });
    expect(within(dialog).getByLabelText("Name")).toBeInTheDocument();
    // The name only: the goal is written into Info on the Loop's page.
    expect(within(dialog).queryByLabelText("Broad goal")).toBeNull();
    expect(within(dialog).getByText(/Its goal goes into Info/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Create Loop" })).toBeDisabled();
  });

  it("says a board without Loops has none yet, with New Loop beside it", async () => {
    const user = renderBoard(PLATFORM, [], []);

    expect(
      await screen.findByText("No Loops yet. A Loop starts with its Info: what you want and why."),
    ).toBeInTheDocument();
    // The empty list carries the page's one New Loop.
    expect(screen.getAllByRole("button", { name: "New Loop" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "New Loop" }));
    expect(await screen.findByRole("dialog", { name: "New Loop" })).toBeInTheDocument();
  });

  it("marks an archived board read only: no next action, no New Loop, Delete in the menu", async () => {
    const user = renderBoard(
      board("board-1", "Platform", { status: "archived" }),
      [REVIEW],
      SUMMARIES,
    );

    expect(await screen.findByText("Read only")).toBeInTheDocument();
    const current = await screen.findByRole("list", { name: "Current Loops" });
    expect(
      await row(current, "Session expiry").findByText("Waits for you to approve the RoadMap"),
    ).toBeInTheDocument();
    expect(within(current).queryByRole("button")).toBeNull();
    expect(screen.getByRole("button", { name: "New Loop" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Board actions" }));
    const menu = screen.getByRole("menu", { name: "Board actions" });
    for (const item of ["Edit board", "Board templates", "Board history", "Restore board"]) {
      expect(within(menu).getByRole("menuitem", { name: item })).toBeInTheDocument();
    }
    expect(within(menu).getByRole("menuitem", { name: "Delete board" })).not.toHaveAttribute(
      "aria-disabled",
    );
    await user.click(within(menu).getByRole("menuitem", { name: "Delete board" }));
    expect(await screen.findByRole("dialog", { name: "Delete board permanently" })).toBeVisible();
  });
});
