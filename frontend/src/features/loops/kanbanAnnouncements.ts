import type { Announcements, ScreenReaderInstructions } from "@dnd-kit/core";
import { dragData, type DragData } from "./dragData";
import {
  columnIndex,
  currentTarget,
  dropTarget,
  findCard,
  placeAt,
  type KanbanState,
  type Place,
} from "./kanbanMoves";

/** A moment of a drag that dnd-kit announces. */
export type DragMoment = "start" | "over" | "end" | "cancel";

/** A place in words: "In Progress, position 2 of 5". */
export function placeText(place: Place): string {
  return `${place.column}, position ${place.position} of ${place.count}`;
}

/** What a screen reader hears while a card moves: its title, the column it is over and where. */
function cardText(
  state: KanbanState,
  moment: DragMoment,
  cardId: string,
  over: DragData | undefined,
): string | undefined {
  const card = findCard(state, cardId);
  if (!card) return undefined;
  const here = placeText(placeAt(state, card, currentTarget(state, card)));
  const target = dropTarget(state, card, over);
  const there = target ? placeText(placeAt(state, card, target)) : null;
  switch (moment) {
    case "start":
      return `Picked up ${card.title}, in ${here}.`;
    case "over":
      return there ? `${card.title} is over ${there}.` : `${card.title} is not over a column.`;
    case "end":
      return there
        ? `${card.title} dropped in ${there}.`
        : `${card.title} was not dropped on a column and stays in ${here}.`;
    case "cancel":
      return `Moving ${card.title} was cancelled. It stays in ${here}.`;
  }
}

/** What a screen reader hears while a column moves: its name and its position among the columns. */
function columnText(
  state: KanbanState,
  moment: DragMoment,
  listId: string,
  over: DragData | undefined,
): string | undefined {
  const from = columnIndex(state.lists, listId);
  const list = state.lists[from];
  if (!list) return undefined;
  const count = state.lists.length;
  const to = over ? columnIndex(state.lists, over.listId) : -1;
  const stays = `It stays at position ${from + 1} of ${count}.`;
  switch (moment) {
    case "start":
      return `Picked up column ${list.name}, position ${from + 1} of ${count}.`;
    case "over":
      return to < 0
        ? `Column ${list.name} is not over a column.`
        : `Column ${list.name} is over position ${to + 1} of ${count}.`;
    case "end":
      return to < 0
        ? `Column ${list.name} was not dropped on a column. ${stays}`
        : `Column ${list.name} dropped at position ${to + 1} of ${count}.`;
    case "cancel":
      return `Moving column ${list.name} was cancelled. ${stays}`;
  }
}

/**
 * One sentence for a moment of a drag on the Kanban (WCAG 4.1.3): the Ticket's title or the
 * column's name, never its id, and where it is. Undefined for anything that is not the board's.
 */
export function dragText(
  state: KanbanState,
  moment: DragMoment,
  active: DragData | undefined,
  over: DragData | undefined,
): string | undefined {
  if (active?.type === "card") return cardText(state, moment, active.cardId, over);
  if (active?.type === "list") return columnText(state, moment, active.listId, over);
  return undefined;
}

/** dnd-kit's announcements for the Kanban `state`, read from the drag's own data. */
export function kanbanAnnouncements(state: KanbanState): Announcements {
  return {
    onDragStart: ({ active }) => dragText(state, "start", dragData(active.data.current), undefined),
    onDragOver: ({ active, over }) =>
      dragText(state, "over", dragData(active.data.current), dragData(over?.data.current)),
    onDragEnd: ({ active, over }) =>
      dragText(state, "end", dragData(active.data.current), dragData(over?.data.current)),
    onDragCancel: ({ active }) =>
      dragText(state, "cancel", dragData(active.data.current), undefined),
  };
}

/** What a screen reader says about every grip on the Kanban: how to move with the keyboard. */
export const KANBAN_INSTRUCTIONS: ScreenReaderInstructions = {
  draggable:
    "To move a Ticket or a column, press Space or Enter on its grip to pick it up. Use the arrow " +
    "keys to move it: up and down within a column, left and right to another column. Press Space " +
    "or Enter to drop it there, or Escape to cancel. The actions menu of a Ticket or a column " +
    "moves it without dragging.",
};
