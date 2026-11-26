import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import {
  newDiscussionRequest,
  newestFirst,
  type BoardDiscussionFilter,
} from "./boardDiscussionRules";
import { ASK_NOT_STARTED } from "./inboxRules";

/**
 * The board's own discussions as its page lists them: the threads with no Ticket under the
 * filter (open or closed), newest activity first, and whether "New discussion" is open.
 */
export function useBoardDiscussions(boardId: string) {
  const [filter, setFilter] = useState<BoardDiscussionFilter>("open");
  const [creating, setCreating] = useState(false);
  const query = useQuery({
    queryKey: keys.boardDiscussions(boardId, filter),
    queryFn: () => api.listDiscussions(boardId, { scope: "board", state: filter }),
    enabled: Boolean(boardId),
    select: newestFirst,
  });
  return { query, filter, setFilter, creating, setCreating };
}

export interface NewDiscussionInput {
  title: string;
  question: string;
  participantIds: readonly string[];
}

/**
 * "Create" in "New discussion": opens the thread on the board and, with agents chosen, starts one
 * round in the background, as "Ask the agents" does; without agents no round starts. The board's
 * lists and the inbox are read again and `onCreated` gets the new thread's id to open it. A round
 * that cannot start still opens the thread, with a toast that says why; a thread that cannot be
 * created leaves the dialog open with the error.
 */
export function useNewDiscussion(boardId: string, onCreated: (id: string) => void) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: async ({ title, question, participantIds }: NewDiscussionInput) => {
      const created = await api.createBoardDiscussion(
        boardId,
        newDiscussionRequest(title, question, participantIds),
      );
      if (participantIds.length === 0) return created.id;
      try {
        await api.startDiscussion(boardId, created.id, { rounds: 1, background: true });
      } catch (error) {
        toast.push({
          title: ASK_NOT_STARTED,
          description: describeError(error, undefined),
          variant: "error",
        });
      }
      return created.id;
    },
    onSuccess: (id) => {
      void queryClient.invalidateQueries({ queryKey: keys.discussions(boardId) });
      void queryClient.invalidateQueries({ queryKey: keys.discussionInbox });
      onCreated(id);
    },
  });
}
