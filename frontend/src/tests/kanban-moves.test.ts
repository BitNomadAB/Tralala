import { describe, expect, it } from "vitest";
import { dragText, KANBAN_INSTRUCTIONS } from "@/features/loops/kanbanAnnouncements";
import { currentTarget, dropTarget, placeAt, type KanbanState } from "@/features/loops/kanbanMoves";
import type { Card } from "@/lib/types";
import { ticketCard } from "./msw/cards";
import { COLUMNS } from "./msw/ticketView";

function card(id: string, listId: string, title: string): Card {
  return ticketCard({ id, list_id: listId, title });
}

const A = card("a", "list-1", "Rotate the key");
const B = card("b", "list-1", "Expire sessions");
const C = card("c", "list-1", "Audit logins");
const D = card("d", "list-2", "Write the runbook");

/** Backlog holds A, B and C; In Progress holds D; Done is empty. */
const STATE: KanbanState = {
  lists: COLUMNS,
  cardsByList: { "list-1": [A, B, C], "list-2": [D], "list-3": [] },
};

const over = (cardId: string, listId: string) => ({ type: "card" as const, cardId, listId });

describe("where a dragged card lands", () => {
  it("takes the place of the card it is over in its own column, up or down", () => {
    expect(dropTarget(STATE, A, over("b", "list-1"))).toEqual({ listId: "list-1", index: 1 });
    expect(dropTarget(STATE, A, over("c", "list-1"))).toEqual({ listId: "list-1", index: 2 });
    expect(dropTarget(STATE, C, over("a", "list-1"))).toEqual({ listId: "list-1", index: 0 });
  });

  it("stays where it was when dropped on itself", () => {
    expect(dropTarget(STATE, B, over("b", "list-1"))).toEqual(currentTarget(STATE, B));
    expect(currentTarget(STATE, B)).toEqual({ listId: "list-1", index: 1 });
  });

  it("goes in front of the card it is over in another column, and last over a column", () => {
    expect(dropTarget(STATE, A, over("d", "list-2"))).toEqual({ listId: "list-2", index: 0 });
    expect(dropTarget(STATE, A, { type: "list-body", listId: "list-2" })).toEqual({
      listId: "list-2",
      index: 1,
    });
    expect(dropTarget(STATE, A, { type: "list", listId: "list-3" })).toEqual({
      listId: "list-3",
      index: 0,
    });
    expect(dropTarget(STATE, A, undefined)).toBeNull();
  });

  it("says the place in words, counting the moved card in its new column", () => {
    expect(placeAt(STATE, A, { listId: "list-2", index: 1 })).toEqual({
      column: "In Progress",
      position: 2,
      count: 2,
    });
    expect(placeAt(STATE, A, { listId: "list-1", index: 2 })).toEqual({
      column: "Backlog",
      position: 3,
      count: 3,
    });
  });
});

describe("what a screen reader hears during a drag", () => {
  const active = { type: "card" as const, cardId: "a", listId: "list-1" };

  it("names the Ticket by its title, the column and the position, never an id", () => {
    expect(dragText(STATE, "start", active, undefined)).toBe(
      "Picked up Rotate the key, in Backlog, position 1 of 3.",
    );
    expect(dragText(STATE, "over", active, over("d", "list-2"))).toBe(
      "Rotate the key is over In Progress, position 1 of 2.",
    );
    expect(dragText(STATE, "over", active, undefined)).toBe("Rotate the key is not over a column.");
    expect(dragText(STATE, "end", active, { type: "list-body", listId: "list-3" })).toBe(
      "Rotate the key dropped in Done, position 1 of 1.",
    );
    expect(dragText(STATE, "end", active, undefined)).toBe(
      "Rotate the key was not dropped on a column and stays in Backlog, position 1 of 3.",
    );
    expect(dragText(STATE, "cancel", active, undefined)).toBe(
      "Moving Rotate the key was cancelled. It stays in Backlog, position 1 of 3.",
    );
  });

  it("names a column and its position among the columns", () => {
    const column = { type: "list" as const, listId: "list-3" };
    expect(dragText(STATE, "start", column, undefined)).toBe(
      "Picked up column Done, position 3 of 3.",
    );
    expect(dragText(STATE, "over", column, { type: "list", listId: "list-1" })).toBe(
      "Column Done is over position 1 of 3.",
    );
    expect(dragText(STATE, "end", column, over("d", "list-2"))).toBe(
      "Column Done dropped at position 2 of 3.",
    );
    expect(dragText(STATE, "cancel", column, undefined)).toBe(
      "Moving column Done was cancelled. It stays at position 3 of 3.",
    );
  });

  it("says nothing about what is not the board's, and tells how to move with the keys", () => {
    expect(dragText(STATE, "start", undefined, undefined)).toBeUndefined();
    expect(dragText(STATE, "start", { ...active, cardId: "gone" }, undefined)).toBeUndefined();
    expect(KANBAN_INSTRUCTIONS.draggable).toMatch(/Space or Enter.*arrow keys.*Escape/);
  });
});
