import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { TicketModal } from "@/features/cards/TicketModal";
import { TicketPage } from "@/features/cards/TicketPage";
import type { CardDetail } from "@/lib/types";
import { LocationProbe } from "./LocationProbe";
import { CARD_ID, ticketCard } from "./msw/cards";
import { BOARD_ID, LOOP_ID } from "./msw/loops";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";
import { ticketViewHandlers } from "./msw/ticketView";

export const LOOP_URL = `/boards/${BOARD_ID}/loops/${LOOP_ID}`;
export const TICKET_URL = `${LOOP_URL}/tickets/${CARD_ID}`;
export const CSRF = "csrf-ticket";

/**
 * The Ticket as the app shows it, over `card` answered by `ticketViewHandlers`: the dialog on the
 * Loop page (or, from `TICKET_URL`, the Ticket's page), signed in as the member, with the CSRF
 * cookie set so every write carries the header. Resolves once the title is on screen.
 */
export async function renderTicket(card: CardDetail = ticketCard(), url = LOOP_URL) {
  const view = ticketViewHandlers(card);
  server.use(...view.handlers);
  document.cookie = `tralala_csrf=${CSRF}`;
  const user = userEvent.setup();
  const onClose = vi.fn();
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
              <Route
                path="/boards/:boardId/loops/:loopId"
                element={
                  <TicketModal
                    boardId={BOARD_ID}
                    loopId={LOOP_ID}
                    cardId={CARD_ID}
                    onClose={onClose}
                  />
                }
              />
              <Route
                path="/boards/:boardId/loops/:loopId/tickets/:cardId"
                element={<TicketPage />}
              />
            </Routes>
            <LocationProbe />
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: card.title });
  return { view, user, onClose };
}

/** Every write the view sent, as "METHOD /path" with its body. */
export function writes(view: ReturnType<typeof ticketViewHandlers>) {
  return view.state.bodies;
}
