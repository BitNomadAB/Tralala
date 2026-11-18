import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { HistoryPage } from "@/features/history/HistoryPage";
import type { HistorySummary } from "@/lib/types";
import { announcer } from "./announcer";
import { board } from "./msw/boards";
import { apiPath, ok } from "./msw/envelope";
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
  };
}

const RECORDS = [record("h-1", "Checkout"), record("h-2", "Session expiry")];

/** The history of board-1; the server finds records by the words of their Loop's name. */
function renderHistory() {
  server.use(
    http.get(apiPath("/boards/:boardId"), () => ok(board("board-1", "Platform"))),
    http.get(apiPath("/boards/:boardId/history"), ({ request }) => {
      const q = (new URL(request.url).searchParams.get("q") ?? "").toLowerCase();
      const items = RECORDS.filter((entry) => entry.loop_name.toLowerCase().includes(q));
      return ok(items, { total: items.length, limit: 50, offset: 0, has_more: false });
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
});
