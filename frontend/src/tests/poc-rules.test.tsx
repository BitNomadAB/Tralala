import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { waitingRows } from "@/features/boards/boardSummaries";
import { DashboardPage } from "@/features/boards/DashboardPage";
import {
  dueNotice,
  missingNotice,
  pocAction,
  pocGroups,
  signLines,
  unansweredLine,
  waitingLine,
} from "@/features/loops/pocDecisions";
import { stopLines } from "@/features/loops/stopList";
import type { PocCounts } from "@/lib/types";
import { board, dashboardHandlers, summary } from "./msw/boards";
import { pocDecision } from "./msw/poc";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";

const NONE: PocCounts = { open: 0, built_on_open: 0, missing_open: 0, due: 0, answered: 0 };

describe("the Decisions tab's groups", () => {
  const plain = pocDecision(1);
  const missing = pocDecision(2, { kind: "missing" });
  const builtOn = pocDecision(3, { built_on: true });
  const answered = pocDecision(4, { status: "ok" });
  const later = pocDecision(5);

  it("follow the review order and leave out an empty group", () => {
    const groups = pocGroups([builtOn, missing, plain, later, answered]);
    expect(groups.map((group) => [group.title, group.items.map((item) => item.id)])).toEqual([
      ["Other work builds on these", ["poc-3"]],
      ["Missing from a person", ["poc-2"]],
      ["Other decisions", ["poc-1", "poc-5"]],
      ["Answered", ["poc-4"]],
    ]);
    expect(pocGroups([plain]).map((group) => group.id)).toEqual(["other"]);
  });

  it("keep a record answered on this visit in its group, in its place", () => {
    const answeredPlain = { ...plain, status: "ok" as const };
    const groups = pocGroups([later, answered, answeredPlain], new Map([["poc-1", "other"]]));
    expect(groups.map((group) => [group.id, group.items.map((item) => item.id)])).toEqual([
      ["other", ["poc-1", "poc-5"]],
      ["answered", ["poc-4"]],
    ]);
  });
});

describe("the words", () => {
  it("count what waits", () => {
    expect(waitingLine(0)).toBe("Nothing waits for an answer.");
    expect(waitingLine(1)).toBe("1 waits for an answer.");
    expect(dueNotice(1, 1)).toBe("1 POC decision waits for your review; other work builds on it.");
    expect(dueNotice(3, 3)).toBe(
      "3 POC decisions wait for your review; other work builds on all of them.",
    );
    expect(dueNotice(3, 0)).toBe("3 POC decisions wait for your review.");
    expect(missingNotice(2)).toBe("2 things are missing from a person.");
    expect(unansweredLine(1)).toBe(
      "1 POC decision is not answered. It cannot be answered once the Loop is closed.",
    );
  });

  it("leave an empty part out of the sign", () => {
    const item = pocDecision(1, { alternative: "", builds_on: "The report." });
    expect(signLines(item).map((line) => line.label)).toEqual([
      "Chosen",
      "Why",
      "To change it",
      "Builds on it",
    ]);
  });

  it("read a stop list one line a stop", () => {
    expect(stopLines("Money\r\n\n  Deleting data \n")).toEqual(["Money", "Deleting data"]);
    expect(stopLines("  \n")).toEqual([]);
  });
});

describe("Waits for you on the dashboard", () => {
  const active = board("b1", "Platform");
  const due = summary("l1", "Session expiry", {
    stage: "in_progress",
    waiting_on: "anyone",
    tickets: { ready: 1, total: 1 },
    poc_decisions: { ...NONE, open: 2, due: 2 },
  });
  const missing = summary("l2", "Mail", {
    stage: "in_progress",
    waiting_on: "anyone",
    tickets: { ready: 1, total: 1 },
    poc_decisions: { ...NONE, open: 1, missing_open: 1 },
  });

  it("gain a row for a Loop with decisions due or something missing, to its Decisions tab", () => {
    const rows = waitingRows(
      [active],
      new Map([["b1", { loops: [due, missing], pending: false, failed: false }]]),
    );
    expect(rows.map((row) => [row.loop.id, row.kind, row.action.waiting, row.action.tab])).toEqual([
      ["l1", "poc", "2 POC decisions wait for your review.", "decisions"],
      ["l2", "poc", "1 thing is missing from a person.", "decisions"],
    ]);
    expect(pocAction(summary("l3", "Quiet", { poc_decisions: { ...NONE, open: 4 } }))).toBeNull();
    // An archived board decides nothing.
    const archived = board("b2", "Old", { status: "archived" });
    expect(
      waitingRows([archived], new Map([["b2", { loops: [due], pending: false, failed: false }]])),
    ).toEqual([]);
  });

  it("lists the row with its way to the Decisions tab", async () => {
    server.use(...dashboardHandlers([active], { b1: [missing] }).handlers);
    const auth = {
      actor: MEMBER,
      loading: false,
      login: () => Promise.resolve(MEMBER),
      logout: () => Promise.resolve(),
      refresh: () => Promise.resolve(MEMBER),
      addressForgotten: false,
      signOutLocally: () => undefined,
    };
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <AuthContext.Provider value={auth}>
          <ToastProvider>
            <MemoryRouter>
              <DashboardPage />
            </MemoryRouter>
          </ToastProvider>
        </AuthContext.Provider>
      </QueryClientProvider>,
    );
    const list = await screen.findByRole("list", { name: "Waits for you" });
    expect(within(list).getByText("1 thing is missing from a person.")).toBeInTheDocument();
    expect(within(list).getByRole("link", { name: "Review decisions: Mail" })).toHaveAttribute(
      "href",
      "/boards/b1/loops/l2?tab=decisions",
    );
  });
});
