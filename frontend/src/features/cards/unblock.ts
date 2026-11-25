import type { Card, LoopBlocker } from "@/lib/types";
import { completeBlocked } from "./ticketRules";
import { WAIT_LABELS, WAITS } from "./ticketWork";

/**
 * What a Ticket that is not completed needs from a person next, in the order the server asks for
 * it: an archived Ticket is restored, a wait is cleared, and then the work is confirmed (a
 * person's task) or marked complete.
 */
export type TicketNeed = "restore" | "clear_wait" | "confirm" | "complete";

/** The next thing a Ticket needs, or null once it is completed. */
export function ticketNeed(card: Card): TicketNeed | null {
  if (card.completed_at !== null) return null;
  if (card.archived_at !== null) return "restore";
  if (card.waiting_for !== "nothing") return "clear_wait";
  return card.human_action_required ? "confirm" : "complete";
}

/**
 * The button's word for each need. They differ from the Ticket's own buttons ("Confirm human
 * action", "Mark complete", "Clear the wait"), so a button for another Ticket is never mistaken
 * for one of this Ticket; the other Ticket's key follows in the accessible name.
 */
export const NEED_LABELS: Record<TicketNeed, string> = {
  restore: "Restore",
  clear_wait: "Clear wait",
  confirm: "Confirm",
  complete: "Complete",
};

/** What a screen reader hears once the server took it. */
export const NEED_DONE: Record<TicketNeed, string> = {
  restore: "Ticket restored",
  clear_wait: "Wait cleared",
  confirm: "Human action confirmed",
  complete: "Ticket completed",
};

/** Why the need's button cannot be pressed yet (earlier work comes first), or null when it can. */
export function needHeld(card: Card, need: TicketNeed): string | null {
  return need === "confirm" || need === "complete" ? completeBlocked(card) : null;
}

/** What the row says under the Ticket: the wait and its reason, or whose work it is. */
export function needNote(card: Card, need: TicketNeed): string | null {
  switch (need) {
    case "restore":
      return "Archived, and not completed.";
    case "clear_wait": {
      const kind = WAITS.find((wait) => wait === card.waiting_for);
      const wait = kind ? WAIT_LABELS[kind].toLowerCase() : card.waiting_for;
      return card.waiting_reason
        ? `Waits for ${wait}: ${card.waiting_reason}`
        : `Waits for ${wait}`;
    }
    case "confirm":
      return "Only a person can do this work.";
    case "complete":
      return null;
  }
}

/**
 * The open Tickets behind one blocker of the plan: the Ticket it names (a blocker carries the
 * planned Ticket's id), or every open Ticket of the Phase it names.
 */
function behind(blocker: LoopBlocker, open: readonly Card[]): Card[] {
  if (blocker.type === "phase") {
    const phase = blocker.phase_number ?? null;
    return phase === null
      ? []
      : open.filter((card) => card.kind === "ticket" && card.phase_number === phase);
  }
  return open.filter((card) => card.plan_item_id === blocker.id || card.id === blocker.id);
}

/**
 * The open Tickets that hold `card` up, directly or through one another (what blocks a blocker
 * holds the Ticket up as well), found among the Loop's open Tickets. Those whose button can be
 * pressed now come first, so a person works down the list; each group keeps the Loop's order.
 */
export function holdUps(card: Card, open: readonly Card[]): Card[] {
  const found = new Map<string, Card>();
  const seen = new Set([card.id]);
  const queue: Card[] = [card];
  for (let current = queue.shift(); current !== undefined; current = queue.shift()) {
    for (const blocker of current.blockers) {
      for (const next of behind(blocker, open)) {
        if (seen.has(next.id) || next.completed_at !== null) continue;
        seen.add(next.id);
        found.set(next.id, next);
        queue.push(next);
      }
    }
  }
  const rows = open.filter((candidate) => found.has(candidate.id));
  const pressable = (row: Card) => {
    const need = ticketNeed(row);
    return need !== null && needHeld(row, need) === null;
  };
  return [...rows.filter(pressable), ...rows.filter((row) => !pressable(row))];
}
