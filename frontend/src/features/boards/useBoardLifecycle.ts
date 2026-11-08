import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Board } from "@/lib/types";
import type { BoardLifecycleAction } from "./BoardTile";

const DONE: Record<BoardLifecycleAction, string> = {
  archive: "Board archived",
  restore: "Board restored",
  duplicate: "Board duplicated",
};

/**
 * Archive, restore, duplicate and delete a board, as the dashboard's tiles and the board page's
 * menu offer them: each refreshes the board lists and says what happened. Deleting asks for the
 * board's name first (`deleting`, `confirmName`), as `DeleteBoardDialog` shows it.
 */
export function useBoardLifecycle({ onDeleted }: { onDeleted?: () => void } = {}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [deleting, setDeleting] = useState<Board | null>(null);
  const [confirmName, setConfirmName] = useState("");

  function refresh(board: Board) {
    void queryClient.invalidateQueries({ queryKey: ["boards"] });
    void queryClient.invalidateQueries({ queryKey: keys.board(board.id) });
  }

  const lifecycle = useMutation({
    mutationFn: async (action: { type: BoardLifecycleAction; board: Board }) => {
      if (action.type === "archive") return api.archiveBoard(action.board.id);
      if (action.type === "restore") return api.restoreBoard(action.board.id);
      return api.duplicateBoard(action.board.id);
    },
    onSuccess: (_result, action) => {
      refresh(action.board);
      toast.push({ title: DONE[action.type], variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Action failed",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const remove = useMutation({
    mutationFn: (board: Board) => api.deleteBoard(board.id, confirmName),
    onSuccess: (_result, board) => {
      refresh(board);
      setDeleting(null);
      setConfirmName("");
      toast.push({ title: "Board deleted", variant: "success" });
      onDeleted?.();
    },
    onError: (error) => {
      toast.push({
        title: "Could not delete board",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return {
    run: (type: BoardLifecycleAction, board: Board) => {
      lifecycle.mutate({ type, board });
    },
    askDelete: (board: Board) => {
      setDeleting(board);
      setConfirmName("");
    },
    /** The props `DeleteBoardDialog` takes. */
    deleteDialog: {
      board: deleting,
      confirmName,
      onConfirmNameChange: setConfirmName,
      deleting: remove.isPending,
      onDelete: (board: Board) => {
        remove.mutate(board);
      },
      onClose: () => {
        setDeleting(null);
      },
    },
  };
}
