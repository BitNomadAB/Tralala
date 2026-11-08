import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { pathsDrafts, pathsPayload } from "@/features/boards/repositoryPaths";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Board } from "@/lib/types";
import type { BoardEditDraft } from "./EditBoardDialog";

/** "Edit board": the draft the dialog edits, opened from the board as it is, and its save. */
export function useBoardEditing(boardId: string) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<BoardEditDraft>({
    name: "",
    description: "",
    repositoryIds: [],
    repositoryPaths: {},
    agentIds: [],
  });

  const save = useMutation({
    mutationFn: () =>
      api.updateBoard(boardId, {
        name: draft.name.trim(),
        description: draft.description,
        repository_ids: draft.repositoryIds,
        repository_paths: pathsPayload(draft.repositoryPaths, draft.repositoryIds),
        agent_ids: draft.agentIds,
      }),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: keys.board(boardId) });
      void queryClient.invalidateQueries({ queryKey: ["boards"] });
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      toast.push({ title: "Board updated", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not update the board",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return {
    open: (board: Board) => {
      setDraft({
        name: board.name,
        description: board.description,
        repositoryIds: board.repository_ids,
        repositoryPaths: pathsDrafts(board.repository_paths),
        agentIds: board.agent_ids,
      });
      setEditing(true);
    },
    /** The props `EditBoardDialog` takes. */
    dialog: {
      open: editing,
      onOpenChange: setEditing,
      draft,
      onDraftChange: setDraft,
      saving: save.isPending,
      onSave: () => {
        save.mutate();
      },
    },
  };
}
