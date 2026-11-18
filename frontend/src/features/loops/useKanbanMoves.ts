import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { BoardList, Card } from "@/lib/types";
import { placeText } from "./kanbanAnnouncements";
import { columnIndex, placeAt, type CardTarget } from "./kanbanMoves";
import { LIST_LIMIT } from "./loopUi";

/** Which of a card's controls takes the focus once the card shows at its new place. */
export type CardControl = "grip" | "actions";

/** A card's control to focus, once the card is at `listId`/`index`. */
interface CardFocus extends CardTarget {
  cardId: string;
  control: CardControl;
}

/** A column's menu button to focus, once `ready` holds for the columns shown. */
interface ColumnFocus {
  listId: string;
  ready: (lists: readonly BoardList[]) => boolean;
}

/** How a move tells the person: announce the new place, and which control keeps the focus. */
interface MoveOptions<Control> {
  announce?: boolean;
  focus?: Control;
}

/**
 * Moving cards and columns, by a drag or from a menu. A card moves at once on screen and then on
 * the server; a column moves on the server and shows the stored order. A move from a menu says
 * the new place (WCAG 4.1.3). A moved card or column is rendered anew where it lands, so the focus
 * would fall to the page: the request kept here is handed to the card or column (`cardFocus`,
 * `columnFocus`) once it shows at its new place, and the one that took it clears it.
 */
export function useKanbanMoves({
  boardId,
  loopId,
  lists,
  cardsByList,
  onListsChanged,
  onCardsChanged,
}: {
  boardId: string;
  loopId: string;
  lists: BoardList[];
  cardsByList: Record<string, Card[]>;
  onListsChanged: () => void;
  onCardsChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const announce = useAnnounce();
  const [cardFocus, setCardFocus] = useState<CardFocus | null>(null);
  const [columnFocus, setColumnFocus] = useState<ColumnFocus | null>(null);

  const moveListMutation = useMutation({
    mutationFn: ({ listId, position }: { listId: string; position: number }) =>
      api.moveList(boardId, loopId, listId, position),
    onSuccess: onListsChanged,
    onError: () => {
      setColumnFocus(null);
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
      // The card goes back where the server keeps it; the focus stays where it is now.
      setCardFocus(null);
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

  function moveCard(card: Card, target: CardTarget, options: MoveOptions<CardControl> = {}) {
    const state = { lists, cardsByList };
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
    if (options.announce) {
      announce(`${card.title} moved to ${placeText(placeAt(state, card, target))}.`);
    }
    if (options.focus) setCardFocus({ ...target, cardId: card.id, control: options.focus });
    moveCardMutation.mutate({ card, listId: target.listId, position: target.index });
  }

  function moveColumn(listId: string, index: number, options: MoveOptions<true> = {}) {
    const list = lists.find((item) => item.id === listId);
    if (options.announce && list) {
      announce(`Column ${list.name} moved to position ${index + 1} of ${lists.length}.`);
    }
    if (options.focus) {
      setColumnFocus({ listId, ready: (shown) => columnIndex(shown, listId) === index });
    }
    moveListMutation.mutate({ listId, position: index });
  }

  /** Focuses the menu button of column `listId` once `ready` holds for the columns shown. */
  const focusColumn = useCallback((listId: string, ready: ColumnFocus["ready"]) => {
    setColumnFocus({ listId, ready });
  }, []);
  const cardFocused = useCallback(() => {
    setCardFocus(null);
  }, []);
  const columnFocused = useCallback(() => {
    setColumnFocus(null);
  }, []);

  const cardFocusNow =
    cardFocus && cardsByList[cardFocus.listId]?.[cardFocus.index]?.id === cardFocus.cardId
      ? cardFocus
      : null;

  return {
    moveCard,
    moveColumn,
    focusColumn,
    cardFocus: cardFocusNow,
    columnFocus: columnFocus?.ready(lists) ? columnFocus.listId : null,
    cardFocused,
    columnFocused,
  };
}
