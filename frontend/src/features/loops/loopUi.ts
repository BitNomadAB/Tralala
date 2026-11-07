import type { BadgeTone } from "@/components/ui/badge";
import type { DocumentKind, LoopDocument, LoopStage, UnplannedTicket } from "@/lib/types";

export const STAGE_TONES: Record<LoopStage, BadgeTone> = {
  draft: "neutral",
  analysis_review: "brand",
  planning: "brand",
  roadmap_review: "brand",
  ready: "success",
  in_progress: "brand",
  replanning: "warning",
  awaiting_qa: "warning",
  completed: "success",
  cancelled: "neutral",
};

export const DOCUMENT_LABELS: Record<DocumentKind, string> = {
  info: "Info",
  analysis_ai: "Analysis (AI)",
  analysis: "Analysis",
  roadmap_ai: "RoadMap (AI)",
  roadmap: "RoadMap",
};

/**
 * Why a document needs regeneration, one sentence per code `stale_reasons` in
 * `backend/app/services/loops_stage.py` produces. The panel shows the sentence and keeps the code in
 * a tooltip, so a person reads what happened and a report can still quote the code.
 */
export const STALE_REASON_TEXT: Readonly<Partial<Record<string, string>>> = {
  info_missing: "Info has not been written yet.",
  info_changed: "Info changed after this was written.",
  analysis_ai_missing: "The AI analysis has not been generated.",
  analysis_ai_changed: "The AI analysis changed after this was written.",
  analysis_missing: "The analysis has not been generated.",
  analysis_changed: "The analysis changed after this was written.",
  roadmap_ai_missing: "The AI RoadMap has not been generated.",
  roadmap_ai_changed: "The AI RoadMap changed after this was written.",
  upstream_stale: "An earlier document needs regeneration first.",
  approval_superseded: "The approval was for an earlier revision; this one needs a new review.",
};

/** The sentence for a stale reason; a code this client does not know yet is shown as it is. */
export function staleReasonText(code: string): string {
  return STALE_REASON_TEXT[code] ?? code;
}

/** The planning documents dialog's tabs; the last two are the scopes an agent generates. */
export type PlanTab = "info" | "analysis" | "roadmap";
export type PlanScope = Exclude<PlanTab, "info">;
/** What a run panel describes: a scope's run, or the brief for people of a scope. */
export type RunPurpose = PlanScope | "analysis_human" | "roadmap_human";
/** The run that writes a scope's brief for people. */
export const FOR_PEOPLE_PURPOSE = {
  analysis: "analysis_human",
  roadmap: "roadmap_human",
} as const satisfies Record<PlanScope, RunPurpose>;

/**
 * Who wrote the human view: the board agent or the worker that wrote it for people, or the server
 * that rendered it from the structure. Null for a revision that says neither.
 */
export function viewAuthorship(document: LoopDocument): string | null {
  const provenance = document.current_provenance ?? {};
  if (provenance.written === true) {
    const agent = provenance.agent_name;
    if (typeof agent === "string" && agent) return `Written by ${agent}`;
    const author = provenance.author;
    if (typeof author === "string" && author) return `Written by ${author}`;
    return "Written by a board agent";
  }
  return provenance.rendered === true ? "Rendered from the structure" : null;
}

/**
 * Whether the human view is a brief (its revision carries the brief as payload). A view written for
 * people before briefs existed is Markdown without one: the "Earlier format".
 */
export function isBrief(document: LoopDocument): boolean {
  const payload = document.current_payload;
  if (payload === null) return false;
  if (document.kind === "analysis") return typeof payload.verdict === "string";
  return document.kind === "roadmap" && Array.isArray(payload.order);
}

export function isEarlierFormat(document: LoopDocument): boolean {
  return document.current_provenance?.written === true && !isBrief(document);
}

/**
 * Why "Rewrite for people" cannot start, or null when it can. A disabled button that only turns grey
 * leaves a person guessing; the reason is shown beside it.
 */
export function rewriteBlockedReason({
  approved,
  writing,
  generating,
  hasTechnical,
}: {
  approved: boolean;
  writing: boolean;
  generating: boolean;
  hasTechnical: boolean;
}): string | null {
  if (writing) return "Writing for people...";
  if (approved) return "Approved: request changes or reset to rewrite";
  if (generating) return "A run is in progress";
  if (!hasTechnical) return "Generate the technical version first";
  return null;
}

/** How many cards one column loads; the drag and drop writes to the same query keys. */
export const LIST_LIMIT = 200;

/** Open work outside the plan: neither completed nor archived. */
export function openUnplanned(tickets: UnplannedTicket[]): UnplannedTicket[] {
  return tickets.filter((ticket) => !ticket.completed_at && !ticket.archived_at);
}
