import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, type HttpHandler } from "msw";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useRouteFocus } from "@/app/useRouteFocus";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { TicketPage } from "@/features/cards/TicketPage";
import { parseFocus, withoutFocus } from "@/features/cards/useTicketFocus";
import type { CardDetail } from "@/lib/types";
import { LocationProbe } from "./LocationProbe";
import { CARD_PATH, ticketCard } from "./msw/cards";
import { apiPath, ok } from "./msw/envelope";
import { LOOP, LOOP_PATH, NOW } from "./msw/loops";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";
import { ticketViewHandlers } from "./msw/ticketView";
import { renderLoopPage, TITLE } from "./renderLoopPage";
import { TICKET_URL } from "./renderTicket";

const WAITING = {
  waiting_for: "decision",
  waiting_reason: "Which key store?",
  waiting_set_by: "Ada Member",
  waiting_stop: null,
  waiting_set_at: NOW,
  state: "needs_input",
} satisfies Partial<CardDetail>;

const PERSON_TASK = {
  human_action_required: true,
  human_action_reason: "Only the key holder can rotate it",
  needs_person: true,
} satisfies Partial<CardDetail>;

function RouteFocus() {
  useRouteFocus();
  return null;
}

/**
 * The Ticket's page at `?focus=<focus>` over `card`, with the app's route focus. A tab opened on
 * it moves no focus by itself; `viaLink` starts on a page with a link to it instead, the way the
 * sign-in navigates there, so the route focus gives the page's heading the focus as it arrives.
 * `extra` handlers answer before the view's own.
 */
async function renderPage(
  card: CardDetail,
  focus: string,
  extra: HttpHandler[] = [],
  viaLink = false,
) {
  const view = ticketViewHandlers(card);
  server.use(...view.handlers);
  server.use(...extra);
  const address = `${TICKET_URL}?focus=${focus}`;
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
          <MemoryRouter initialEntries={[viaLink ? "/" : address]}>
            <RouteFocus />
            <main id="main">
              <Routes>
                <Route path="/" element={<Link to={address}>Open the decision</Link>} />
                <Route
                  path="/boards/:boardId/loops/:loopId/tickets/:cardId"
                  element={<TicketPage />}
                />
              </Routes>
            </main>
            <LocationProbe />
          </MemoryRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  if (viaLink) {
    await userEvent.setup().click(screen.getByRole("link", { name: "Open the decision" }));
  }
  return screen.findByRole("heading", { level: 1, name: TITLE });
}

/** The Loop page with the Ticket open over it from `?card=card-1&focus=<focus>`, over `card`. */
async function renderDialog(card: CardDetail, focus: string) {
  const page = await renderLoopPage(`?card=card-1&focus=${focus}`, "in_progress", {}, [
    http.get(apiPath(CARD_PATH), () => ok(card)),
  ]);
  const dialog = await screen.findByRole("dialog", { name: TITLE });
  return { ...page, dialog };
}

// A string name matches the whole name, so "Clear wait SES-1-…" of the Held up by list is no match.
const button = (name: string, root: HTMLElement = document.body) =>
  within(root).getByRole("button", { name });

/** The query string while the Ticket's dialog may hide the probe from the accessibility tree. */
const query = () => screen.getByLabelText("Query");

describe("the button a link to a decision names", () => {
  it("reads clear-wait and confirm, and nothing else", () => {
    expect(parseFocus("clear-wait")).toBe("clear-wait");
    expect(parseFocus("confirm")).toBe("confirm");
    expect(parseFocus(null)).toBeNull();
    expect(parseFocus("mark-waiting")).toBeNull();
    expect(parseFocus("Confirm")).toBeNull();
    expect(withoutFocus(new URLSearchParams("card=card-1&focus=confirm")).toString()).toBe(
      "card=card-1",
    );
  });
});

