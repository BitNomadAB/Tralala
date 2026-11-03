import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { BoardList, Card } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CardTile } from "./CardTile";
import type { DragData } from "./dragData";

export function ListColumn({
  list,
  cards,
  onOpenCard,
  onCreateCard,
  onRename,
  onArchive,
}: {
  list: BoardList;
  cards: Card[];
  onOpenCard: (card: Card) => void;
  onCreateCard: (title: string) => Promise<void>;
  onRename: (name: string) => void;
  onArchive: () => void;
}) {
  // Destructured, so the ref callbacks stay separate from the values read while rendering.
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: list.id,
    data: { type: "list", listId: list.id } satisfies DragData,
  });
  const { setNodeRef: setBodyRef, isOver } = useDroppable({
    id: `list-body:${list.id}`,
    data: { type: "list-body", listId: list.id } satisfies DragData,
  });
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(list.name);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  async function submitCard() {
    if (!title.trim()) return;
    await onCreateCard(title.trim());
    setTitle("");
    setAdding(false);
  }

  return (
    <section
      ref={setNodeRef}
      style={style}
      aria-label={`List ${list.name}`}
      className={cn(
        "flex h-full w-[300px] shrink-0 flex-col rounded-xl border border-[var(--border)] bg-[color-mix(in_srgb,var(--surface)_65%,transparent)]",
        isDragging && "opacity-60",
      )}
    >
      <header className="flex items-center gap-1.5 px-3 pt-3">
        <button
          type="button"
          className="cursor-grab text-[var(--muted-foreground)]"
          aria-label={`Reorder list ${list.name}`}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={14} />
        </button>
        {renaming ? (
          <form
            className="flex-1"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim() && name.trim() !== list.name) onRename(name.trim());
              setRenaming(false);
            }}
          >
            <Input
              value={name}
              autoFocus
              aria-label={`Rename list ${list.name}`}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => {
                if (name.trim() && name.trim() !== list.name) onRename(name.trim());
                setRenaming(false);
              }}
              className="h-7 text-sm"
            />
          </form>
        ) : (
          <button
            type="button"
            onDoubleClick={() => setRenaming(true)}
            onClick={() => setRenaming(true)}
            className="flex-1 truncate text-left text-sm font-semibold"
            title="Rename list"
          >
            {list.name}
          </button>
        )}
        <span className="text-[11px] text-[var(--muted-foreground)]">{cards.length}</span>
        <Button
          size="icon"
          variant="ghost"
          title={`Archive list ${list.name}`}
          aria-label={`Archive list ${list.name}`}
          onClick={onArchive}
        >
          <span aria-hidden>×</span>
        </Button>
      </header>

      <div
        ref={setBodyRef}
        className={cn(
          "scrollbar-thin mt-2 flex min-h-[60px] flex-1 flex-col gap-2 overflow-y-auto px-2.5 pb-2",
          isOver && "bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]",
        )}
      >
        <SortableContext items={cards.map((card) => card.id)} strategy={verticalListSortingStrategy}>
          <ul className="flex flex-col gap-2">
            {cards.map((card) => (
              <CardTile key={card.id} card={card} onOpen={onOpenCard} />
            ))}
          </ul>
        </SortableContext>
        {cards.length === 0 ? (
          <p className="px-1 py-3 text-center text-[11px] text-[var(--muted-foreground)]">
            Drop cards here
          </p>
        ) : null}
      </div>

      <div className="p-2.5 pt-0">
        {adding ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submitCard();
            }}
          >
            <Input
              autoFocus
              value={title}
              aria-label={`New card in ${list.name}`}
              placeholder="Card title"
              onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setAdding(false);
                  setTitle("");
                }
              }}
              className="mb-1.5"
            />
            <div className="flex gap-1.5">
              <Button size="sm" type="submit" disabled={!title.trim()}>
                Add card
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setAdding(false);
                  setTitle("");
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={() => setAdding(true)}
          >
            <Plus size={14} /> Add card
          </Button>
        )}
      </div>
    </section>
  );
}
