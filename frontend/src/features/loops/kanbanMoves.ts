import type { BoardList, Card } from "@/lib/types";
import type { DragData } from "./dragData";

/** The Loop's columns in order and the cards of each, as the Kanban shows them. */
export interface KanbanState {
  lists: readonly BoardList[];
  cardsByList: Readonly<Record<string, readonly Card[]>>;
}

/**
 * Where a card goes: a column, and its index among that column's cards without it (the position
 * `POST …/cards/{id}/move` takes).
 */
export interface CardTarget {
  listId: string;
  index: number;
}

/** A place on the Kanban in words: the column's name and the position counted from 1, of how many. */
export interface Place {
  column: string;
  position: number;
  count: number;
}

/**
 * Where a dragged card lands when it is dropped on `over`. In its own column it takes the place of
 * the card it is over, as the sorting preview shows, so it also stays put when dropped on itself;
 * in another column it goes in front of that card. Over a column itself, or its empty body, it goes
 * last. Null when it is over nothing of the board.
 */
export function dropTarget(
  state: KanbanState,
  card: Card,
  over: DragData | undefined,
): CardTarget | null {
  if (!over) return null;
  const column = state.cardsByList[over.listId] ?? [];
  const others = column.filter((item) => item.id !== card.id);
  if (over.type !== "card") return { listId: over.listId, index: others.length };
  const index =
    over.listId === card.list_id
      ? column.findIndex((item) => item.id === over.cardId)
      : others.findIndex((item) => item.id === over.cardId);
  return { listId: over.listId, index: index < 0 ? others.length : index };
}

/** The card's place once it is at `target`: the column's name, its position and the column's count. */
export function placeAt(state: KanbanState, card: Card, target: CardTarget): Place {
  const others = (state.cardsByList[target.listId] ?? []).filter((item) => item.id !== card.id);
  return {
    column: state.lists.find((list) => list.id === target.listId)?.name ?? "a column",
    position: Math.min(target.index, others.length) + 1,
    count: others.length + 1,
  };
}

/** Where the card is now, as a target: its column and its index there. */
export function currentTarget(state: KanbanState, card: Card): CardTarget {
  const column = state.cardsByList[card.list_id] ?? [];
  const index = column.findIndex((item) => item.id === card.id);
  return { listId: card.list_id, index: index < 0 ? column.length : index };
}

/** The card with `cardId`, wherever it is on the Kanban. */
export function findCard(state: KanbanState, cardId: string): Card | undefined {
  for (const cards of Object.values(state.cardsByList)) {
    const card = cards.find((item) => item.id === cardId);
    if (card) return card;
  }
  return undefined;
}

/** The index of the column `listId` among `lists` (its position), -1 when it is not there. */
export function columnIndex(lists: readonly BoardList[], listId: string): number {
  return lists.findIndex((list) => list.id === listId);
}
