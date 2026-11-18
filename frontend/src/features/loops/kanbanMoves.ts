import type { MenuItem } from "@/components/ui/menu";
import type { BoardList, Card } from "@/lib/types";
import type { DragData } from "./dragData";

/** Why every move is unavailable in a Loop that is completed, cancelled or archived. */
const READ_ONLY = "The Loop is read-only";

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

/** A menu entry that moves to `target`, or says why it cannot (`reason`). */
function moveItem(
  label: string,
  target: CardTarget | null,
  reason: string,
  readOnly: boolean,
  onMove: (target: CardTarget) => void,
): MenuItem {
  if (readOnly || target === null) {
    return {
      label,
      disabled: true,
      hint: readOnly ? READ_ONLY : reason,
      onSelect: () => undefined,
    };
  }
  return { label, onSelect: () => onMove(target) };
}

/**
 * The card's moves without dragging (WCAG 2.5.7), for its "Actions for <title>" menu: up, down, to
 * the top and the bottom of its column, and to the end of each other column. One that would not
 * move it stays in the menu, disabled, with the reason.
 */
export function cardMoveItems(
  state: KanbanState,
  card: Card,
  readOnly: boolean,
  onMove: (target: CardTarget) => void,
): MenuItem[] {
  const { listId, index } = currentTarget(state, card);
  const last = (state.cardsByList[listId] ?? []).length - 1;
  const at = (to: number): CardTarget => ({ listId, index: to });
  const top = "Already at the top";
  const bottom = "Already at the bottom";
  return [
    moveItem("Move up", index > 0 ? at(index - 1) : null, top, readOnly, onMove),
    moveItem("Move down", index < last ? at(index + 1) : null, bottom, readOnly, onMove),
    moveItem("Move to top", index > 0 ? at(0) : null, top, readOnly, onMove),
    moveItem("Move to bottom", index < last ? at(last) : null, bottom, readOnly, onMove),
    ...state.lists
      .filter((list) => list.id !== listId)
      .map((list) =>
        moveItem(
          `Move to ${list.name}`,
          { listId: list.id, index: (state.cardsByList[list.id] ?? []).length },
          "",
          readOnly,
          onMove,
        ),
      ),
  ];
}

/**
 * A column's moves without dragging, for its "Column actions" menu: one place to the left or to
 * the right (`onMove` gets the new index), disabled with the reason at either end.
 */
export function columnMoveItems(
  lists: readonly BoardList[],
  listId: string,
  readOnly: boolean,
  onMove: (index: number) => void,
): MenuItem[] {
  const index = columnIndex(lists, listId);
  const item = (label: string, to: number, reason: string): MenuItem =>
    readOnly || to < 0 || to >= lists.length
      ? { label, disabled: true, hint: readOnly ? READ_ONLY : reason, onSelect: () => undefined }
      : { label, onSelect: () => onMove(to) };
  return [
    item("Move left", index - 1, "Already the first column"),
    item("Move right", index < 0 ? -1 : index + 1, "Already the last column"),
  ];
}
