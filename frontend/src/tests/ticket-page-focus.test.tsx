import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useRouteFocus } from "@/app/useRouteFocus";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { TicketPage } from "@/features/cards/TicketPage";
import { CARD_PATH, ticketCard } from "./msw/cards";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";
import { ticketViewHandlers } from "./msw/ticketView";
import { TICKET_URL } from "./renderTicket";

function RouteFocus() {
  useRouteFocus();
  return null;
}

/** The Ticket's page behind a link, with route focus, and its card held until `release`. */
function renderPage() {
  const card = ticketCard();
  const view = ticketViewHandlers(card);
  let release: () => void = () => undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(...view.handlers);
  server.use(
    http.get(apiPath(CARD_PATH), async () => {
      await held;
      return ok(view.state.card);
    }),
  );
  const auth = {
    actor: MEMBER,
    loading: false,
    login: () => Promise.resolve(MEMBER),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(MEMBER),
    addressForgotten: false,
    signOutLocally: () => undefined,
  };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/"]}>
            <RouteFocus />
            <main id="main">
              <Routes>
                <Route path="/" element={<Link to={TICKET_URL}>Open the Ticket</Link>} />
                <Route
                  path="/boards/:boardId/loops/:loopId/tickets/:cardId"
                  element={<TicketPage />}
                />
              </Routes>
            </main>
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return { card, release, user: userEvent.setup() };
}

describe("the Ticket's page after a navigation", () => {
  it("gives the Ticket's title the focus once the Ticket has loaded", async () => {
    const { card, release, user } = renderPage();
    await user.click(screen.getByRole("link", { name: "Open the Ticket" }));
    expect(await screen.findByText("Loading Ticket…")).toBeInTheDocument();
    // The loading heading only keeps the page's outline; the focus waits for the real one.
    expect(screen.getByRole("main")).toHaveFocus();

    await act(async () => {
      release();
      await Promise.resolve();
    });

    const title = await screen.findByRole("heading", { level: 1, name: card.title });
    await waitFor(() => expect(title).toHaveFocus());
  });
});
