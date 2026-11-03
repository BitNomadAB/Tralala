/** What a draggable or droppable on a Loop's board carries in its dnd-kit `data`. */
export type DragData =
  | { type: "card"; cardId: string; listId: string }
  | { type: "list"; listId: string }
  | { type: "list-body"; listId: string };

/** The board's own drag data, read from dnd-kit's untyped `data.current`; anything else is undefined. */
export function dragData(data: Record<string, unknown> | undefined): DragData | undefined {
  if (!data || typeof data.listId !== "string") return undefined;
  if (data.type === "card") {
    return typeof data.cardId === "string"
      ? { type: "card", cardId: data.cardId, listId: data.listId }
      : undefined;
  }
  if (data.type === "list" || data.type === "list-body") {
    return { type: data.type, listId: data.listId };
  }
  return undefined;
}
