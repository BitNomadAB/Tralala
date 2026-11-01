import { useEffect, useState } from "react";

const EVENT_TYPES = ["agent_started", "agent_completed", "agent_failed"] as const;

const COALESCE_MS = 120;

/**
 * Subscribe to one ticket's server-sent events (agent mention work).
 *
 * Events only invalidate the queries; the queries refetch the authoritative state. The browser
 * reconnects on its own and sends `Last-Event-ID`, so the server replays anything missed.
 */
export function useCardEvents(
  boardId: string,
  loopId: string,
  cardId: string | null,
  onEvent: () => void,
): boolean {
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!boardId || !loopId || !cardId || typeof EventSource === "undefined") {
      setLive(false);
      return;
    }
    const source = new EventSource(
      `/api/v1/boards/${boardId}/loops/${loopId}/cards/${cardId}/events`,
    );
    let timer: number | undefined;
    const notify = () => {
      if (timer !== undefined) return;
      timer = window.setTimeout(() => {
        timer = undefined;
        onEvent();
      }, COALESCE_MS);
    };
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    for (const type of EVENT_TYPES) source.addEventListener(type, notify);
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
      for (const type of EVENT_TYPES) source.removeEventListener(type, notify);
      source.close();
      setLive(false);
    };
  }, [boardId, loopId, cardId, onEvent]);

  return live;
}
