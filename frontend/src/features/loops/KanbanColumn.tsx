import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import type { BoardList, Card } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { DragData } from "./dragData";
import { TicketCard } from "./TicketCard";

/**
 * One column of the Loop's Kanban: its name and count, the cards, and "Add card" at the bottom. A
 * column named Done is a column like any other; only completing a Ticket completes it. Renaming and
 * archiving sit in the column's quiet menu.
 */
export function KanbanColumn({
  list,
  cards,
  readOnly,
  onOpenCard,
  onCreateCard,
  onRename,
  onArchive,
}: {
  list: BoardList;
  cards: Card[];
  readOnly: boolean;
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

  async function submitCard() {
    if (!title.trim()) return;
    await onCreateCard(title.trim());
    setTitle("");
    setAdding(false);
  }

  function finishRename() {
    if (name.trim() && name.trim() !== list.name) onRename(name.trim());
    setRenaming(false);
  }

  return (
    <section
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      aria-label={`List ${list.name}`}
      className={cn(
        "flex h-full w-[280px] shrink-0 flex-col rounded-[10px] border border-[var(--border-soft)] bg-[var(--surface)]",
        isDragging && "opacity-60",
      )}
    >
      <header className="flex items-center gap-1.5 px-2.5 pt-2.5">
        <button
          type="button"
          className="cursor-grab text-[var(--foreground-faint)] hover:text-[var(--muted-foreground)]"
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
              finishRename();
            }}
          >
            <Input
              value={name}
              autoFocus
              aria-label={`Rename list ${list.name}`}
              onChange={(event) => setName(event.target.value)}
              onBlur={finishRename}
              className="h-7 text-sm"
            />
          </form>
        ) : (
          <h2 className="m-0 flex flex-1 items-baseline justify-between gap-2 truncate text-[13px] font-semibold text-[var(--muted-foreground)]">
            <span className="truncate">{list.name}</span>
            <span className="tabular-nums text-[var(--foreground-faint)]">{cards.length}</span>
          </h2>
        )}
        <Menu
          label={`Column actions for ${list.name}`}
          items={[
            {
              label: "Rename column",
              disabled: readOnly,
              onSelect: () => {
                setName(list.name);
                setRenaming(true);
              },
            },
            { label: "Archive column", danger: true, disabled: readOnly, onSelect: onArchive },
          ]}
        />
      </header>

      <div
        ref={setBodyRef}
        className={cn(
          "scrollbar-thin mt-2 flex min-h-[60px] flex-1 flex-col gap-2 overflow-y-auto px-2.5 pb-2",
          isOver && "bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]",
        )}
      >
        <SortableContext
          items={cards.map((card) => card.id)}
          strategy={verticalListSortingStrategy}
        >
          <ul className="flex flex-col gap-2">
            {cards.map((card) => (
              <TicketCard key={card.id} card={card} onOpen={onOpenCard} />
            ))}
          </ul>
        </SortableContext>
        {cards.length === 0 ? (
          <p className="px-1 py-3 text-center text-xs text-[var(--foreground-faint)]">
            Drop cards here
          </p>
        ) : null}
      </div>

      <div className="px-2.5 pb-2.5">
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
            variant="quiet"
            size="sm"
            className="w-full justify-start"
            disabled={readOnly}
            onClick={() => setAdding(true)}
          >
            <Plus size={14} aria-hidden="true" /> Add card
          </Button>
        )}
      </div>
    </section>
  );
}
