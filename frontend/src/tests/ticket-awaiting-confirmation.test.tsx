import { DndContext } from "@dnd-kit/core";
import { SortableContext } from "@dnd-kit/sortable";
import { render, screen, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { completeBlocked, doneAwaiting, stateReason } from "@/features/cards/ticketRules";
import { TicketCard } from "@/features/loops/TicketCard";
import type { Card, LoopReadiness } from "@/lib/types";
import { ticketCard } from "./msw/cards";
import { apiPath, ok } from "./msw/envelope";
import { LOOP_PATH, NOW } from "./msw/loops";
import { planItem, PREREQUISITE_KEY, READINESS } from "./msw/ticketView";
import { renderLoopPage } from "./renderLoopPage";
import { renderTicket } from "./renderTicket";

/** The person's task the viewed Ticket waits for: the plan's `item-0`, not confirmed yet. */
const TASK = ticketCard({
  id: "card-0",
  plan_item_id: "item-0",
  ticket_key: PREREQUISITE_KEY,
  title: "Sign the contract",
  required_actor: "human",
  human_action_required: true,
});

/** A Ticket held up only by that task: it may be worked and completed. */
function held(extra: Partial<Card> = {}): Card {
  return ticketCard({
    list_id: "list-2",
    ready: false,
    state: "ready",
    blockers: [
      {
        type: "ticket",
        id: "item-0",
        key: PREREQUISITE_KEY,
        reason: "prerequisite_ticket_incomplete",
      },
    ],
    awaiting_confirmation: true,
    confirmations: [{ id: "item-0", key: PREREQUISITE_KEY, title: "Sign the contract" }],
    ...extra,
  });
}

const DONE = held({ completed_at: NOW, state: null });

describe("the rules for a Ticket awaiting a person's confirmation", () => {
  it("lets it be completed and says what it waits for", () => {
    expect(completeBlocked(held())).toBeNull();
    expect(stateReason(held())).toBe(`waits for a person to confirm ${PREREQUISITE_KEY}`);
    expect(doneAwaiting(held())).toBe(false);
    expect(doneAwaiting(DONE)).toBe(true);
  });

  it("still holds a Ticket blocked by real work, and a wait still wins", () => {
    const blocked = held({ awaiting_confirmation: false, confirmations: [], state: "blocked" });
    expect(completeBlocked(blocked)).toBe(`Blocked by ${PREREQUISITE_KEY}`);
    const waiting = held({ waiting_for: "decision", state: "needs_input" });
    expect(completeBlocked(waiting)).toBe("Clear the wait first");
    expect(stateReason(waiting)).toBe("waits for a decision");
  });
});

describe("a Ticket awaiting a person's confirmation, in its rail", () => {
  it("reads Ready, can be marked complete, and offers the person's Confirm", async () => {
    await renderTicket(held(), undefined, { open: [TASK] });
    const status = await screen.findByRole("region", { name: "Status" });
    expect(status).toHaveTextContent(`Ready· waits for a person to confirm ${PREREQUISITE_KEY}`);
    const complete = screen.getByRole("button", { name: "Mark complete" });
    expect(complete).not.toHaveAttribute("aria-disabled");
    const list = await within(status).findByRole("list", { name: "Held up by" });
    expect(
      within(list).getByRole("button", { name: `Confirm ${PREREQUISITE_KEY}` }),
    ).not.toHaveAttribute("aria-disabled");
  });

  it("once completed reads Done, awaiting confirmation, and keeps the Confirm", async () => {
    await renderTicket(DONE, undefined, { open: [TASK] });
    const status = await screen.findByRole("region", { name: "Status" });
    expect(status).toHaveTextContent(`Done· awaiting confirmation of ${PREREQUISITE_KEY}`);
    expect(status).not.toHaveTextContent("Completed");
    const list = await within(status).findByRole("list", { name: "Held up by" });
    expect(
      within(list).getByRole("button", { name: `Confirm ${PREREQUISITE_KEY}` }),
    ).toBeInTheDocument();
  });

  it("reads Completed again once the person confirmed", async () => {
    await renderTicket(held({ completed_at: NOW, state: null, ...confirmed() }));
    const status = await screen.findByRole("region", { name: "Status" });
    expect(status).toHaveTextContent("Completed");
    expect(within(status).queryByText("Held up by")).toBeNull();
  });
});

function confirmed(): Partial<Card> {
  return { ready: true, blockers: [], awaiting_confirmation: false, confirmations: [] };
}

function renderKanbanCard(card: Card) {
  render(
    <DndContext>
      <SortableContext items={[card.id]}>
        <ul>
          <TicketCard card={card} />
        </ul>
      </SortableContext>
    </DndContext>,
  );
  return screen.getByRole("listitem");
}

describe("the Kanban card of a Ticket awaiting a person's confirmation", () => {
  it("marks a completed one Awaiting confirmation, naming whose", () => {
    const item = renderKanbanCard(DONE);
    expect(within(item).getByText("done")).toBeInTheDocument();
    expect(within(item).getByText("Awaiting confirmation")).toBeInTheDocument();
    expect(item).toHaveTextContent(`Done; a person has still to confirm ${PREREQUISITE_KEY}`);
  });

  it("shows no mark on an open one, which reads as ready", () => {
    const item = renderKanbanCard(held());
    expect(within(item).queryByText("Awaiting confirmation")).toBeNull();
    expect(within(item).queryByText("Blocked")).toBeNull();
  });
});

describe("the Loop header's person's tasks", () => {
  it("lists a task the Phases after it depend on and says their work goes on", async () => {
    const readiness: LoopReadiness = {
      ...READINESS,
      items: [
        planItem("item-0", PREREQUISITE_KEY, {
          title: "Sign the contract",
          card_id: "card-0",
          required_actor: "human",
          human_action_required: true,
          downstream_phase_numbers: [2, 3],
        }),
        planItem("item-9", "SES-1-PH01-009", {
          title: "Countersign",
          card_id: "card-9",
          required_actor: "human",
          human_action_required: true,
          ready: false,
          awaiting_confirmation: true,
          confirmations: [{ id: "item-0", key: PREREQUISITE_KEY, title: "Sign the contract" }],
        }),
      ],
    };
    await renderLoopPage("", "in_progress", {}, [
      http.get(apiPath(`${LOOP_PATH}/readiness`), () => ok(readiness)),
    ]);
    const task = await screen.findByText(/Sign the contract — human action required\./);
    expect(task).toHaveTextContent(
      "Phases 2, 3 depend on it: their work need not wait for it, and stays awaiting " +
        "confirmation until a person confirms this.",
    );
    // A person's task held up only by another one may be confirmed, so it is listed too.
    expect(await screen.findByText(/Countersign — human action required\./)).toBeInTheDocument();
  });
});
