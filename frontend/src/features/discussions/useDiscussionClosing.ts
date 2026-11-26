import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Discussion } from "@/lib/types";

/**
 * "Close discussion" and "Reopen": the question before closing (`asking`), then the request. The
 * thread on screen takes the new status at once, so the button that was pressed says what it is
 * now without waiting for the refetch, and the lists are read again (`invalidate`). A refusal (not
 * the opener, a run under way, a finished Loop) is a toast with the server's reason.
 */
export function useDiscussionClosing(
  boardId: string,
  discussionId: string,
  invalidate: () => void,
) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [asking, setAsking] = useState(false);

  const settle = (saved: Discussion) => {
    queryClient.setQueryData<Discussion>(keys.discussion(boardId, discussionId), (shown) =>
      shown ? { ...shown, status: saved.status, closed_at: saved.closed_at } : shown,
    );
    invalidate();
  };
  const refused = (title: string) => (error: Error) => {
    toast.push({ title, description: describeError(error, undefined), variant: "error" });
  };

  const close = useMutation({
    mutationFn: () => api.closeDiscussion(boardId, discussionId),
    onSuccess: settle,
    onError: refused("Could not close the discussion"),
  });
  const reopen = useMutation({
    mutationFn: () => api.reopenDiscussion(boardId, discussionId),
    onSuccess: settle,
    onError: refused("Could not reopen the discussion"),
  });

  return {
    asking,
    ask: () => {
      setAsking(true);
    },
    cancel: () => {
      setAsking(false);
    },
    /** Closes the question at once: the button that opened it stays and says it is under way. */
    confirm: () => {
      setAsking(false);
      close.mutate();
    },
    reopen: () => {
      reopen.mutate();
    },
    busy: close.isPending || reopen.isPending,
  };
}

export type DiscussionClosing = ReturnType<typeof useDiscussionClosing>;
