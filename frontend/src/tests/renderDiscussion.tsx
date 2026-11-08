import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { TicketPage } from "@/features/cards/TicketPage";
import { DiscussionPage } from "@/features/discussions/DiscussionPage";
import { LoopPage } from "@/features/loops/LoopPage";
import type { AskableAgent, Discussion, DiscussionEvent } from "@/lib/types";
import { LocationProbe } from "./LocationProbe";
import { ticketCard } from "./msw/cards";
import { runHandlers } from "./msw/discussionRuns";
import { discussion, discussionHandlers, DISCUSSION_ID, QUESTION } from "./msw/discussions";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, LOOP_ID, LOOP_PATH, planningDialogHandlers } from "./msw/loops";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";
import { createHandler } from "./msw/ticketDiscussions";
import { ticketViewHandlers } from "./msw/ticketView";

export const LOOP_URL = `/boards/${BOARD_ID}/loops/${LOOP_ID}`;
export const MODAL_URL = `${LOOP_URL}?card=card-1&discussion=${DISCUSSION_ID}`;
export const TICKET_PAGE_URL = `${LOOP_URL}/tickets/card-1`;
export const PAGE_URL = `${TICKET_PAGE_URL}/discussions/${DISCUSSION_ID}`;

/**
 * The discussion as the app shows it, over `thread` answered by `discussionHandlers`: on the Loop
 * page inside the Ticket's dialog (`MODAL_URL`), or as a page of its Ticket (`PAGE_URL`), signed in
 * as the member with the CSRF cookie set. The Ticket, its page and the Loop page are answered too,
 * so Back to the Ticket and Close can be followed; `events` is what the event history replays.
 * `ticket.agents` are the agents the board may ask; creating a discussion answers `thread` too.
 * Resolves once the question (or `ticket.heading`, when the URL opens the Ticket) is on screen.
 */
export async function renderDiscussion(
  thread: Discussion = discussion(),
  url = MODAL_URL,
  events: DiscussionEvent[] = [],
  ticket: { agents?: AskableAgent[]; heading?: string } = {},
) {
  const api = discussionHandlers(thread);
  api.state.events = events;
  const view = ticketViewHandlers(ticketCard(), { agents: ticket.agents ?? [] });
  server.use(
    createHandler(api.state),
    ...api.handlers,
    ...runHandlers(api.state),
    http.get(apiPath(`/boards/${BOARD_ID}/loop-summaries`), () =>
      ok({ board_id: BOARD_ID, loops: [], count: 0 }),
    ),
    http.get(apiPath(`${LOOP_PATH}/cards`), () => ok([])),
    http.get(apiPath(`${LOOP_PATH}/notes`), () => ok({ notes: [], count: 0 })),
    ...view.handlers,
    ...planningDialogHandlers().handlers,
  );
  document.cookie = "tralala_csrf=csrf-discussion";
  const user = userEvent.setup();
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
          <MemoryRouter initialEntries={[url]}>
            <Routes>
              <Route path="/boards/:boardId/loops/:loopId" element={<LoopPage />} />
              <Route
                path="/boards/:boardId/loops/:loopId/tickets/:cardId"
                element={<TicketPage />}
              />
              <Route
                path="/boards/:boardId/loops/:loopId/tickets/:cardId/discussions/:discussionId"
                element={<DiscussionPage />}
              />
            </Routes>
            <LocationProbe />
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: ticket.heading ?? (thread.goal || QUESTION) });
  return { api, user };
}
