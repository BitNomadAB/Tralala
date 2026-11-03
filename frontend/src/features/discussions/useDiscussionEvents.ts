import { useEffect, useState } from "react";

const EVENT_TYPES = [
  "message_created",
  "agent_started",
  "agent_completed",
  "agent_failed",
  "vote_recorded",
  "consensus_proposed",
  "discussion_status_changed",
  "human_review_completed",
  "run_started",
  "run_finished",
  "round_completed",
] as const;

const COALESCE_MS = 120;

/**
 * Subscribe to one discussion's server-sent events.
 *
 * Events are only a hint: they invalidate the queries, which refetch the authoritative state. The
 * browser reconnects on its own and sends `Last-Event-ID`, so the server replays what was missed.
 */
export function useDiscussionEvents(
  boardId: string,
  discussionId: string | null,
  onEvent: () => void,
): boolean {
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!boardId || !discussionId || typeof EventSource === "undefined") {
      // Nothing to follow: `live` starts false, and the previous subscription's cleanup resets it.
      return;
    }
    const source = new EventSource(
      `/api/v1/boards/${boardId}/discussions/${discussionId}/events`,
    );
    let timer: number | undefined;
    const notify = () => {
      if (timer !== undefined) return;
      timer = window.setTimeout(() => {
        timer = undefined;
        onEvent();
      }, COALESCE_MS);
    };
    source.onopen = () => {
      setLive(true);
    };
    source.onerror = () => {
      setLive(false);
    };
    for (const type of EVENT_TYPES) source.addEventListener(type, notify);
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
      for (const type of EVENT_TYPES) source.removeEventListener(type, notify);
      source.close();
      setLive(false);
    };
  }, [boardId, discussionId, onEvent]);

  return live;
}
