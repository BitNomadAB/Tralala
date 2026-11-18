import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { announcer } from "./announcer";
import { CARD_ID, ticketCard } from "./msw/cards";
import { QUESTION } from "./msw/discussions";
import { ASKABLE, askedThread } from "./msw/ticketDiscussions";
import { LOOP_URL, MODAL_URL, renderDiscussion } from "./renderDiscussion";
import { renderTicket, TICKET_URL } from "./renderTicket";

const TITLE = "Rotate the signing key";

function title(level = 2) {
  return screen.getByRole("heading", { level, name: TITLE });
}

function rail() {
  return screen.getByRole("complementary", { name: "Status and details" });
}

describe("the focus after the Ticket's decisions", () => {
  it("goes from Start work to Mark complete, and says work started", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Start work" }));
    const complete = await screen.findByRole("button", { name: "Mark complete" });
    await waitFor(() => expect(complete).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("Work started"));
  });

  it("goes from Mark complete to the title, and says the Ticket is completed", async () => {
    const { user } = await renderTicket(ticketCard({ list_id: "list-2" }));
    await user.click(screen.getByRole("button", { name: "Mark complete" }));
    await waitFor(() => expect(title()).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Mark complete" })).toBeNull();
    await waitFor(() => expect(announcer()).toHaveTextContent("Ticket completed"));
  });

  it("goes to the title on the page too", async () => {
    const { user } = await renderTicket(ticketCard({ list_id: "list-2" }), TICKET_URL);
    await user.click(screen.getByRole("button", { name: "Mark complete" }));
    await waitFor(() => expect(title(1)).toHaveFocus());
  });

  it("goes from Confirm human action to the title, and says it is confirmed", async () => {
    const { user } = await renderTicket(
      ticketCard({ list_id: "list-2", human_action_required: true }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm human action" }));
    await waitFor(() => expect(title()).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("Human action confirmed"));
  });

  it("gives the focus back to More actions after an item, and says Mark incomplete went through", async () => {
    const { user } = await renderTicket(
      ticketCard({ list_id: "list-2", completed_at: "2026-11-04T09:00:00Z", state: null }),
    );
    const more = screen.getByRole("button", { name: "More actions" });
    await user.click(more);
    const menu = () => screen.getByRole("list", { name: "More actions" });
    await user.click(within(menu()).getByRole("button", { name: "Copy link" }));
    expect(more).toHaveFocus();
    await user.click(more);
    await user.click(within(menu()).getByRole("button", { name: "Mark incomplete" }));
    expect(more).toHaveFocus();
    await screen.findByRole("button", { name: "Mark complete" });
    await waitFor(() => expect(announcer()).toHaveTextContent("Ticket marked incomplete"));
    expect(more).toHaveFocus();
  });
});

describe("the focus around a wait", () => {
  it("goes back to the head's Mark as waiting when the form is cancelled", async () => {
    const { user } = await renderTicket();
    const head = screen.getByRole("button", { name: "Mark as waiting" });
    await user.click(head);
    expect(screen.getByLabelText("It waits for")).toHaveFocus();
    await user.click(within(rail()).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(head).toHaveFocus());
  });

  it("goes back to the rail's Mark as waiting… when the form it opened is cancelled", async () => {
    const { user } = await renderTicket();
    await user.click(within(rail()).getByRole("button", { name: "Mark as waiting…" }));
    await user.click(within(rail()).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(within(rail()).getByRole("button", { name: "Mark as waiting…" })).toHaveFocus(),
    );
  });

  it("goes to Clear the wait once a wait is saved, and back to Mark as waiting… once cleared", async () => {
    const { user } = await renderTicket();
    await user.click(within(rail()).getByRole("button", { name: "Mark as waiting…" }));
    await user.type(within(rail()).getByLabelText("Why (required)"), "Which key store?");
    await user.click(within(rail()).getByRole("button", { name: "Save the wait" }));
    const clear = await within(rail()).findByRole("button", { name: "Clear the wait" });
    await waitFor(() => expect(clear).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("Wait saved"));

    await user.click(clear);
    const mark = await within(rail()).findByRole("button", { name: "Mark as waiting…" });
    await waitFor(() => expect(mark).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("Wait cleared"));
  });

  it("keeps the column menu's button usable, and says where the Ticket moved", async () => {
    const { user } = await renderTicket();
    const column = screen.getByRole("button", { name: "Column: Backlog" });
    await user.click(column);
    await user.click(screen.getByRole("option", { name: "In Progress, 0" }));
    const moved = await screen.findByRole("button", { name: "Column: In Progress" });
    expect(moved).toHaveFocus();
    expect(moved).toBeEnabled();
    await waitFor(() => expect(announcer()).toHaveTextContent("Moved to In Progress"));
  });
});

describe("the focus when the Ticket's dialog swaps its view", () => {
  it("gives the Ticket's title the focus on Back to the Ticket", async () => {
    const { user } = await renderDiscussion(undefined, MODAL_URL);
    await user.click(screen.getByRole("button", { name: "Back to the Ticket" }));
    const heading = await screen.findByRole("heading", { level: 2, name: TITLE });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("gives the question the focus when Ask the agents opens the new discussion", async () => {
    const { api, user } = await renderDiscussion(askedThread(), `${LOOP_URL}?card=${CARD_ID}`, [], {
      agents: ASKABLE,
      heading: TITLE,
    });
    api.state.next.start = askedThread({ run_state: "running" });
    await user.click(screen.getByRole("button", { name: "Ask the agents" }));
    const dialog = await screen.findByRole("dialog", { name: "Ask the agents" });
    await user.type(within(dialog).getByLabelText("Question"), QUESTION);
    await user.click(within(dialog).getByRole("button", { name: "Ask" }));
    const question = await screen.findByRole("heading", { level: 2, name: QUESTION });
    await waitFor(() => expect(question).toHaveFocus());
  });
});
