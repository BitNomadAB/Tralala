import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Menu, type MenuItem } from "@/components/ui/menu";
import type { BoardList, Card } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { DragData } from "./dragData";
import { TicketCard } from "./TicketCard";
import type { CardControl, ColumnControl } from "./useKanbanMoves";

/**
 * One column of the Loop's Kanban: its name and count, the cards, and "Add card" at the bottom. A
 * column named Done is a column like any other; only completing a Ticket completes it. Renaming,
 * moving left or right (`moveItems`) and archiving sit in the column's quiet menu; each card's own
 * menu holds `cardActions(card)`. `focus` and `focusCard` hand the focus to this column's grip or
 * menu button, or to a card's control, after a move (see `useKanbanMoves`).
 */
export function KanbanColumn({
  list,
  cards,
  emptyText,
  readOnly,
  moveItems,
  cardActions,
  focusCard,
  onCardFocused,
  focus,
  onFocused,
  onOpenCard,
  onCreateCard,
  onRename,
  onArchive,
}: {
  list: BoardList;
  cards: Card[];
  emptyText: string;
  readOnly: boolean;
  moveItems: readonly MenuItem[];
  cardActions: (card: Card) => readonly MenuItem[];
  focusCard: { cardId: string; control: CardControl } | null;
  onCardFocused: () => void;
  focus: ColumnControl | null;
  onFocused: () => void;
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
  const header = useRef<HTMLElement>(null);
  const footer = useRef<HTMLDivElement>(null);
  // Which button takes the focus once an inline form has closed (WCAG 2.4.3): "Add card" after a
  // new card or a cancel, the column's menu after a rename. The form's field is gone by then.
  const refocus = useRef<"add" | "menu" | null>(null);
  // Escape ends a rename without saving, even if the field reports a blur as it goes.
  const renameCancelled = useRef(false);

  useEffect(() => {
    const target = refocus.current;
    if (target === null) return;
    refocus.current = null;
    const button =
      target === "add"
        ? footer.current?.querySelector<HTMLElement>("button")
        : header.current?.querySelector<HTMLElement>('[aria-haspopup="menu"]');
    button?.focus();
  });

  // The column moved (or the one before it went): its grip or menu takes the focus back.
  useEffect(() => {
    if (focus === null) return;
    const selector = focus === "grip" ? "[data-column-grip]" : '[aria-haspopup="menu"]';
    header.current?.querySelector<HTMLElement>(selector)?.focus();
    onFocused();
  }, [focus, onFocused]);

  async function submitCard() {
    if (!title.trim()) return;
    await onCreateCard(title.trim());
    closeAdding();
  }

  function closeAdding() {
    refocus.current = "add";
    setTitle("");
    setAdding(false);
  }

  /** Saves a changed name; after Enter (`refocusMenu`) the focus is on the menu, after a blur not. */
  function finishRename(refocusMenu: boolean) {
    if (renameCancelled.current) return;
    if (name.trim() && name.trim() !== list.name) onRename(name.trim());
    if (refocusMenu) refocus.current = "menu";
    setRenaming(false);
  }

  return (
    <section
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      aria-label={`Column ${list.name}`}
      className={cn(
        "flex h-full w-[280px] shrink-0 flex-col rounded-[10px] border border-[var(--border-soft)] bg-[var(--surface)]",
        isDragging && "opacity-60",
      )}
    >
      <header ref={header} className="flex items-center gap-1.5 px-2.5 pt-2.5">
        <button
          type="button"
          // 24 px square: the smallest target WCAG 2.5.8 allows.
          className="inline-flex size-6 shrink-0 cursor-grab items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
          data-column-grip=""
          aria-label={`Reorder column ${list.name}`}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={14} aria-hidden="true" />
        </button>
        {renaming ? (
          <form
            className="flex-1"
            onSubmit={(event) => {
              event.preventDefault();
              finishRename(true);
            }}
          >
            <Input
              value={name}
              autoFocus
              aria-label={`Rename column ${list.name}`}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => finishRename(false)}
              onKeyDown={(event) => {
                if (event.key !== "Escape") return;
                renameCancelled.current = true;
                refocus.current = "menu";
                setRenaming(false);
              }}
              className="h-7 text-sm"
            />
          </form>
        ) : (
          // A long name wraps instead of being cut off (WCAG 1.4.10).
          <h2 className="m-0 flex min-w-0 flex-1 items-baseline justify-between gap-2 text-[13px] font-semibold text-[var(--muted-foreground)]">
            <span className="min-w-0 break-words">{list.name}</span>
            <span className="shrink-0 tabular-nums text-[var(--foreground-faint)]">
              {cards.length}
            </span>
          </h2>
        )}
        <Menu
          label={`Column actions for ${list.name}`}
          items={[
            {
              label: "Rename column",
              disabled: readOnly,
              hint: readOnly ? "The Loop is read-only" : undefined,
              onSelect: () => {
                renameCancelled.current = false;
                setName(list.name);
                setRenaming(true);
              },
            },
            ...moveItems,
            {
              label: "Archive column",
              danger: true,
              disabled: readOnly,
              hint: readOnly ? "The Loop is read-only" : undefined,
              onSelect: onArchive,
            },
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
              <TicketCard
                key={card.id}
                card={card}
                onOpen={onOpenCard}
                actions={cardActions(card)}
                focus={focusCard?.cardId === card.id ? focusCard.control : null}
                onFocused={onCardFocused}
              />
            ))}
          </ul>
        </SortableContext>
        {cards.length === 0 ? (
          <p className="px-1 py-3 text-center text-xs text-[var(--foreground-faint)]">
            {emptyText}
          </p>
        ) : null}
      </div>

      <div ref={footer} className="px-2.5 pb-2.5">
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
                if (event.key === "Escape") closeAdding();
              }}
              className="mb-1.5"
            />
            <div className="flex gap-1.5">
              <Button size="sm" type="submit" disabled={!title.trim()}>
                Add card
              </Button>
              <Button size="sm" variant="ghost" onClick={closeAdding}>
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
            // The Ticket's dialog hands the focus here once it archived a card of this column.
            data-focus-target="add-card"
            onClick={() => setAdding(true)}
          >
            <Plus size={14} aria-hidden="true" /> Add card
          </Button>
        )}
      </div>
    </section>
  );
}
