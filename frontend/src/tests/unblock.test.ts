import { describe, expect, it } from "vitest";
import { holdUps, needHeld, needNote, ticketNeed } from "@/features/cards/unblock";
import type { Card, LoopBlocker } from "@/lib/types";
import { ticketCard } from "./msw/cards";
import { NOW } from "./msw/loops";

/** An open planned Ticket `name`: card `card-<name>`, planned Ticket `item-<name>`, key `K-<name>`. */
function open(name: string, extra: Partial<Card> = {}): Card {
  return ticketCard({
    id: `card-${name}`,
    plan_item_id: `item-${name}`,
    ticket_key: `K-${name}`,
    title: `Ticket ${name}`,
    ...extra,
  });
}

/** The plan's blocker that names the planned Ticket `name`. */
function waitsFor(name: string): LoopBlocker {
  return { type: "ticket", id: `item-${name}`, key: `K-${name}`, reason: "prerequisite" };
}

/** A Ticket the plan blocks by `blockers`. */
function blockedBy(name: string, blockers: LoopBlocker[], extra: Partial<Card> = {}): Card {
  return open(name, { ready: false, state: "blocked", blockers, ...extra });
}

const keys = (cards: Card[]) => cards.map((card) => card.ticket_key);

describe("what a Ticket that is not completed needs next", () => {
  it("asks for nothing once the Ticket is completed", () => {
    expect(ticketNeed(open("a", { completed_at: NOW, state: null }))).toBeNull();
  });

  it("restores an archived Ticket before anything else", () => {
    const card = open("a", { archived_at: NOW, waiting_for: "decision" });
    expect(ticketNeed(card)).toBe("restore");
    expect(needNote(card, "restore")).toBe("Archived, and not completed.");
    expect(needHeld(card, "restore")).toBeNull();
  });

  it("clears a wait before the work is confirmed or completed, and says what it waits for", () => {
    const card = open("a", {
      waiting_for: "information",
      waiting_reason: "Which account?",
      human_action_required: true,
    });
    expect(ticketNeed(card)).toBe("clear_wait");
    expect(needNote(card, "clear_wait")).toBe("Waits for information: Which account?");
    expect(needNote({ ...card, waiting_reason: "" }, "clear_wait")).toBe("Waits for information");
  });

  it("clears a wait although earlier work is open: a person can answer now", () => {
    const card = blockedBy("b", [waitsFor("a")], { waiting_for: "third_party" });
    expect(ticketNeed(card)).toBe("clear_wait");
    expect(needHeld(card, "clear_wait")).toBeNull();
  });

  it("confirms a person's task and completes any other", () => {
    const person = open("a", { human_action_required: true, required_actor: "human" });
    expect(ticketNeed(person)).toBe("confirm");
    expect(needNote(person, "confirm")).toBe("Only a person can do this work.");
    expect(ticketNeed(open("b"))).toBe("complete");
    expect(needNote(open("b"), "complete")).toBeNull();
  });

  it("holds the last step while earlier work is open, naming it", () => {
    const card = blockedBy("b", [waitsFor("a")]);
    expect(needHeld(card, "complete")).toBe("Blocked by K-a");
    expect(needHeld({ ...card, human_action_required: true }, "confirm")).toBe("Blocked by K-a");
    expect(needHeld(open("a"), "complete")).toBeNull();
  });
});

describe("the open Tickets that hold a Ticket up", () => {
  it("finds the Ticket a blocker names by its planned Ticket", () => {
    const viewed = blockedBy("c", [waitsFor("a")]);
    expect(keys(holdUps(viewed, [open("a"), open("z"), viewed]))).toEqual(["K-a"]);
  });

  it("is empty when the Ticket it waits for is no longer open", () => {
    expect(holdUps(blockedBy("c", [waitsFor("a")]), [open("z")])).toEqual([]);
    expect(holdUps(open("c"), [open("a")])).toEqual([]);
  });

  it("follows the chain, and puts what can be pressed now first", () => {
    const viewed = blockedBy("c", [waitsFor("b")]);
    const middle = blockedBy("b", [waitsFor("a")]);
    // The Loop lists the blocked one first; the list a person works down starts with the other.
    expect(keys(holdUps(viewed, [middle, open("a"), viewed]))).toEqual(["K-a", "K-b"]);
  });

  it("takes every open Ticket of a Phase the Ticket waits for, archived ones included", () => {
    const phase: LoopBlocker = { type: "phase", id: "phase-1", phase_number: 1, reason: "phase" };
    const viewed = blockedBy("c", [phase], { phase_number: 2 });
    const rows = holdUps(viewed, [
      open("a", { phase_number: 1 }),
      open("b", { phase_number: 1, archived_at: NOW }),
      open("other", { phase_number: 2 }),
      open("outside", { phase_number: null, kind: "manual" }),
      viewed,
    ]);
    expect(keys(rows)).toEqual(["K-a", "K-b"]);
  });

  it("ends on Tickets that wait for one another, and never lists the Ticket itself", () => {
    const viewed = blockedBy("a", [waitsFor("b")]);
    const other = blockedBy("b", [waitsFor("a")]);
    expect(keys(holdUps(viewed, [viewed, other]))).toEqual(["K-b"]);
  });

  it("counts a wait on a blocker as something a person can take away now", () => {
    const viewed = blockedBy("c", [waitsFor("a"), waitsFor("b")]);
    const held = blockedBy("a", [waitsFor("x")]);
    const waiting = blockedBy("b", [waitsFor("x")], { waiting_for: "decision" });
    expect(keys(holdUps(viewed, [held, waiting]))).toEqual(["K-b", "K-a"]);
  });
});
