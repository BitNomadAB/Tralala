import { useEffect, useState } from "react";

/**
 * The card events that change what the view shows: an agent's mention work, and a person's note
 * (`NOTE_EVENT_TYPES` in `backend/app/services/card_notes.py`).
 */
export const CARD_EVENT_TYPES = [
  "agent_started",
  "agent_completed",
  "agent_failed",
  "note_added",
  "note_edited",
  "note_deleted",
] as const;

const COALESCE_MS = 120;

/**
 * Subscribe to one ticket's server-sent events (agent mention work, a person's notes).
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
      // Nothing to follow: `live` starts false, and the previous subscription's cleanup resets it.
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
    source.onopen = () => {
      setLive(true);
    };
    source.onerror = () => {
      setLive(false);
    };
    for (const type of CARD_EVENT_TYPES) source.addEventListener(type, notify);
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
      for (const type of CARD_EVENT_TYPES) source.removeEventListener(type, notify);
      source.close();
      setLive(false);
    };
  }, [boardId, loopId, cardId, onEvent]);

  return live;
}
