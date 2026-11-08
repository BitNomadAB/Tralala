import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import { ASK_NOT_STARTED, askRequest } from "./inboxRules";

export interface AskInput {
  question: string;
  participantIds: readonly string[];
}

/**
 * "Ask" from a Ticket, as a worker's `ask_agents` does it: create a roundtable on the Ticket with
 * the chosen agents and the default round cap, then start one round. The Ticket's discussions and
 * the inbox are read again, and `onAsked` gets the new thread's id to open it. A round that cannot
 * start still opens the thread, with a toast that says why; a thread that cannot be created
 * leaves the dialog open with the error.
 */
export function useAskAgents(boardId: string, cardId: string, onAsked: (id: string) => void) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: async ({ question, participantIds }: AskInput) => {
      const created = await api.createDiscussion(
        boardId,
        askRequest(cardId, question, participantIds),
      );
      try {
        await api.startDiscussion(boardId, created.id, { rounds: 1 });
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
      onAsked(id);
    },
  });
}
