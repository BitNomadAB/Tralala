import { screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { CHANGED_ELSEWHERE } from "@/features/cards/useUnblock";
import type { Card } from "@/lib/types";
import { ticketCard } from "./msw/cards";
import { apiPath, failure, ok } from "./msw/envelope";
import { LOOP_PATH, NOW } from "./msw/loops";
import { server } from "./msw/server";
import { PREREQUISITE_KEY } from "./msw/ticketView";
import { LOOP_URL, renderTicket, TICKET_URL } from "./renderTicket";

const FIRST_ID = "card-0";
const FIRST_PATH = `${LOOP_PATH}/cards/${FIRST_ID}`;

/** The open Ticket the viewed one waits for: the plan's `item-0`. */
function first(extra: Partial<Card> = {}): Card {
  return ticketCard({
    id: FIRST_ID,
    plan_item_id: "item-0",
    ticket_key: PREREQUISITE_KEY,
    title: "Give the word",
    version: 7,
    ...extra,
  });
}

/** The viewed Ticket, in the second column, blocked by the plan's `item-0`. */
const BLOCKED = ticketCard({
  list_id: "list-2",
  ready: false,
  state: "blocked",
  blockers: [{ type: "ticket", id: "item-0", key: PREREQUISITE_KEY, reason: "prerequisite" }],
});

/**
 * The blocked Ticket over a Loop whose open Tickets are `open`, and the first one's routes: each
 * records what was sent and answers as `after` says (a Ticket to list instead, or null when it is
 * completed, which also frees the viewed Ticket), or refuses when `refuse` is set.
 */
async function renderHeld(
  open: Card[],
  { url = LOOP_URL, after = () => null as Card | null, refuse = false } = {},
) {
  const rendered = await renderTicket(BLOCKED, url, { open });
  const sent: { route: string; body: unknown }[] = [];
  const step = async (route: string, request: Request) => {
    // Restoring sends no body.
    const body: unknown = route === "restore" ? null : await request.json();
    sent.push({ route, body });
    if (refuse) return failure(409, "version_conflict", "The card changed since it was read");
    const next = after();
    const index = open.findIndex((card) => card.id === FIRST_ID);
    if (next) open.splice(index, 1, next);
    else {
      open.splice(index, 1);
      rendered.view.state.card = {
        ...rendered.view.state.card,
        ready: true,
        blockers: [],
        state: "ready",
      };
    }
    return ok(next ?? first({ completed_at: NOW, state: null }));
  };
  server.use(
    http.post(apiPath(`${FIRST_PATH}/confirm`), ({ request }) => step("confirm", request)),
    http.post(apiPath(`${FIRST_PATH}/wait/clear`), ({ request }) => step("clear", request)),
    http.post(apiPath(`${FIRST_PATH}/restore`), ({ request }) => step("restore", request)),
    http.patch(apiPath(FIRST_PATH), ({ request }) => step("patch", request)),
  );
  return { ...rendered, sent };
}

const heldUpBy = () => screen.findByRole("list", { name: "Held up by" });

describe("what holds a blocked Ticket up, under its state", () => {
  it("names the open Ticket with a link that opens it and the button it needs", async () => {
    await renderHeld([first({ human_action_required: true, required_actor: "human" })]);
    const list = await heldUpBy();
    expect(
      within(list).getByRole("link", { name: `${PREREQUISITE_KEY} Give the word` }),
    ).toHaveAttribute("href", `${LOOP_URL}?card=${FIRST_ID}`);
    expect(list).toHaveTextContent("Only a person can do this work.");
    expect(
      within(list).getByRole("button", { name: `Confirm ${PREREQUISITE_KEY}` }),
    ).not.toHaveAttribute("aria-disabled");
    // The Ticket's own decision stays held, and says by what.
    expect(
      screen.getByRole("button", {
        name: "Mark complete",
        description: `Blocked by ${PREREQUISITE_KEY}`,
      }),
    ).toHaveAttribute("aria-disabled", "true");
  });

  it("links to the other Ticket's page from the Ticket's own page", async () => {
    await renderHeld([first()], { url: TICKET_URL });
    const list = await heldUpBy();
    expect(within(list).getByRole("link")).toHaveAttribute(
      "href",
      `${LOOP_URL}/tickets/${FIRST_ID}`,
    );
  });

  it("confirms a person's task from there and hands the focus to the freed decision", async () => {
    const { sent, user } = await renderHeld([
      first({ human_action_required: true, required_actor: "human" }),
    ]);
    const list = await heldUpBy();
    await user.click(within(list).getByRole("button", { name: `Confirm ${PREREQUISITE_KEY}` }));
    await waitFor(() => expect(screen.queryByText("Held up by")).toBeNull());
    expect(sent).toEqual([{ route: "confirm", body: { version: 7, note: "" } }]);
    const complete = screen.getByRole("button", { name: "Mark complete" });
    await waitFor(() => expect(complete).toHaveFocus());
    await waitFor(() => expect(complete).not.toHaveAttribute("aria-disabled"));
  });

  it("completes another Ticket with its version", async () => {
    const { sent, user } = await renderHeld([first()]);
    const list = await heldUpBy();
    await user.click(within(list).getByRole("button", { name: `Complete ${PREREQUISITE_KEY}` }));
    await waitFor(() => expect(screen.queryByText("Held up by")).toBeNull());
    expect(sent).toEqual([{ route: "patch", body: { version: 7, completed: true } }]);
  });

  it("clears a wait first; the same button then offers the next step and keeps the focus", async () => {
    const { sent, user } = await renderHeld(
      [first({ waiting_for: "information", waiting_reason: "Which account?" })],
      { after: () => first({ version: 8 }) },
    );
    const list = await heldUpBy();
    expect(list).toHaveTextContent("Waits for information: Which account?");
    const clear = within(list).getByRole("button", { name: `Clear wait ${PREREQUISITE_KEY}` });
    await user.click(clear);
    const complete = await within(list).findByRole("button", {
      name: `Complete ${PREREQUISITE_KEY}`,
    });
    expect(sent).toEqual([{ route: "clear", body: { version: 7 } }]);
    expect(complete).toBe(clear);
    expect(complete).toHaveFocus();
    expect(list).not.toHaveTextContent("Waits for");
  });

  it("restores an archived Ticket, which then asks for its next step", async () => {
    const { sent, user } = await renderHeld([first({ archived_at: NOW })], {
      after: () => first({ version: 8 }),
    });
    const list = await heldUpBy();
    expect(list).toHaveTextContent("Archived, and not completed.");
    await user.click(within(list).getByRole("button", { name: `Restore ${PREREQUISITE_KEY}` }));
    await within(list).findByRole("button", { name: `Complete ${PREREQUISITE_KEY}` });
    expect(sent).toEqual([{ route: "restore", body: null }]);
  });

  it("holds a Ticket that waits for earlier work itself, below the one that can be pressed", async () => {
    const earlier = ticketCard({
      id: "card-9",
      plan_item_id: "item-9",
      ticket_key: "SES-1-PH01-009",
      title: "Read the draft",
    });
    const held = first({
      ready: false,
      state: "blocked",
      blockers: [{ type: "ticket", id: "item-9", key: "SES-1-PH01-009", reason: "prerequisite" }],
    });
    await renderHeld([held, earlier]);
    const list = await heldUpBy();
    const buttons = within(list).getAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual([
      "Complete SES-1-PH01-009",
      `Complete ${PREREQUISITE_KEY}`,
    ]);
    expect(buttons[0]).not.toHaveAttribute("aria-disabled");
    expect(
      within(list).getByRole("button", {
        name: `Complete ${PREREQUISITE_KEY}`,
        description: "Blocked by SES-1-PH01-009",
      }),
    ).toHaveAttribute("aria-disabled", "true");
  });

  it("says when the other Ticket changed meanwhile, and keeps its row", async () => {
    const { user } = await renderHeld([first()], { refuse: true });
    const list = await heldUpBy();
    await user.click(within(list).getByRole("button", { name: `Complete ${PREREQUISITE_KEY}` }));
    expect(await screen.findByText(CHANGED_ELSEWHERE)).toBeInTheDocument();
    expect(
      within(list).getByRole("button", { name: `Complete ${PREREQUISITE_KEY}` }),
    ).toBeInTheDocument();
  });

  it("draws nothing for a Ticket nothing holds up", async () => {
    await renderTicket(ticketCard({ list_id: "list-2" }), LOOP_URL, { open: [first()] });
    await screen.findByRole("button", { name: "Mark complete" });
    expect(screen.queryByText("Held up by")).toBeNull();
  });
});
