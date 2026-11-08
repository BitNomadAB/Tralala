import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Discussion } from "@/lib/types";
import { reviewedText, type ReviewDecision } from "./discussionRules";
import { useDiscussionEvents } from "./useDiscussionEvents";

/** What a saved reply did when it did not start a round, in the words of the toast. */
function replyNotice(discussion: Discussion) {
  switch (discussion.auto_run) {
    case "already_running":
      return {
        title: "The agents are already answering",
        description: "Your message is saved and joins the conversation; no second round starts.",
        variant: "info" as const,
      };
    case "thread_closed":
      return {
        title: "The discussion is closed",
        description: "The message is saved, but a closed discussion does not start a round.",
        variant: "warning" as const,
      };
    case "no_participants":
      return {
        title: "No agents in this discussion",
        description: "The message is saved; add agents before they can answer.",
        variant: "warning" as const,
      };
    default:
      return null;
  }
}

/**
 * One discussion for the view: the thread (refetched while the agents answer and the event
 * stream is down), its server-sent events, the person's decision with the review dialog, and the
 * reply that asks again.
 */
export function useDiscussionView(boardId: string, discussionId: string) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [reviewing, setReviewing] = useState<ReviewDecision | null>(null);
  const [reply, setReply] = useState("");

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.discussion(boardId, discussionId) });
    void queryClient.invalidateQueries({ queryKey: keys.discussions(boardId) });
  }, [queryClient, boardId, discussionId]);

  const live = useDiscussionEvents(boardId, discussionId, invalidate);

  const query = useQuery({
    queryKey: keys.discussion(boardId, discussionId),
    queryFn: () => api.getDiscussion(boardId, discussionId),
    enabled: Boolean(boardId && discussionId),
    refetchInterval: (current) =>
      current.state.data?.run_state === "running" && !live ? 1500 : false,
  });

  const reviewMutation = useMutation({
    mutationFn: (input: { decision: ReviewDecision; reason: string }) =>
      api.reviewDiscussion(boardId, discussionId, input),
    onSuccess: (_discussion, input) => {
      setReviewing(null);
      invalidate();
      toast.push({ title: reviewedText(input.decision), variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not record the decision",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const replyMutation = useMutation({
    mutationFn: (content: string) => api.postDiscussionMessage(boardId, discussionId, { content }),
    onSuccess: (discussion) => {
      setReply("");
      invalidate();
      const notice = replyNotice(discussion);
      if (notice) toast.push(notice);
    },
    onError: (error) => {
      toast.push({
        title: "Could not send the reply",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return {
    query,
    live,
    invalidate,
    reviewing,
    setReviewing,
    review: (decision: ReviewDecision, reason: string) => {
      reviewMutation.mutate({ decision, reason });
    },
    reviewPending: reviewMutation.isPending,
    reply,
    setReply,
    sendReply: () => {
      const content = reply.trim();
      if (content) replyMutation.mutate(content);
    },
    sending: replyMutation.isPending,
  };
}

export type DiscussionViewState = ReturnType<typeof useDiscussionView>;
