import { useEffect, useRef } from "react";
import { useAnnounce } from "@/components/ui/useAnnounce";
import type { Discussion } from "@/lib/types";
import { discussionNotices, liveState, type LiveState } from "./discussionNotices";
import type { RunView } from "./runEvents";

/**
 * Tells a screen reader what changed as the agents answer (`discussionNotices`): each render's
 * thread is compared with the last one looked at. `ready` waits for the stored events, so the
 * answers and failures they hold when the view opens are not read out as news.
 */
export function useDiscussionNotices(
  discussion: Discussion,
  run: RunView | null,
  ready: boolean,
): void {
  const announce = useAnnounce();
  const seen = useRef<LiveState | null>(null);
  useEffect(() => {
    if (!ready) return;
    const now = liveState(discussion, run);
    for (const notice of discussionNotices(seen.current, now)) announce(notice);
    seen.current = now;
  }, [announce, discussion, run, ready]);
}
