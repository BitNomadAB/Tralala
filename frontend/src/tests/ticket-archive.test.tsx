import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { afterArchiveTarget, focusRestoredCard } from "@/features/cards/archiveFocus";
import { TicketModal } from "@/features/cards/TicketModal";
import { CARD_ID, CARD_PATH, ticketCard } from "./msw/cards";
import { BOARD_ID, LOOP_ID } from "./msw/loops";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";
import { ticketViewHandlers } from "./msw/ticketView";

const TITLE = "Rotate the signing key";

/** A column of the Kanban with the Ticket's card, and the Ticket's dialog over it until it closes. */
function Board() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <section aria-label="Column Backlog">
        <button type="button" data-ticket-open={CARD_ID}>
          {TITLE}
        </button>
        <button type="button">Add card</button>
      </section>
      {open ? (
        <TicketModal
          boardId={BOARD_ID}
          loopId={LOOP_ID}
          cardId={CARD_ID}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

async function renderBoard() {
  const view = ticketViewHandlers(ticketCard());
  server.use(...view.handlers);
  document.cookie = "tralala_csrf=csrf-archive";
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
          <MemoryRouter>
            <Board />
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { level: 2, name: TITLE });
  return { view, user: userEvent.setup() };
}

async function archiveFromMore(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "More actions" }));
  const menu = screen.getByRole("list", { name: "More actions" });
  await user.click(within(menu).getByRole("button", { name: "Archive" }));
}

describe("archiving a Ticket", () => {
  it("closes, says so with Undo, and Undo restores the Ticket", async () => {
    const { view, user } = await renderBoard();
    await archiveFromMore(user);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Ticket archived")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Ticket restored")).toBeInTheDocument();
    expect(view.state.bodies).toEqual([
      { route: `POST ${CARD_PATH}/archive`, body: null },
      { route: `POST ${CARD_PATH}/restore`, body: null },
    ]);
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("gives the focus to the column's Add card, since the card leaves the board", async () => {
    const { user } = await renderBoard();
    await archiveFromMore(user);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(screen.getByRole("button", { name: "Add card" })).toHaveFocus());
  });

  it("falls back to the page's main region, and to nothing without one", () => {
    expect(afterArchiveTarget(CARD_ID)).toBeNull();
    const { unmount } = render(
      <main id="main" tabIndex={-1}>
        Board
      </main>,
    );
    expect(afterArchiveTarget(CARD_ID)).toBe(screen.getByRole("main"));
    unmount();
  });

  it("gives the restored card's title the focus once it is back, unless the focus is elsewhere", async () => {
    render(
      <>
        <button type="button" data-ticket-open={CARD_ID}>
          {TITLE}
        </button>
        <button type="button">Elsewhere</button>
      </>,
    );
    focusRestoredCard(CARD_ID);
    await waitFor(() => expect(screen.getByRole("button", { name: TITLE })).toHaveFocus());
    screen.getByRole("button", { name: "Elsewhere" }).focus();
    focusRestoredCard(CARD_ID);
    // Give the frame its turn: the focus the person chose stays.
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve());
    });
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });
});
