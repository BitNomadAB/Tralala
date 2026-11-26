import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { HistoryPage } from "@/features/history/HistoryPage";
import type { HistoryDetail, HistorySummary } from "@/lib/types";
import { announcer } from "./announcer";
import { board } from "./msw/boards";
import { apiPath, failure, ok } from "./msw/envelope";
import { server } from "./msw/server";

function record(id: string, loopName: string): HistorySummary {
  return {
    id,
    source_kind: "native",
    conformance: "native",
    board_id: "board-1",
    loop_id: id,
    loop_key: null,
    loop_name: loopName,
    qa_status: "accepted",
    completed_at: "2026-11-01T09:00:00Z",
    imported_at: null,
    created_at: "2026-11-01T09:00:00Z",
    content_hash: "a".repeat(64),
    warnings: [],
    label: "",
    without_plan: false,
  };
}

const RECORDS = [record("h-1", "Checkout"), record("h-2", "Session expiry")];

/** A Loop closed without a plan: one decision, no QA. */
const FAST: HistorySummary = {
  ...record("h-3", "Small fixes"),
  loop_key: "SN008",
  qa_status: "not_run",
  without_plan: true,
};

/** A record whose decisions a coding session asked for: a review, a wait, and the implementation. */
const ASKED: HistorySummary = { ...record("h-4", "Asked decisions"), loop_key: "BE007" };
const LAPTOP = { credential_id: "cred-1", key_name: "Laptop", via: "link" };
const ASKED_ENVELOPE: Record<string, unknown> = {
  activity: [
    {
      action: "loop.analysis_reviewed",
      changes: { decision: "approved", approval_id: "a-1", asked_through: [LAPTOP] },
    },
    { action: "loop.roadmap_reviewed", changes: { decision: "approved", approval_id: "a-2" } },
    {
      action: "card.wait_cleared",
      changes: {
        asked_through: [LAPTOP, { credential_id: "cred-2", key_name: "Desktop", via: "link" }],
      },
    },
  ],
  approvals: [
    {
      scope: "implementation",
      decision: "approved",
      revisions: { qa_status: "passed", asked_through: [LAPTOP] },
    },
  ],
};

/** The history of board-1; the server finds records by the words of their Loop's name. */
function renderHistory(records: HistorySummary[] = RECORDS) {
  server.use(
    http.get(apiPath("/boards/:boardId"), () => ok(board("board-1", "Platform"))),
    http.get(apiPath("/boards/:boardId/history"), ({ request }) => {
      const q = (new URL(request.url).searchParams.get("q") ?? "").toLowerCase();
      const items = records.filter((entry) => entry.loop_name.toLowerCase().includes(q));
      return ok(items, { total: items.length, limit: 50, offset: 0, has_more: false });
    }),
    http.get(apiPath("/boards/:boardId/history/:historyId"), ({ params }) => {
      const found = records.find((entry) => entry.id === params.historyId);
      const envelope = found?.id === ASKED.id ? ASKED_ENVELOPE : {};
      const detail: HistoryDetail | undefined = found && { ...found, envelope, artifacts: [] };
      return detail ? ok(detail) : failure(404, "history_not_found", "No such record");
    }),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/boards/board-1/history"]}>
          <Routes>
            <Route path="/boards/:boardId/history" element={<HistoryPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe("the board history", () => {
  it("counts the records in words, and says the count again after each search", async () => {
    const user = renderHistory();
    expect(await screen.findByText(/^2 records ·/)).toBeInTheDocument();
    // What the page opens with is shown, not announced.
    expect(announcer()).toBeEmptyDOMElement();

    await user.type(screen.getByRole("textbox", { name: "Search history" }), "check");
    await waitFor(() => expect(announcer()).toHaveTextContent("1 record."));
    expect(screen.getByText(/^1 record ·/)).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Search history" }), "zzz");
    await waitFor(() =>
      expect(announcer()).toHaveTextContent("No historical records match this search."),
    );
  });

  it("marks a Loop closed without a plan in place of a QA result, in the list and the record", async () => {
    const user = renderHistory([...RECORDS, FAST]);
    const fast = (await screen.findByText("Small fixes")).closest("button");
    const planned = screen.getByText("Checkout").closest("button");
    if (!fast || !planned) throw new Error("a record is not a button");
    expect(within(fast).getByText("Closed without a plan")).toBeInTheDocument();
    expect(within(fast).queryByText(/^QA /)).toBeNull();
    // A record of a Loop with a plan still says its QA result.
    expect(within(planned).getByText("QA accepted")).toBeInTheDocument();
    expect(within(planned).queryByText("Closed without a plan")).toBeNull();

    await user.click(fast);
    const dialog = await screen.findByRole("dialog", { name: "Small fixes" });
    expect(await within(dialog).findByText("Closed without a plan")).toBeInTheDocument();
    expect(within(dialog).getByText("SN008")).toBeInTheDocument();
    expect(within(dialog).queryByText(/^QA /)).toBeNull();
  });

  it("shows the QA result in the record of a Loop with a plan", async () => {
    const user = renderHistory();
    const planned = (await screen.findByText("Checkout")).closest("button");
    if (!planned) throw new Error("the record is not a button");
    await user.click(planned);
    const dialog = await screen.findByRole("dialog", { name: "Checkout" });
    expect(await within(dialog).findByText("QA accepted")).toBeInTheDocument();
    expect(within(dialog).queryByText("Closed without a plan")).toBeNull();
  });

  it("names the decisions a coding session asked for, and through which keys", async () => {
    const user = renderHistory([...RECORDS, ASKED]);
    const asked = (await screen.findByText("Asked decisions")).closest("button");
    if (!asked) throw new Error("the record is not a button");
    await user.click(asked);
    const dialog = await screen.findByRole("dialog", { name: "Asked decisions" });
    const list = await within(dialog).findByRole("list", {
      name: "Decisions asked from a coding session",
    });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Approved the analysis, asked from a coding session through the key Laptop",
      "Cleared a wait, asked from a coding session through the keys Laptop and Desktop",
      "Accepted the implementation, asked from a coding session through the key Laptop",
    ]);
  });

  it("lists no asked decisions in a record without any", async () => {
    const user = renderHistory();
    const planned = (await screen.findByText("Checkout")).closest("button");
    if (!planned) throw new Error("the record is not a button");
    await user.click(planned);
    const dialog = await screen.findByRole("dialog", { name: "Checkout" });
    expect(await within(dialog).findByText("QA accepted")).toBeInTheDocument();
    expect(within(dialog).queryByText("Decisions asked from a coding session")).toBeNull();
  });
});
