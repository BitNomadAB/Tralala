import { useEffect, useRef, useState } from "react";
import { useLoopDocuments, useLoopSummaries } from "@/lib/queries";
import type { DocumentKind, LoopDocument, LoopSummary } from "@/lib/types";

const KINDS: readonly DocumentKind[] = ["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"];

/** Shown, and read out, when a text on screen is no longer the Loop's current one. */
export const DOCUMENTS_CHANGED_TEXT =
  "The planning documents have changed since this page read them.";

/**
 * How the planning documents on screen stand to the board's Loop summary: `no` when they are the
 * current revisions, `unread` when only documents nobody has on screen yet got a revision, and
 * `replaced` when a text on screen is no longer the current one.
 */
export type Behind = "no" | "unread" | "replaced";

/** The revision a summary's document line names (`approved r3`); null for one without (`empty`). */
export function summaryRevision(line: string | undefined): number | null {
  const digits = / r(\d+)$/.exec(line ?? "")?.[1];
  return digits === undefined ? null : Number(digits);
}

/**
 * Compares each document's revision number in the summary with the one on screen. A document's
 * revisions are numbered upwards and never again from one, so the screen is behind only where the
 * summary names a higher number; a screen that is ahead (the page read the documents after the
 * summary) is not. Info counts as replaced even when the screen shows none: a person writes it
 * here, and a draft of it is saved against the revision the page holds.
 */
export function documentsBehind(
  summary: LoopSummary["documents"] | undefined,
  shown: Record<DocumentKind, LoopDocument> | undefined,
): Behind {
  if (!summary || !shown) return "no";
  let behind: Behind = "no";
  for (const kind of KINDS) {
    const current = summaryRevision(summary[kind]);
    const onScreen = shown[kind].current_revision_number;
    if (current === null || current <= (onScreen ?? 0)) continue;
    if (onScreen !== null || kind === "info") return "replaced";
    behind = "unread";
  }
  return behind;
}

/**
 * Whether the planning documents on screen are behind the Loop, which the page follows live
 * through the board's Loop summaries while the documents themselves wait for the person: an
 * approval binds to the revisions on screen, so a text under review is never replaced under its
 * reader. A document nobody has on screen yet (an analysis handed in while the page was open) is
 * read at once through `onChanged`, once per state of the summary; a text that was replaced only
 * says so (`behind`), and the person asks for the latest. `loading` is true while that is read.
 */
export function useDocumentsBehind(
  boardId: string,
  loopId: string,
  onChanged: () => void,
): { behind: boolean; loading: boolean } {
  const summaries = useLoopSummaries(boardId);
  const documents = useLoopDocuments(boardId, loopId);
  const summary = summaries.data?.loops.find((entry) => entry.id === loopId)?.documents;
  // While either is being read the two are not from the same moment, so the last verdict stands.
  const settled = !summaries.isFetching && !documents.isFetching;
  const [verdict, setVerdict] = useState<Behind>("no");
  const now = settled ? documentsBehind(summary, documents.data?.documents) : verdict;
  if (now !== verdict) setVerdict(now);

  const read = useRef<string | null>(null);
  useEffect(() => {
    if (verdict !== "unread") return;
    const state = JSON.stringify(summary);
    if (read.current === state) return;
    read.current = state;
    onChanged();
  }, [verdict, summary, onChanged]);

  return { behind: verdict === "replaced", loading: documents.isFetching };
}
