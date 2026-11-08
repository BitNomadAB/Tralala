import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { LoopStage } from "@/lib/types";
import type { LoopTab } from "./loopNextAction";
import type { PlanTab } from "./loopUi";

const TABS: readonly LoopTab[] = ["kanban", "plan", "notes"];
const DOCUMENTS: readonly PlanTab[] = ["info", "analysis", "roadmap"];

/** The tab `?tab=` names; anything else, or nothing, is the Kanban. */
export function parseTab(value: string | null): LoopTab {
  return TABS.find((tab) => tab === value) ?? "kanban";
}

/** The document the Plan tab opens on when `?doc=` names none: the one the stage works on. */
export function stageDocument(stage: LoopStage): PlanTab {
  if (stage === "draft") return "info";
  if (stage === "analysis_review") return "analysis";
  return "roadmap";
}

/** The Plan tab's document from `?doc=`, else the stage's. */
export function parseDocument(value: string | null, stage: LoopStage): PlanTab {
  return DOCUMENTS.find((doc) => doc === value) ?? stageDocument(stage);
}

/**
 * The search parameters for a view: `tab` only when it is not the Kanban, `doc` only on the Plan
 * tab (kept when the tab is chosen without one), and everything else, `card` included, as it was.
 */
export function viewParams(current: URLSearchParams, tab: LoopTab, doc?: PlanTab): URLSearchParams {
  const next = new URLSearchParams(current);
  if (tab === "kanban") next.delete("tab");
  else next.set("tab", tab);
  if (tab !== "plan") next.delete("doc");
  else if (doc) next.set("doc", doc);
  return next;
}

/** The Loop page's tab and the Plan tab's document, both in the URL so a link lands on them. */
export function useLoopView(stage: LoopStage) {
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get("tab"));
  const doc = parseDocument(params.get("doc"), stage);
  const show = useCallback(
    (next: LoopTab, nextDoc?: PlanTab) => {
      setParams((current) => viewParams(current, next, nextDoc), { replace: true });
    },
    [setParams],
  );
  return { tab, doc, show };
}

export type LoopView = ReturnType<typeof useLoopView>;
