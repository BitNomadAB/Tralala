import { useEffect, useRef } from "react";
import { useAnnounce } from "@/components/ui/useAnnounce";

/**
 * Says how many boards the dashboard shows after a search or a filter: "3 boards match (1
 * archived).", or "No board matches." Without a search or a filter it counts them all.
 */
export function boardCountWords(active: number, archived: number, filtered: boolean): string {
  const total = active + archived;
  if (total === 0) return filtered ? "No board matches." : "No boards yet.";
  const boards = total === 1 ? "1 board" : `${total} boards`;
  const verb = filtered ? (total === 1 ? " matches" : " match") : "";
  const archivedPart = archived === 0 ? "" : ` (${archived} archived)`;
  return `${boards}${verb}${archivedPart}.`;
}

/**
 * Announces `text`, the number of results, once the results for a new search or filter (`key`)
 * have arrived (WCAG 4.1.3): the list changes under the field without moving focus, so a screen
 * reader would not hear about it otherwise. The results the page opens with are not announced,
 * since nobody asked for them; going back to them later is.
 */
export function useAnnounceResults(key: string, settled: boolean, text: string): void {
  const announce = useAnnounce();
  const said = useRef(key);
  useEffect(() => {
    if (!settled || said.current === key) return;
    said.current = key;
    announce(text);
  }, [key, settled, text, announce]);
}
