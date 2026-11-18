import { createContext, useContext, useEffect } from "react";

/** How a screen reader reads an announcement: after what it is reading, or at once. */
export type Politeness = "polite" | "assertive";

/** Says `text` to a screen reader without showing anything new on screen. */
export type Announce = (text: string, politeness?: Politeness) => void;

/**
 * How long a region stays empty before the new text goes in. A screen reader reads a live region
 * when its text changes, so the same text sent twice is cleared first and set on the next tick.
 */
export const ANNOUNCE_DELAY_MS = 50;

/** Shared by `AnnouncerProvider` (announcer.tsx) and the hooks; a component file exports components. */
export const AnnounceContext = createContext<Announce | null>(null);

/**
 * The one way a view tells a screen reader what happened (WCAG 4.1.3): "Saved", "Ticket moved to
 * Done". The text goes into a visually hidden live region that exists from the start, outside
 * every dialog. Use it for what changed without moving focus; a toast is announced by itself.
 */
export function useAnnounce(): Announce {
  const announce = useContext(AnnounceContext);
  if (!announce) throw new Error("useAnnounce must be used within ToastProvider");
  return announce;
}

/**
 * Announces `text` each time `active` becomes true, and again when the text changes while it is:
 * for a status line a view shows while something is under way.
 */
export function useAnnounceWhen(active: boolean, text: string, politeness?: Politeness): void {
  const announce = useAnnounce();
  useEffect(() => {
    if (active) announce(text, politeness);
  }, [active, text, politeness, announce]);
}
