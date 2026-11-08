import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { LoopPage } from "@/features/loops/LoopPage";
import type { Loop } from "@/lib/types";
import { LocationProbe } from "./LocationProbe";
import { summary } from "./msw/boards";
import { ticketCard } from "./msw/cards";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, LOOP, LOOP_ID, LOOP_PATH, planningDialogHandlers } from "./msw/loops";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";
import { PHASE_NAME, ticketViewHandlers } from "./msw/ticketView";

const PAGE_URL = `/boards/${BOARD_ID}/loops/${LOOP_ID}`;
const TITLE = "Rotate the signing key";

/**
 * The Loop page signed in as the member, at `query`, over a Loop at `stage` whose row of the
 * board's Loop summaries is `row`. The Ticket of `ticketViewHandlers` sits in the first column;
 * `writes` collects every PATCH or POST on the Loop itself.
 */
async function renderLoopPage(
  query: string,
  stage: Loop["stage"],
  row: NonNullable<Parameters<typeof summary>[2]>,
) {
  const view = ticketViewHandlers(ticketCard({ summary: "The key is rotated every 90 days." }));
  const writes: { route: string; body: unknown }[] = [];
  const loopRow = summary(LOOP_ID, LOOP.name, { key: LOOP.key, stage, ...row });
  server.use(
    http.get(apiPath(LOOP_PATH), () => ok({ ...LOOP, stage })),
    http.patch(apiPath(LOOP_PATH), async ({ request }) => {
      writes.push({ route: `PATCH ${LOOP_PATH}`, body: await request.json() });
      return ok({ ...LOOP, stage, name: "Session limits" });
    }),
    http.post(apiPath(`${LOOP_PATH}/cancel`), async ({ request }) => {
      writes.push({ route: `POST ${LOOP_PATH}/cancel`, body: await request.json() });
      return ok({ ...LOOP, stage: "cancelled" });
    }),
    http.get(apiPath(`/boards/${BOARD_ID}/loop-summaries`), () =>
      ok({ board_id: BOARD_ID, loops: [loopRow], count: 1 }),
    ),
    http.get(apiPath(`${LOOP_PATH}/cards`), ({ request }) =>
      ok(new URL(request.url).searchParams.get("list_id") === "list-1" ? [view.state.card] : []),
    ),
    http.get(apiPath(`${LOOP_PATH}/notes`), () => ok({ notes: [], count: 0 })),
    ...view.handlers,
    ...planningDialogHandlers().handlers,
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const auth = {
    actor: MEMBER,
    loading: false,
    login: () => Promise.resolve(MEMBER),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(MEMBER),
    signOutLocally: () => undefined,
  };
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <ToastProvider>
          <MemoryRouter initialEntries={[`${PAGE_URL}${query}`]}>
            <Routes>
              <Route path="/boards/:boardId/loops/:loopId" element={<LoopPage />} />
            </Routes>
            <LocationProbe />
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  // Hidden from the accessibility tree while a Ticket is open over the page.
  const title = await screen.findByRole("heading", { level: 1, name: LOOP.name, hidden: true });
  const header = title.closest("header");
  if (!header) throw new Error("the Loop's title is not in its header");
  return { header, writes, user: userEvent.setup() };
}

const query = () => screen.getByRole("status", { name: "Query" });

describe("the Loop page's header", () => {
  it("shows the key, the stage, what it waits for and the one decision", async () => {
    const { header, user } = await renderLoopPage("", "analysis_review", {});
    expect(within(header).getByText("SES-1")).toHaveClass("font-mono");
    expect(within(header).getByText("Analysis review")).toBeInTheDocument();
    expect(
      await within(header).findByText("Waits for you to approve the analysis"),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Kanban" })).toHaveAttribute("aria-selected", "true");

    // The approval binds to the text on screen, so the header opens the analysis to decide on.
    await user.click(within(header).getByRole("button", { name: "Approve analysis" }));
    expect(query()).toHaveTextContent("?tab=plan&doc=analysis");
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    const documents = await screen.findByRole("region", { name: "Planning documents" });
    const approve = await within(documents).findByRole("button", { name: "Approve analysis" });
    expect(screen.getAllByRole("button", { name: "Approve analysis" })).toEqual([approve]);
  });

  it("offers no decision when the next step is not the person's, only the quiet menu", async () => {
    const { header } = await renderLoopPage("", "in_progress", { tickets: { ready: 1 } });
    expect(await within(header).findByText("1 Ticket ready to start")).toBeInTheDocument();
    expect(
      within(header)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([""]);
    expect(within(header).getByRole("button", { name: "Loop actions" })).toBeInTheDocument();
  });

  it("edits the Loop's name against its version from the menu", async () => {
    const { header, writes, user } = await renderLoopPage("", "in_progress", {});
    await user.click(within(header).getByRole("button", { name: "Loop actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit Loop" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Loop" });
    const name = within(dialog).getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Session limits");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(writes).toEqual([
        { route: `PATCH ${LOOP_PATH}`, body: { version: 1, name: "Session limits", goal: "" } },
      ]);
    });
    expect(screen.queryByRole("dialog", { name: "Edit Loop" })).not.toBeInTheDocument();
  });

  it("asks before it cancels the Loop", async () => {
    const { header, writes, user } = await renderLoopPage("", "in_progress", {});
    await user.click(within(header).getByRole("button", { name: "Loop actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel Loop" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel Loop" });
    expect(writes).toEqual([]);
    await user.type(within(dialog).getByLabelText("Why (optional)"), "Replaced by SES-2");
    await user.click(within(dialog).getByRole("button", { name: "Cancel Loop" }));
    await waitFor(() => {
      expect(writes).toEqual([
        {
          route: `POST ${LOOP_PATH}/cancel`,
          body: { version: 1, reason: "Replaced by SES-2" },
        },
      ]);
    });
  });
});

describe("the Loop page's tabs", () => {
  it("switch between Kanban, Plan and Notes and keep the tab in the URL", async () => {
    const { user } = await renderLoopPage("", "in_progress", {});
    const backlog = await screen.findByRole("region", { name: "List Backlog" });
    expect(await within(backlog).findByText("The key is rotated every 90 days.")).toBeVisible();
    expect(query()).toHaveTextContent("");

    await user.click(screen.getByRole("tab", { name: "Notes" }));
    expect(query()).toHaveTextContent("?tab=notes");
    expect(await screen.findByText("No notes yet.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "List Backlog" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Kanban" }));
    expect(query()).toBeEmptyDOMElement();
    expect(screen.getByRole("region", { name: "List Backlog" })).toBeInTheDocument();
  });

  it("land on the Plan tab from a link, with the documents and the readiness", async () => {
    await renderLoopPage("?tab=plan", "in_progress", {});
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    const documents = screen.getByRole("region", { name: "Planning documents" });
    for (const name of ["Info", "Analysis", "RoadMap"]) {
      expect(within(documents).getByRole("button", { name })).toBeInTheDocument();
    }
    // A Loop in delivery opens its RoadMap.
    expect(
      await within(documents).findByRole("button", { name: /Generate RoadMap/ }),
    ).toBeInTheDocument();
    const readiness = screen.getByRole("region", { name: "Phases and readiness" });
    expect(await within(readiness).findByText(PHASE_NAME)).toBeInTheDocument();
  });

  it("open a Ticket over the Plan tab and close it back to the Plan tab", async () => {
    const { user } = await renderLoopPage("?tab=plan&card=card-1", "in_progress", {});
    const dialog = await screen.findByRole("dialog", { name: TITLE });
    expect(screen.getByRole("tab", { name: "Plan", hidden: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(query()).toHaveTextContent("?tab=plan");
    expect(query()).not.toHaveTextContent("card");
  });
});
