import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CARD_PATH, ticketCard } from "./msw/cards";
import { NOW } from "./msw/loops";
import { PREREQUISITE_KEY } from "./msw/ticketView";
import { renderTicket, writes } from "./renderTicket";

function rail() {
  return screen.getByRole("complementary", { name: "Status and details" });
}

function details() {
  return within(rail()).getByRole("region", { name: "Details" });
}

describe("the Ticket's rail", () => {
  it("moves the card with the column menu, which shows each column's count", async () => {
    const { view, user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Column: Backlog" }));
    expect(screen.getByRole("option", { name: "In Progress, 0" })).toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "Done, 21" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Column: Done" })).toBeInTheDocument(),
    );
    expect(writes(view)).toEqual([
      {
        route: `POST ${CARD_PATH}/move`,
        body: { version: 3, list_id: "list-3", position: 10_000 },
      },
    ]);
  });

  it("shows what the Ticket depends on from the plan, with a done mark", async () => {
    await renderTicket();
    await waitFor(() => expect(details()).toHaveTextContent(`${PREREQUISITE_KEY}done`));
    expect(details()).toHaveTextContent("Phase1 · Session limits");
  });

  it("gives the Ticket to a person and back to nobody", async () => {
    const { view, user } = await renderTicket();
    await user.click(await screen.findByRole("button", { name: "Owner: Nobody" }));
    await user.click(await screen.findByRole("option", { name: "Grace Hopper" }));
    const owner = await screen.findByRole("button", { name: "Owner: Grace Hopper" });
    await user.click(owner);
    await user.click(screen.getByRole("option", { name: "Nobody" }));
    await screen.findByRole("button", { name: "Owner: Nobody" });
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, assignee_actor_id: "user-2" } },
      { route: `PATCH ${CARD_PATH}`, body: { version: 4, clear_assignee: true } },
    ]);
  });

  it("changes the priority on a click and saves it with the version", async () => {
    const { view, user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Priority: None" }));
    expect(screen.getByRole("option", { name: "None" })).toHaveFocus();
    await user.click(screen.getByRole("option", { name: "High" }));
    expect(await screen.findByRole("button", { name: "Priority: High" })).toHaveFocus();
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, priority: "high" } },
    ]);
  });

  it("saves where the work is done through its own route", async () => {
    const { view, user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Work is done: Not decided" }));
    await user.click(screen.getByRole("option", { name: "In the code base" }));
    await screen.findByRole("button", { name: "Work is done: In the code base" });
    await user.click(screen.getByRole("button", { name: "Work is done: In the code base" }));
    await user.click(screen.getByRole("option", { name: "Outside the code base" }));
    await screen.findByRole("button", { name: "Work is done: Outside the code base" });
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}/workplace`, body: { version: 3, workplace: "codebase" } },
      { route: `PATCH ${CARD_PATH}/workplace`, body: { version: 4, workplace: "outside" } },
    ]);
  });

  it("keeps a completed Ticket's workplace as it was", async () => {
    await renderTicket(ticketCard({ completed_at: NOW, state: null, workplace: "codebase" }));
    expect(screen.queryByRole("button", { name: /^Work is done/ })).toBeNull();
    expect(details()).toHaveTextContent("In the code base");
  });

  it("sets and clears the due date", async () => {
    const { view, user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Due: None" }));
    const field = screen.getByLabelText("Due date");
    await user.type(field, "2026-12-01{Enter}");
    const due = await screen.findByRole("button", { name: /^Due: (?!None)/ });
    await user.click(due);
    await user.click(screen.getByRole("button", { name: "Clear" }));
    await screen.findByRole("button", { name: "Due: None" });
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, due_at: "2026-12-01T00:00:00Z" } },
      { route: `PATCH ${CARD_PATH}`, body: { version: 4, clear_due_at: true } },
    ]);
  });

  it("picks labels, each press saving", async () => {
    const { view, user } = await renderTicket();
    await user.click(await screen.findByRole("button", { name: "Labels: None" }));
    await user.click(await screen.findByRole("button", { name: "Backend", pressed: false }));
    await screen.findByRole("button", { name: "Backend", pressed: true });
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("button", { name: "Labels: Backend" })).toHaveFocus();
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, labels: ["label-1"] } },
    ]);
  });

  it("confirms a human-only Ticket in the state block, not in the actions row", async () => {
    const { view, user } = await renderTicket(
      ticketCard({ list_id: "list-2", human_action_required: true }),
    );
    expect(screen.queryByRole("button", { name: "Mark complete" })).toBeNull();
    const status = within(rail()).getByRole("region", { name: "Status" });
    await user.click(within(status).getByRole("button", { name: "Confirm human action" }));
    await waitFor(() => expect(status).toHaveTextContent("Completed"));
    expect(writes(view)).toEqual([
      { route: `POST ${CARD_PATH}/confirm`, body: { version: 3, note: "" } },
    ]);
  });

  it("keeps Move to another Loop for later", async () => {
    await renderTicket();
    const move = within(rail()).getByRole("button", { name: "Move to another Loop…" });
    expect(move).toBeDisabled();
    expect(move).toHaveAttribute("title", "Later");
  });
});
