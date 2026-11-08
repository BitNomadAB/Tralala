import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { TicketState } from "@/features/cards/TicketState";
import { TicketCard } from "@/features/loops/TicketCard";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { CardDetail } from "@/lib/types";
import { CARD_ID, CARD_PATH, PERSON_ID, ticketCard, ticketWorkHandlers } from "./msw/cards";
import { BOARD_ID, LOOP_ID, NOW } from "./msw/loops";
import { server } from "./msw/server";

/** The rail's state block as the view holds it: the card from its query, a change refetches it. */
function Section() {
  const queryClient = useQueryClient();
  const [waitOpen, setWaitOpen] = useState(false);
  const card = useQuery({
    queryKey: keys.card(BOARD_ID, LOOP_ID, CARD_ID),
    queryFn: () => api.getCard(BOARD_ID, LOOP_ID, CARD_ID),
  });
  if (!card.data) return <p>Loading card…</p>;
  return (
    <section aria-label="Status">
      <TicketState
        boardId={BOARD_ID}
        loopId={LOOP_ID}
        card={card.data}
        readOnly={false}
        onChanged={() => {
          void queryClient.invalidateQueries({ queryKey: keys.card(BOARD_ID, LOOP_ID, CARD_ID) });
        }}
        waitOpen={waitOpen}
        onWaitOpenChange={setWaitOpen}
        onConfirm={() => undefined}
        confirmBlocked={null}
        pending={false}
      />
    </section>
  );
}

async function renderSection(card: CardDetail) {
  const work = ticketWorkHandlers(card);
  server.use(...work.handlers);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <Section />
    </QueryClientProvider>,
  );
  const section = await screen.findByRole("region", { name: "Status" });
  return { work, section, user: userEvent.setup() };
}

const DECISION = {
  waiting_for: "decision",
  waiting_reason: "Which key store do we use?",
  waiting_set_at: NOW,
  waiting_set_by: PERSON_ID,
  state: "needs_input",
  needs_person: true,
} as const;

describe("where a Ticket's work is done and what it waits for", () => {
  it("shows a ready Ticket with nothing holding it up and a way to mark it as waiting", async () => {
    const { section } = await renderSection(ticketCard({ workplace: "codebase" }));
    expect(within(section).getByText("Ready")).toBeInTheDocument();
    expect(section).toHaveTextContent("· nothing holds it up");
    // Where the work is done is a fact in the rail now (ticket-view.test.tsx).
    expect(within(section).getByRole("button", { name: "Mark as waiting…" })).toBeInTheDocument();
  });

  it("shows a wait with its kind, its reason, who set it and when", async () => {
    const { section } = await renderSection(ticketCard(DECISION));
    expect(within(section).getByText("Needs input")).toBeInTheDocument();
    expect(section).toHaveTextContent("· waits for a decision: Which key store do we use?");
    expect(section).toHaveTextContent("Waits for: A decision");
    expect(section).toHaveTextContent("Which key store do we use?");
    expect(section).toHaveTextContent(`Set by ${PERSON_ID}`);
    expect(within(section).getByRole("button", { name: "Clear the wait" })).toBeInTheDocument();
  });

  it("shows a Ticket that waits for a third party as blocked", async () => {
    const { section } = await renderSection(
      ticketCard({ ...DECISION, waiting_for: "third_party", state: "blocked" }),
    );
    expect(within(section).getByText("Blocked")).toBeInTheDocument();
    expect(section).toHaveTextContent("Waits for: A third party");
  });

  it("shows no state on a completed Ticket and offers no change", async () => {
    const { section } = await renderSection(ticketCard({ completed_at: NOW, state: null }));
    expect(within(section).queryByText(/^(Ready|Needs input|Blocked)$/)).not.toBeInTheDocument();
    expect(within(section).getByText("Completed")).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Mark as waiting…" })).toBeNull();
  });

  it("puts a person's confirmation in the state block of a human-only Ticket", async () => {
    const { section } = await renderSection(ticketCard({ human_action_required: true }));
    expect(within(section).getByRole("button", { name: "Confirm human action" })).toBeEnabled();
  });

  it("sets a wait only with a reason, and sends the kind and the reason", async () => {
    const { work, section, user } = await renderSection(ticketCard());
    await user.click(within(section).getByRole("button", { name: "Mark as waiting…" }));
    const save = within(section).getByRole("button", { name: "Save the wait" });
    expect(save).toBeDisabled();
    await user.type(within(section).getByLabelText("Why (required)"), "   ");
    expect(save).toBeDisabled();
    await user.selectOptions(within(section).getByLabelText("It waits for"), "information");
    await user.clear(within(section).getByLabelText("Why (required)"));
    await user.type(within(section).getByLabelText("Why (required)"), "  The token's lifetime  ");
    await user.click(save);
    await waitFor(() => expect(section).toHaveTextContent("Waits for: Information"));
    expect(within(section).getByText("Needs input")).toBeInTheDocument();
    expect(work.state.bodies).toEqual([
      {
        route: `PATCH ${CARD_PATH}/wait`,
        body: { version: 3, waiting_for: "information", reason: "The token's lifetime" },
      },
    ]);
  });

  it("clears a wait with one click and the wait disappears", async () => {
    const { work, section, user } = await renderSection(ticketCard(DECISION));
    await user.click(within(section).getByRole("button", { name: "Clear the wait" }));
    await waitFor(() =>
      expect(within(section).getByRole("button", { name: "Mark as waiting…" })).toBeInTheDocument(),
    );
    expect(section).not.toHaveTextContent("Waits for");
    expect(within(section).getByText("Ready")).toBeInTheDocument();
    expect(work.state.bodies).toEqual([
      { route: `POST ${CARD_PATH}/wait/clear`, body: { version: 3 } },
    ]);
  });

  it("says to reload when someone else changed the Ticket first", async () => {
    const { work, section, user } = await renderSection(ticketCard(DECISION));
    work.state.card = { ...work.state.card, version: 7 };
    await user.click(within(section).getByRole("button", { name: "Clear the wait" }));
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Someone else changed this Ticket. Reload to see the latest version.",
    );
  });

  it("never says an agent does the work", async () => {
    const { section, user } = await renderSection(ticketCard());
    await user.click(within(section).getByRole("button", { name: "Mark as waiting…" }));
    expect(section).not.toHaveTextContent(/agent/i);
  });
});

describe("the Kanban card's marker", () => {
  it("shows Needs input, Blocked, and nothing for a ready Ticket", () => {
    const { unmount } = render(<TicketCard card={ticketCard(DECISION)} overlay />);
    expect(screen.getByText("Needs input")).toBeInTheDocument();
    expect(screen.queryByText("Blocked")).toBeNull();
    unmount();

    const blocked = render(
      <TicketCard card={ticketCard({ ready: false, state: "blocked" })} overlay />,
    );
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Needs input")).toBeNull();
    blocked.unmount();

    render(<TicketCard card={ticketCard()} overlay />);
    expect(screen.queryByText("Needs input")).toBeNull();
    expect(screen.queryByText("Blocked")).toBeNull();
  });
});
