import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { ChecklistItem } from "@/lib/types";

/**
 * The card's checklist forms and mutations. Called by the dialog, so text typed into a form lives
 * as long as the dialog does.
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
