import type { BadgeTone } from "@/components/ui/badge";
import { ApiError } from "@/lib/api";
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

/** The planning documents dialog's tabs; the last two are the scopes an agent generates. */
export type PlanTab = "info" | "analysis" | "roadmap";
export type PlanScope = Exclude<PlanTab, "info">;

export const errorText = (error: unknown) =>
  error instanceof ApiError ? error.message : "Please try again.";

/** How many cards one column loads; the drag and drop writes to the same query keys. */
export const LIST_LIMIT = 200;
