import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, type HttpHandler } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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
import { ticketViewHandlers } from "./msw/ticketView";

export const PAGE_URL = `/boards/${BOARD_ID}/loops/${LOOP_ID}`;
export const TITLE = "Rotate the signing key";

/**
 * The Loop page signed in as the member, at `query`, over a Loop at `stage` whose row of the
 * board's Loop summaries is `row`. The Ticket of `ticketViewHandlers` sits in the first column;
 * `writes` collects every PATCH or POST on the Loop itself. `extra` handlers answer before all of
 * these (a Kanban of its own, `kanbanHandlers`).
 */
export async function renderLoopPage(
  query: string,
  stage: Loop["stage"],
  row: NonNullable<Parameters<typeof summary>[2]>,
  extra: readonly HttpHandler[] = [],
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
  server.use(...extra);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
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

/** The location probe's query string. */
export const query = () => screen.getByRole("status", { name: "Query" });
