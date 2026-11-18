import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { BoardList, Card } from "@/lib/types";
import { menuMoveText } from "./kanbanAnnouncements";
import { columnIndex, restoreIndex, type CardTarget } from "./kanbanMoves";
import { LIST_LIMIT } from "./loopUi";

/** Which of a card's controls takes the focus once the card shows at its new place. */
export type CardControl = "grip" | "actions";

/** Which of a column's controls takes the focus once the column shows at its new place. */
export type ColumnControl = "grip" | "menu";

/** A card's control to focus, once the card is at `listId`/`index`. */
interface CardFocus extends CardTarget {
  cardId: string;
  control: CardControl;
}

/** A column's control to focus, once `ready` holds for the columns shown. */
interface ColumnFocus {
  listId: string;
  control: ColumnControl;
  ready: (lists: readonly BoardList[]) => boolean;
}

/** An archived column and where it stood: the column before it (null when first) and its index. */
interface ArchivedColumn {
  list: BoardList;
  after: string | null;
  index: number;
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
 * `columnFocus`) once it shows at its new place, and the one that took it clears it. Archiving a
 * column acts at once and its toast offers Undo, which brings it back where it stood (WCAG 3.3.4).
 * A card's moves are sent one after another, each with the version the server gave the one before,
 * so a second move from the menu before the board is read again is no version conflict.
 */
export function useKanbanMoves({
  boardId,
  loopId,
  lists,
  cardsByList,
  filtered,
  onListsChanged,
  onCardsChanged,
}: {
  boardId: string;
  loopId: string;
  lists: BoardList[];
  cardsByList: Record<string, Card[]>;
  /** A filter hides cards: a move's announcement names the column alone. */
  filtered: boolean;
  onListsChanged: () => void;
  onCardsChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const announce = useAnnounce();
  const [cardFocus, setCardFocus] = useState<CardFocus | null>(null);
  const [columnFocus, setColumnFocus] = useState<ColumnFocus | null>(null);
  // The columns shown now, for an Undo pressed after they changed.
  const shownLists = useRef(lists);
  useEffect(() => {
    shownLists.current = lists;
  });
  // The version each card's last move returned; a move sends the newer of it and the board's.
  const movedVersions = useRef(new Map<string, number>());

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

  const archiveListMutation = useMutation({
    mutationFn: ({ list }: ArchivedColumn) => api.archiveList(boardId, loopId, list.id),
    onSuccess: (_archived, archived) => {
      const { list } = archived;
      onListsChanged();
      onCardsChanged();
      toast.push({
        title: "Column archived",
        description: `${list.name} and its Tickets no longer show.`,
        variant: "success",
        action: { label: "Undo", onClick: () => restoreListMutation.mutate(archived) },
      });
    },
    onError: (error) => {
      setColumnFocus(null);
      onListsChanged();
      toast.push({
        title: "Could not archive column",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const restoreListMutation = useMutation({
    mutationFn: async ({ list, after, index }: ArchivedColumn) => {
      await api.restoreList(boardId, loopId, list.id);
      // Restoring makes it the last column, so it is moved back to where it stood.
      const others = shownLists.current.filter((item) => item.id !== list.id);
      const position = restoreIndex(others, after, index);
      await api.moveList(boardId, loopId, list.id, position);
      return position;
    },
    onSuccess: (position, { list }) => {
      // The Undo button left with its toast; the column's menu takes the focus once it is back.
      setColumnFocus({
        listId: list.id,
        control: "menu",
        ready: (shown) => columnIndex(shown, list.id) === position,
      });
      onListsChanged();
      onCardsChanged();
      toast.push({ title: "Column restored", description: list.name, variant: "success" });
    },
    onError: (error) => {
      onListsChanged();
      onCardsChanged();
      toast.push({
        title: "Could not restore the column where it was",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const moveCardMutation = useMutation({
    // One after another: each move reads the version the one before it returned.
    scope: { id: `card-moves:${loopId}` },
    mutationFn: ({ card, listId, position }: { card: Card; listId: string; position: number }) =>
      api.moveCard(boardId, loopId, card.id, {
        // Versions only grow: the newer of the board's and the last move's.
        version: Math.max(card.version, movedVersions.current.get(card.id) ?? 0),
        list_id: listId,
        position,
      }),
    onSuccess: (moved) => {
      movedVersions.current.set(moved.id, moved.version);
    },
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
      announce(menuMoveText(state, card, target, filtered));
    }
    if (options.focus) setCardFocus({ ...target, cardId: card.id, control: options.focus });
    moveCardMutation.mutate({ card, listId: target.listId, position: target.index });
  }

  function moveColumn(listId: string, index: number, options: MoveOptions<ColumnControl> = {}) {
    const list = lists.find((item) => item.id === listId);
    if (options.announce && list) {
      announce(`Column ${list.name} moved to position ${index + 1} of ${lists.length}.`);
    }
    const control = options.focus;
    if (control) {
      setColumnFocus({ listId, control, ready: (shown) => columnIndex(shown, listId) === index });
    }
    moveListMutation.mutate({ listId, position: index });
  }

  /** Focuses the menu button of column `listId` once `ready` holds for the columns shown. */
  const focusColumn = useCallback((listId: string, ready: ColumnFocus["ready"]) => {
    setColumnFocus({ listId, control: "menu", ready });
  }, []);

  /**
   * Archives column `list`. Focus goes on to the next column's menu (the one before, at the end),
   * as the column leaves with its own.
   */
  function archiveColumn(list: BoardList) {
    const index = columnIndex(lists, list.id);
    const next = lists[index + 1] ?? lists[index - 1];
    if (next) focusColumn(next.id, (shown) => !shown.some((item) => item.id === list.id));
    archiveListMutation.mutate({ list, after: lists[index - 1]?.id ?? null, index });
  }

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
    archiveColumn,
    cardFocus: cardFocusNow,
    columnFocus: columnFocus?.ready(lists) ? columnFocus : null,
    cardFocused,
    columnFocused,
  };
}
