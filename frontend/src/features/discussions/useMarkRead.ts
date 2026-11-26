import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";

/**
 * Marks the thread read for the person once per opening, when it has loaded (`ready`): reading it
 * never does, so the view says so itself. The lists that show what is new for the reader (the
 * board's and the Tickets' lists, the inbox) are read again so the mark goes. A thread that cannot
 * be marked stays as it was: nothing the person asked for failed.
 */
export function useMarkRead(boardId: string, discussionId: string, ready: boolean): void {
  const queryClient = useQueryClient();
  const marked = useRef<string | null>(null);
  useEffect(() => {
    const opened = `${boardId}/${discussionId}`;
    if (!ready || !boardId || !discussionId || marked.current === opened) return;
    marked.current = opened;
    api.markDiscussionRead(boardId, discussionId).then(
      () => {
        void queryClient.invalidateQueries({ queryKey: keys.discussions(boardId) });
        void queryClient.invalidateQueries({ queryKey: keys.discussionInbox });
      },
      () => undefined,
    );
  }, [queryClient, boardId, discussionId, ready]);
}
