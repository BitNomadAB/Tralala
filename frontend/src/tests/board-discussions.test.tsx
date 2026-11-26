import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { BoardLoopsPage } from "@/features/loops/BoardLoopsPage";
import type { Board, Discussion } from "@/lib/types";
import { LocationProbe } from "./LocationProbe";
import { boardDiscussionHandlers, boardThread } from "./msw/boardDiscussions";
import { board, loop } from "./msw/boards";
import { runHandlers } from "./msw/discussionRuns";
import { discussionHandlers, DISCUSSION_ID } from "./msw/discussions";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";
import { ASKABLE } from "./msw/ticketDiscussions";

const PLATFORM = board("board-1", "Platform");
const NEW_URL = `/boards/board-1/discussions/${DISCUSSION_ID}`;

function thread(id: string, title: string, minute: number, extra: Partial<Discussion> = {}) {
  const at = `2026-11-08T11:${String(minute).padStart(2, "0")}:00Z`;
  return boardThread({ id, title, last_activity_at: at, updated_at: at, ...extra });
}

function renderBoard(
  threads: Discussion[],
  options: { shown?: Board; answer?: Discussion | null } = {},
) {
  const list = boardDiscussionHandlers(
    threads,
    options.answer === undefined ? boardThread() : options.answer,
  );
  const runs = discussionHandlers(boardThread());
  server.use(
    http.get(apiPath("/boards/board-1"), () => ok(options.shown ?? PLATFORM)),
    http.get(apiPath("/boards/board-1/loops"), () => ok([loop("loop-1", "Session expiry")])),
    http.get(apiPath("/boards/board-1/loop-summaries"), () =>
      ok({ board_id: "board-1", loops: [], count: 0 }),
    ),
    http.get(apiPath("/boards/board-1/actors"), () => ok({ people: [], agents: ASKABLE })),
    http.get(apiPath("/agents"), () => ok([])),
    http.get(apiPath("/repositories"), () => ok([])),
    ...list.handlers,
    ...runHandlers(runs.state),
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
            <Route path="*" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { list, runs, user: userEvent.setup() };
}

async function discussions() {
  return screen.findByRole("region", { name: "Discussions" });
}

describe("the board's discussions", () => {
  it("lists the board's own discussions after the Loops, newest activity first, marking the unread", async () => {
    const { list } = renderBoard([
      thread("d-old", "Old question", 1),
      thread("d-new", "New question", 9, { unread: true }),
    ]);
    const part = within(await discussions());
    const rows = await part.findAllByRole("link");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("New question"),
      expect.stringContaining("Old question"),
    ]);
    expect(rows[0]).toHaveAccessibleName(/^Unread /);
    expect(rows[1]).not.toHaveTextContent("Unread");
    expect(rows[0]).toHaveAttribute("href", "/boards/board-1/discussions/d-new");
    expect(rows[0]).toHaveTextContent("Asked by Ada Member · 4 agents · 6 messages");
    expect(await screen.findByRole("list", { name: "Current Loops" })).toBeInTheDocument();
    const query = list.state.queries[0];
    expect(query?.get("scope")).toBe("board");
    expect(query?.get("state")).toBe("open");
  });

  it("shows the closed discussions under Closed, and says so when a filter has none", async () => {
    const { list, user } = renderBoard([
      thread("d-shut", "Shut question", 3, { status: "closed" }),
    ]);
    const part = within(await discussions());
    expect(
      await part.findByText("No open discussion on this board. Start one with New discussion."),
    ).toBeInTheDocument();
    await user.click(part.getByRole("tab", { name: "Closed" }));
    const link = await part.findByRole("link", { name: /Shut question/ });
    expect(link).toHaveTextContent("Closed");
    expect(part.getByRole("tab", { name: "Closed" })).toHaveAttribute("aria-selected", "true");
    expect(list.state.queries.at(-1)?.get("state")).toBe("closed");
  });

  it("asks for the title and the question before it starts a discussion", async () => {
    const { list, user } = renderBoard([]);
    await user.click(await screen.findByRole("button", { name: "New discussion" }));
    const dialog = await screen.findByRole("dialog", { name: "New discussion" });
    const chips = await within(dialog).findAllByRole("checkbox");
    expect(chips).toHaveLength(3);
    for (const chip of chips) expect(chip).not.toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Start discussion" }));
    const title = within(dialog).getByRole("textbox", { name: "Title" });
    expect(title).toHaveAccessibleDescription("Error: Write a title.");
    expect(title).toHaveFocus();
    expect(within(dialog).getByRole("textbox", { name: "Question" })).toHaveAccessibleDescription(
      "Error: Write the question.",
    );
    await user.type(title, "Export");
    await user.click(within(dialog).getByRole("button", { name: "Start discussion" }));
    expect(within(dialog).getByRole("textbox", { name: "Question" })).toHaveFocus();
    expect(list.state.created).toHaveLength(0);
  });

  it("starts a question to nobody in particular without agents, and opens it", async () => {
    const { list, runs, user } = renderBoard([]);
    await user.click(await screen.findByRole("button", { name: "New discussion" }));
    const dialog = await screen.findByRole("dialog", { name: "New discussion" });
    await user.type(within(dialog).getByRole("textbox", { name: "Title" }), "  Export  ");
    await user.type(within(dialog).getByRole("textbox", { name: "Question" }), "Where?");
    await user.click(within(dialog).getByRole("button", { name: "Start discussion" }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "Location" })).toHaveTextContent(NEW_URL),
    );
    expect(list.state.created).toEqual([
      { title: "Export", goal: "Where?", mode: "manual", participant_ids: [] },
    ]);
    expect(runs.state.bodies.filter((entry) => entry.route === "start")).toHaveLength(0);
  });

  it("starts one round in the background with the agents chosen, and opens it", async () => {
    const { list, runs, user } = renderBoard([]);
    await user.click(await screen.findByRole("button", { name: "New discussion" }));
    const dialog = await screen.findByRole("dialog", { name: "New discussion" });
    await user.type(within(dialog).getByRole("textbox", { name: "Title" }), "Export");
    await user.type(within(dialog).getByRole("textbox", { name: "Question" }), "Where?");
    await user.click(await within(dialog).findByRole("checkbox", { name: /^Bravo/ }));
    await user.click(within(dialog).getByRole("button", { name: "Start discussion" }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "Location" })).toHaveTextContent(NEW_URL),
    );
    expect(list.state.created).toEqual([
      { title: "Export", goal: "Where?", mode: "roundtable", participant_ids: ["agent-Bravo"] },
    ]);
    const starts = runs.state.bodies.filter((entry) => entry.route === "start");
    expect(starts.map((entry) => entry.body)).toEqual([{ rounds: 1, background: true }]);
  });

  it("shows the server's refusal of the title under the field", async () => {
    const { user } = renderBoard([], { answer: null });
    await user.click(await screen.findByRole("button", { name: "New discussion" }));
    const dialog = await screen.findByRole("dialog", { name: "New discussion" });
    const title = within(dialog).getByRole("textbox", { name: "Title" });
    await user.type(title, "x");
    await user.type(within(dialog).getByRole("textbox", { name: "Question" }), "Where?");
    await user.click(within(dialog).getByRole("button", { name: "Start discussion" }));
    await waitFor(() =>
      expect(title).toHaveAccessibleDescription("Error: A discussion on the board needs a title."),
    );
    expect(title).toHaveFocus();
    expect(screen.getByRole("dialog", { name: "New discussion" })).toBeInTheDocument();
  });

  it("keeps the list readable on an archived board, without New discussion", async () => {
    renderBoard([thread("d-1", "Kept question", 2)], {
      shown: board("board-1", "Platform", { status: "archived" }),
    });
    const part = within(await discussions());
    expect(await part.findByRole("link", { name: /Kept question/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New discussion" })).toBeNull();
  });
});