describe("a link to a Ticket's decision on its page", () => {
  it("focuses Clear the wait of a Ticket that waits, and leaves the address", async () => {
    await renderPage(ticketCard(WAITING), "clear-wait");
    await waitFor(() => expect(button("Clear the wait")).toHaveFocus());
    // The router moves on in a transition, so the address follows a moment later.
    await waitFor(() => expect(query()).toBeEmptyDOMElement());
    expect(button("Clear the wait")).toHaveFocus();
  });

  it("takes the focus from the heading the route focus gives a page navigated to", async () => {
    await renderPage(ticketCard(WAITING), "clear-wait", [], true);
    await waitFor(() => expect(button("Clear the wait")).toHaveFocus());
    await waitFor(() => expect(query()).toBeEmptyDOMElement());
    expect(button("Clear the wait")).toHaveFocus();
  });

  it("focuses Confirm human action of a person's task", async () => {
    await renderPage(ticketCard(PERSON_TASK), "confirm");
    await waitFor(() => expect(button("Confirm human action")).toHaveFocus());
    // Only the focus moved: nothing was confirmed.
    expect(button("Confirm human action")).toBeVisible();
  });

  it("focuses Confirm human action while the Ticket waits, held, and read with why", async () => {
    await renderPage(ticketCard({ ...PERSON_TASK, ...WAITING }), "confirm");
    const confirm = button("Confirm human action");
    await waitFor(() => expect(confirm).toHaveFocus());
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAccessibleDescription("Clear the wait first");
    expect(button("Clear the wait")).toBeVisible();
  });

  it("gives the title the focus when the wait was already cleared", async () => {
    const title = await renderPage(ticketCard(), "clear-wait");
    await waitFor(() => expect(title).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Clear the wait" })).toBeNull();
    await waitFor(() => expect(query()).toBeEmptyDOMElement());
  });

  it("gives the title the focus when the Ticket was already confirmed", async () => {
    const done = ticketCard({ ...PERSON_TASK, completed_at: NOW, human_confirmed_at: NOW });
    const title = await renderPage(done, "confirm");
    await waitFor(() => expect(title).toHaveFocus());
  });

  it("waits for the Loop before it chooses: a completed Loop shows no Confirm", async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const title = await renderPage(ticketCard(PERSON_TASK), "confirm", [
      http.get(apiPath(LOOP_PATH), async () => {
        await held;
        return ok({ ...LOOP, stage: "completed", completed_at: NOW });
      }),
    ]);
    // Drawn while the Loop is still on its way, but not focused: it may not stay.
    expect(button("Confirm human action")).not.toHaveFocus();
    expect(query()).toHaveTextContent("?focus=confirm");

    await act(async () => {
      release();
      await Promise.resolve();
    });
    await waitFor(() => expect(title).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Confirm human action" })).toBeNull();
  });

  it("leaves the focus alone for a button it does not know", async () => {
    const title = await renderPage(ticketCard(WAITING), "mark-waiting");
    // The Loop has answered, so a known button would have been focused by now.
    expect(await screen.findByRole("link", { name: "SES-1 Session expiry" })).toBeVisible();
    expect(button("Clear the wait")).toBeVisible();
    expect(title).not.toHaveFocus();
    expect(button("Clear the wait")).not.toHaveFocus();
    expect(query()).toHaveTextContent("?focus=mark-waiting");
  });
});

describe("a link to a Ticket's decision in the dialog over the Kanban", () => {
  it("focuses Clear the wait, keeps the Ticket open and drops only focus", async () => {
    const { dialog } = await renderDialog(ticketCard(WAITING), "clear-wait");
    await waitFor(() => expect(button("Clear the wait", dialog)).toHaveFocus());
    await waitFor(() => expect(query()).toHaveTextContent(/^\?card=card-1$/));
    expect(button("Clear the wait", dialog)).toHaveFocus();
  });

  it("focuses Confirm human action of a person's task", async () => {
    const { dialog } = await renderDialog(ticketCard(PERSON_TASK), "confirm");
    await waitFor(() => expect(button("Confirm human action", dialog)).toHaveFocus());
  });

  it("gives the title the focus when the button is not there", async () => {
    const { dialog } = await renderDialog(ticketCard(), "confirm");
    const title = within(dialog).getByRole("heading", { level: 2, name: TITLE });
    await waitFor(() => expect(title).toHaveFocus());
  });

  it("leaves neither the Ticket nor focus in the address once the dialog is closed", async () => {
    const { dialog } = await renderDialog(ticketCard(WAITING), "clear-wait");
    await waitFor(() => expect(button("Clear the wait", dialog)).toHaveFocus());
    const user = userEvent.setup();
    await user.click(button("Close dialog", dialog));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(query()).toBeEmptyDOMElement();
  });
});
