import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { CardDetail, ChecklistItem } from "@/lib/types";

/** The card with one checklist item ticked or unticked, as the server will answer it. */
export function withItemToggled(card: CardDetail, itemId: string): CardDetail {
  return {
    ...card,
    checklists: (card.checklists ?? []).map((checklist) => ({
      ...checklist,
      items: checklist.items.map((item) =>
        item.id === itemId ? { ...item, completed: !item.completed } : item,
      ),
    })),
  };
}

/**
 * The card's checklist forms and mutations. Called by the dialog, so text typed into a form lives
 * as long as the dialog does. A tick shows at once (the checkbox a person just pressed reads its
 * new state), and the refetch afterwards puts back what the server holds, also after a refusal.
 */
export function useCardChecklists({
  boardId,
  loopId,
  cardId,
  refresh,
  onError,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  refresh: () => void;
  onError: (error: unknown) => void;
}) {
  const queryClient = useQueryClient();
  const [checklistTitle, setChecklistTitle] = useState("");
  const [itemText, setItemText] = useState<Record<string, string>>({});

  const checklistMutation = useMutation({
    mutationFn: (title: string) => api.addChecklist(boardId, loopId, cardId, title),
    onSuccess: () => {
      setChecklistTitle("");
      refresh();
    },
    onError,
  });

  const itemMutation = useMutation({
    mutationFn: ({ checklistId, text }: { checklistId: string; text: string }) =>
      api.addChecklistItem(boardId, checklistId, text),
    onSuccess: () => {
      setItemText({});
      refresh();
    },
    onError,
  });

  const toggleItemMutation = useMutation({
    mutationFn: (item: ChecklistItem) =>
      api.updateChecklistItem(boardId, item.id, { completed: !item.completed }),
    onMutate: (item: ChecklistItem) => {
      queryClient.setQueryData<CardDetail>(keys.card(boardId, loopId, cardId), (current) =>
        current ? withItemToggled(current, item.id) : current,
      );
    },
    onSuccess: refresh,
    onError,
  });

  return {
    checklistTitle,
    setChecklistTitle,
    itemText,
    changeItemText: (checklistId: string, text: string) => {
      setItemText((current) => ({ ...current, [checklistId]: text }));
    },
    addChecklist: (title: string) => {
      checklistMutation.mutate(title);
    },
    addItem: (checklistId: string, text: string) => {
      itemMutation.mutate({ checklistId, text });
    },
    toggleItem: (item: ChecklistItem) => {
      toggleItemMutation.mutate(item);
    },
  };
}
