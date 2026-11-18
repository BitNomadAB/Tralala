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
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { BoardList, Card } from "@/lib/types";
import { dragData } from "./dragData";
import { KANBAN_INSTRUCTIONS, kanbanAnnouncements } from "./kanbanAnnouncements";
import { KanbanColumn } from "./KanbanColumn";
import { currentTarget, dropTarget, findCard, type CardTarget } from "./kanbanMoves";
import { LIST_LIMIT } from "./loopUi";
import { TicketCard } from "./TicketCard";

/**
 * The Loop's columns with drag and drop: a card moves between columns optimistically, a column moves
 * by position. `children` is the slot after the last column ("Add column").
 */
export function LoopKanban({
  boardId,
  loopId,
  lists,
  cardsByList,
  matchingIds,
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
  readOnly: boolean;
  onOpenCard: (cardId: string) => void;
  onListsChanged: () => void;
  onCardsChanged: () => void;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
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
      onListsChanged();
      toast.push({
        title: "Could not archive column",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const moveListMutation = useMutation({
    mutationFn: ({ listId, position }: { listId: string; position: number }) =>
      api.moveList(boardId, loopId, listId, position),
    onSuccess: onListsChanged,
    onError: () => {
      onListsChanged();
      toast.push({ title: "Could not reorder columns", variant: "error" });
    },
  });

  const moveCardMutation = useMutation({
    mutationFn: ({ card, listId, position }: { card: Card; listId: string; position: number }) =>
      api.moveCard(boardId, loopId, card.id, {
        version: card.version,
        list_id: listId,
        position,
      }),
    onSettled: onCardsChanged,
    onError: (error) => {
      onCardsChanged();
      toast.push({
        title: "Could not move ticket",
        description:
          error instanceof ApiError && error.code === "version_conflict"
            ? "The ticket changed elsewhere. The loop has been refreshed."
            : describeError(error, undefined),
        variant: "error",
      });
    },
  });

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
    if (data?.type === "card") setActiveCard(findCard({ lists, cardsByList }, data.cardId) ?? null);
  }

  /** Moves the card at once on screen, then on the server; a refusal reloads the columns. */
  function moveCard(card: Card, target: CardTarget) {
    const targetCards = (cardsByList[target.listId] ?? []).filter((item) => item.id !== card.id);
    const sourceCards = (cardsByList[card.list_id] ?? []).filter((item) => item.id !== card.id);
    queryClient.setQueryData<Card[]>(
      keys.listCards(boardId, loopId, card.list_id, LIST_LIMIT),
      sourceCards,
    );
    queryClient.setQueryData<Card[]>(
      keys.listCards(boardId, loopId, target.listId, LIST_LIMIT),
      () => {
        const next = [...targetCards];
        next.splice(target.index, 0, { ...card, list_id: target.listId });
        return next;
      },
    );
    moveCardMutation.mutate({ card, listId: target.listId, position: target.index });
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
      moveListMutation.mutate({ listId: activeData.listId, position: toIndex });
      return;
    }

    if (activeData?.type !== "card") return;
    const state = { lists, cardsByList };
    const card = findCard(state, activeData.cardId);
    const target = card ? dropTarget(state, card, overData) : null;
    if (!card || !target) return;
    // Dropped where it was: nothing to store.
    const here = currentTarget(state, card);
    if (target.listId === here.listId && target.index === here.index) return;
    moveCard(card, target);
  }

  return (
    <div className="flex min-h-0 flex-1 gap-4">
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
          {lists.map((list: BoardList) => {
            const allCards = cardsByList[list.id] ?? [];
            const cards = matchingIds
              ? allCards.filter((card) => matchingIds.has(card.id))
              : allCards;
            return (
              <div key={list.id} className="h-full">
                <KanbanColumn
                  list={list}
                  cards={cards}
                  readOnly={readOnly}
                  onOpenCard={(card) => onOpenCard(card.id)}
                  onCreateCard={async (title) => {
                    await createCardMutation.mutateAsync({ listId: list.id, title });
                  }}
                  onRename={(name) => renameListMutation.mutate({ listId: list.id, name })}
                  onArchive={() => archiveListMutation.mutate(list.id)}
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
