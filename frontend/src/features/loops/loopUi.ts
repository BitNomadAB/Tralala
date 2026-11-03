import type { BadgeTone } from "@/components/ui/badge";
import type { DocumentKind, LoopStage } from "@/lib/types";

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

/** How many cards one column loads; the drag and drop writes to the same query keys. */
export const LIST_LIMIT = 200;
