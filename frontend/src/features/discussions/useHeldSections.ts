import { useEffect, useRef, useState } from "react";
import type { DiscussionInboxRow } from "@/lib/types";
import { inboxSections, type HeldSections } from "./inboxRules";

/**
 * The inbox's sections held while focus is inside `ref` (the lists): the inbox refetches every
 * 30 s, and a row that moved to another section would be a new link, so the one with focus would
 * vanish. While focus moves between the rows each keeps its section (`inboxSection`); once focus
 * leaves the lists, they are grouped as they stand.
 */
export function useHeldSections(rows: readonly DiscussionInboxRow[]) {
  const ref = useRef<HTMLDivElement>(null);
  const latest = useRef(rows);
  const [held, setHeld] = useState<HeldSections | null>(null);

  useEffect(() => {
    latest.current = rows;
  }, [rows]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const enter = () => {
      setHeld((current) => current ?? inboxSections(latest.current));
    };
    const leave = (event: FocusEvent) => {
      if (event.relatedTarget instanceof Node && node.contains(event.relatedTarget)) return;
      setHeld(null);
    };
    node.addEventListener("focusin", enter);
    node.addEventListener("focusout", leave);
    return () => {
      node.removeEventListener("focusin", enter);
      node.removeEventListener("focusout", leave);
    };
  }, []);

  return { ref, held };
}
