import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { DiscussionsPage } from "@/features/discussions/DiscussionsPage";
import type { DiscussionInboxRow } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { LocationProbe } from "./LocationProbe";
import { inboxHandler, inboxRow } from "./msw/discussionInbox";
import { server } from "./msw/server";

const ROUTE = "/boards/board-1/loops/loop-1/tickets/card-1/discussions/wait-1";

function renderInbox(rows: DiscussionInboxRow[], total = rows.length) {
  const api = inboxHandler(rows, total);
  server.use(api.handler);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/discussions"]}>
        <Routes>
          <Route path="/discussions" element={<DiscussionsPage />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { api, user: userEvent.setup() };
}

const WAITING = inboxRow("wait-1", {
  question: "Should the agent write the assumption for a skipped question?",
  counts: { go: 2, stop: 1, unclear: 0, missing: 0 },
});
const TALKING = inboxRow("talk-1", {
  question: "Which Loops should the Memorial import first?",
  status: "discussing",
  run_state: "running",
  waits_for: "agents",
  verdict: null,
  round_count: 1,
  max_rounds: 3,
  board_name: "Memorial",
});
const DECIDED = inboxRow("done-1", {
  question: "Can we skip the audit entry when a person rewrites an assumption?",
  status: "vetoed",
  verdict: "no",
  waits_for: "nobody",
  decided_by_name: "Grace Hopper",
  last_activity_at: "2026-11-07T09:00:00Z",
});

describe("the Discussions inbox", () => {
  it("says where a discussion starts and lists the three sections in order with their counts", async () => {
    renderInbox([WAITING, TALKING, DECIDED]);

    expect(screen.getByRole("heading", { name: "Discussions", level: 1 })).toBeVisible();
    expect(
      screen.getByText(
        "Where the agents advise. You decide. A discussion starts from a Ticket: open one and choose Ask the agents.",
      ),
    ).toBeVisible();
    await screen.findByRole("list", { name: "Waits for your decision" });
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Waits for your decision 1",
      "Agents are talking 1",
      "Decided 1",
    ]);
    const decided = screen.getByRole("list", { name: "Decided" });
    expect(within(decided).getByRole("link")).toHaveTextContent(DECIDED.question);
    expect(screen.queryByRole("button", { name: /New discussion/ })).toBeNull();
  });

  it("shows a row's mark, question, the text at the right and the meta line, and opens the Ticket's discussion", async () => {
    const { user } = renderInbox([WAITING, TALKING, DECIDED]);

    const waiting = within(await screen.findByRole("list", { name: "Waits for your decision" }));
    const link = waiting.getByRole("link", { name: new RegExp(WAITING.question.slice(0, 20)) });
    expect(link).toHaveAttribute("href", ROUTE);
    expect(link).toHaveTextContent("Yes, with conditions");
    expect(link).toHaveTextContent(formatDate(WAITING.last_activity_at));
    expect(link).toHaveTextContent(
      "SES-1-PH01-001 · Session expiry · Platform · 3 agents · 2 for · 1 against · round 2 of 4",
    );

    const talking = within(screen.getByRole("list", { name: "Agents are talking" }));
    expect(talking.getByRole("link")).toHaveTextContent("Round 2 of 3");
    expect(talking.getByRole("link")).toHaveTextContent("Answering now");

    const decided = within(screen.getByRole("list", { name: "Decided" }));
    expect(decided.getByRole("link")).toHaveTextContent("No");
    expect(decided.getByRole("link")).toHaveTextContent(
      `Vetoed by Grace Hopper · ${formatDate(DECIDED.last_activity_at)}`,
    );

    await user.click(link);
    expect(screen.getByRole("status", { name: "Location" })).toHaveTextContent(ROUTE);
  });

  it("says so in a section that has no row", async () => {
    renderInbox([DECIDED]);

    await screen.findByRole("list", { name: "Decided" });
    expect(screen.getByText("Nothing waits for your decision.")).toBeInTheDocument();
    expect(screen.getByText("No agents are talking now.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Waits for your decision" })).toBeNull();
  });

  it("shows one empty state when nothing is in the inbox", async () => {
    renderInbox([]);

    expect(await screen.findByText("No discussions yet.")).toBeInTheDocument();
    expect(
      screen.getByText("When you ask the agents about a Ticket, the discussion shows up here."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Waits for your decision/ })).toBeNull();
  });

  it("says how many of all the discussions are listed when the inbox is capped", async () => {
    renderInbox([WAITING], 250);

    expect(await screen.findByText("1 of 250 discussions are listed.")).toBeInTheDocument();
  });
});
