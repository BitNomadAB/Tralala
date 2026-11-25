import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { LoopStage } from "@/lib/types";
import type { LoopTab } from "./loopNextAction";
import type { PlanTab } from "./loopUi";

const TABS: readonly LoopTab[] = ["kanban", "plan", "notes"];
const DOCUMENTS: readonly PlanTab[] = ["info", "analysis", "roadmap"];
const DIALOGS = ["completion"] as const;

/**
 * A dialog of the Loop page a link opens (`?dialog=`): `completion`, the dialog where a person
 * accepts the implementation and QA, or closes a Loop without a plan. The server's decision links
 * (`decision_links.py`) name it.
 */
export type LinkedDialog = (typeof DIALOGS)[number];

/** The dialog `?dialog=` names; anything else, or nothing, is none. */
export function parseDialog(value: string | null): LinkedDialog | null {
  return DIALOGS.find((dialog) => dialog === value) ?? null;
}

/** The search parameters without `dialog`, everything else as it was. */
export function withoutDialog(current: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(current);
  next.delete("dialog");
  return next;
}

/** The tab `?tab=` names; anything else, or nothing, is the Kanban. */
export function parseTab(value: string | null): LoopTab {
  return TABS.find((tab) => tab === value) ?? "kanban";
}

/**
 * The document the Plan tab opens on when `?doc=` names none: the one the stage works on. A Loop
 * without a plan has no RoadMap, so it opens on its Info.
 */
export function stageDocument(stage: LoopStage, withoutPlan = false): PlanTab {
  if (stage === "draft" || withoutPlan) return "info";
  if (stage === "analysis_review") return "analysis";
  return "roadmap";
}

/** The Plan tab's document from `?doc=`, else the stage's. */
export function parseDocument(
  value: string | null,
  stage: LoopStage,
  withoutPlan = false,
): PlanTab {
  return DOCUMENTS.find((doc) => doc === value) ?? stageDocument(stage, withoutPlan);
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

/**
 * The Loop page's tab, the Plan tab's document and the dialog a link opens, all in the URL so a
 * link lands on them. `closeDialog` takes `dialog` out of the URL, replacing the entry, so a reload
 * or Back does not open the dialog again.
 */
export function useLoopView(stage: LoopStage, withoutPlan = false) {
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get("tab"));
  const doc = parseDocument(params.get("doc"), stage, withoutPlan);
  const dialog = parseDialog(params.get("dialog"));
  const linked = params.has("dialog");
  const show = useCallback(
    (next: LoopTab, nextDoc?: PlanTab) => {
      setParams((current) => viewParams(current, next, nextDoc), { replace: true });
    },
    [setParams],
  );
  const closeDialog = useCallback(() => {
    if (linked) setParams(withoutDialog, { replace: true });
  }, [linked, setParams]);
  return { tab, doc, dialog, show, closeDialog };
}

export type LoopView = ReturnType<typeof useLoopView>;
