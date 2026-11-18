import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useMutation } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { BoardList, Card } from "@/lib/types";
import { dragData } from "./dragData";
import { KANBAN_INSTRUCTIONS, kanbanAnnouncements } from "./kanbanAnnouncements";
import { KanbanColumn } from "./KanbanColumn";
import { cardMoveItems, columnMoveItems, currentTarget, dropTarget, findCard } from "./kanbanMoves";
import { TicketCard } from "./TicketCard";
import { useKanbanMoves } from "./useKanbanMoves";

/**
 * The Loop's columns with drag and drop: a card moves between columns optimistically, a column moves
 * by position. The same moves are in the card's and the column's menus, for a single pointer or a
 * keyboard without dragging (WCAG 2.5.7). `children` is the slot after the last column ("Add
 * column").
 */
export function LoopKanban({
  boardId,
  loopId,
  lists,
  cardsByList,
  matchingIds,
  emptyText = "Drop cards here",
  readOnly,
  onOpenCard,
  onListsChanged,
  onCardsChanged,
  children,
}: {
  boardId: string;
  loopId: string;
  lists: BoardList[];
  cardsByList: Record<string, Card[]>;
  matchingIds: Set<string> | null;
  /** What a column without cards says (that no Ticket matches, while the filters are set). */
  emptyText?: string;
  readOnly: boolean;
  onOpenCard: (cardId: string) => void;
  onListsChanged: () => void;
  onCardsChanged: () => void;
  children: ReactNode;
}) {
  const toast = useToast();
  const [activeCard, setActiveCard] = useState<Card | null>(null);

  const createCardMutation = useMutation({
    mutationFn: ({ listId, title }: { listId: string; title: string }) =>
      api.createCard(boardId, loopId, { list_id: listId, title }),
    onSuccess: onCardsChanged,
    onError: (error) => {
      toast.push({
        title: "Could not create ticket",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const renameListMutation = useMutation({
    mutationFn: ({ listId, name }: { listId: string; name: string }) =>
      api.renameList(boardId, loopId, listId, name),
    onSuccess: onListsChanged,
    // The column shows the stored name again, so say why the new one did not stay.
    onError: (error) => {
      onListsChanged();
      toast.push({
        title: "Could not rename column",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const archiveListMutation = useMutation({
    mutationFn: (listId: string) => api.archiveList(boardId, loopId, listId),
    onSuccess: () => {
      onListsChanged();
      onCardsChanged();
    },
    onError: (error) => {
      moves.columnFocused();
      onListsChanged();
      toast.push({
        title: "Could not archive column",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const moves = useKanbanMoves({
    boardId,
    loopId,
    lists,
    cardsByList,
    onListsChanged,
    onCardsChanged,
  });
  const state = { lists, cardsByList };

  // What a screen reader hears during a drag names the Ticket or the column and where it is.
  const accessibility = useMemo(
    () => ({
      announcements: kanbanAnnouncements({ lists, cardsByList }),
      screenReaderInstructions: KANBAN_INSTRUCTIONS,
    }),
    [lists, cardsByList],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function handleDragStart(event: DragStartEvent) {
    const data = dragData(event.active.data.current);
    if (data?.type === "card") setActiveCard(findCard(state, data.cardId) ?? null);
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveCard(null);
    const activeData = dragData(event.active.data.current);
    const over = event.over;
    if (!over) return;
    const overData = dragData(over.data.current);

    if (activeData?.type === "list") {
      const fromIndex = lists.findIndex((list) => list.id === activeData.listId);
      const overId = overData?.listId ?? over.id;
      const toIndex = lists.findIndex((list) => list.id === overId);
      if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return;
      moves.moveColumn(activeData.listId, toIndex);
      return;
    }

    if (activeData?.type !== "card") return;
    const card = findCard(state, activeData.cardId);
    const target = card ? dropTarget(state, card, overData) : null;
    if (!card || !target) return;
    // Dropped where it was: nothing to store.
    const here = currentTarget(state, card);
    if (target.listId === here.listId && target.index === here.index) return;
    // dnd-kit says where it landed; a keyboard keeps the focus on the grip of the moved card.
    const byKeyboard = event.activatorEvent instanceof KeyboardEvent;
    moves.moveCard(card, target, byKeyboard ? { focus: "grip" } : {});
  }

  return (
    // Never squeezed to a sliver when the page around it is short.
    <div className="flex min-h-56 flex-1 gap-4">
      <DndContext
        sensors={sensors}
        accessibility={accessibility}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => setActiveCard(null)}
      >
        <div
          className="scrollbar-thin flex min-h-0 flex-1 items-start gap-3 overflow-x-auto pb-2"
          role="region"
          aria-label="Loop Kanban columns"
        >
          {lists.map((list: BoardList, index) => {
            const allCards = cardsByList[list.id] ?? [];
            const cards = matchingIds
              ? allCards.filter((card) => matchingIds.has(card.id))
              : allCards;
            const focusCard = moves.cardFocus?.listId === list.id ? moves.cardFocus : null;
            return (
              <div key={list.id} className="h-full">
                <KanbanColumn
                  list={list}
                  cards={cards}
                  emptyText={emptyText}
                  readOnly={readOnly}
                  moveItems={columnMoveItems(lists, list.id, readOnly, (to) => {
                    moves.moveColumn(list.id, to, { announce: true, focus: true });
                  })}
                  cardActions={(card) =>
                    cardMoveItems(state, card, readOnly, (target) => {
                      moves.moveCard(card, target, { announce: true, focus: "actions" });
                    })
                  }
                  focusCard={focusCard}
                  onCardFocused={moves.cardFocused}
                  focusMenu={moves.columnFocus === list.id}
                  onMenuFocused={moves.columnFocused}
                  onOpenCard={(card) => onOpenCard(card.id)}
                  onCreateCard={async (title) => {
                    await createCardMutation.mutateAsync({ listId: list.id, title });
                  }}
                  onRename={(name) => renameListMutation.mutate({ listId: list.id, name })}
                  onArchive={() => {
                    // The focus goes on to the next column's menu (the one before, at the end).
                    const next = lists[index + 1] ?? lists[index - 1];
                    if (next) {
                      moves.focusColumn(
                        next.id,
                        (shown) => !shown.some((item) => item.id === list.id),
                      );
                    }
                    archiveListMutation.mutate(list.id);
                  }}
                />
              </div>
            );
          })}

          {children}
        </div>
        <DragOverlay dropAnimation={null}>
          {activeCard ? <TicketCard card={activeCard} overlay /> : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
