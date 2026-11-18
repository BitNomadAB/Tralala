import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ANNOUNCE_DELAY_MS, AnnounceContext, type Announce, type Politeness } from "./useAnnounce";

const QUIET: Record<Politeness, string> = { polite: "", assertive: "" };

/**
 * Holds the two live regions `useAnnounce` writes to, visually hidden and in the page from the
 * first render: a screen reader only reads a region it already knew when its text changes. They
 * carry `aria-live` itself, not only a role, because a Radix dialog hides the rest of the page from
 * screen readers with `aria-hidden` and keeps exactly the `[aria-live]` elements readable; and no
 * role, so they never compete with a page's own status or alert. Texts sent in the same tick are
 * read together.
 */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [said, setSaid] = useState(QUIET);
  const pending = useRef<Record<Politeness, string[]>>({ polite: [], assertive: [] });
  const timers = useRef(new Map<Politeness, number>());

  const announce = useCallback<Announce>((text, politeness = "polite") => {
    const queued = pending.current[politeness];
    queued.push(text);
    if (timers.current.has(politeness)) return;
    setSaid((current) => ({ ...current, [politeness]: "" }));
    const timer = window.setTimeout(() => {
      timers.current.delete(politeness);
      const next = pending.current[politeness].join(" ");
      pending.current[politeness] = [];
      setSaid((current) => ({ ...current, [politeness]: next }));
    }, ANNOUNCE_DELAY_MS);
    timers.current.set(politeness, timer);
  }, []);

  useEffect(() => {
    const running = timers.current;
    return () => {
      for (const timer of running.values()) window.clearTimeout(timer);
      running.clear();
    };
  }, []);

  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <div className="sr-only" aria-live="polite" aria-atomic="true" data-announcer="polite">
        {said.polite}
      </div>
      <div className="sr-only" aria-live="assertive" aria-atomic="true" data-announcer="assertive">
        {said.assertive}
      </div>
    </AnnounceContext.Provider>
  );
}
