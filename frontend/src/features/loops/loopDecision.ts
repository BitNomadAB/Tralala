import type { MenuItem } from "@/components/ui/menu";
import type { Loop } from "@/lib/types";
import type { LoopNextAction } from "./loopNextAction";
import type { PlanTab } from "./loopUi";

/**
 * The one primary button the Loop's header offers: a review opens the document on the Plan tab,
 * where the person reads it and decides (an approval binds to the revisions on screen, so the
 * header never approves a text nobody has opened); finalize opens the completion dialog with its
 * confirmations, or for a Loop without a plan the dialog that closes it. Null when the next step is
 * no decision of the Loop's (a Ticket's wait, a generation, a Ticket to confirm sits on the Kanban).
 */
export type LoopDecision =
  | { kind: "review"; label: string; doc: Extract<PlanTab, "analysis" | "roadmap"> }
  | { kind: "finalize"; label: string };

export function loopDecision(next: LoopNextAction | null): LoopDecision | null {
  if (!next?.decision || next.label === null) return null;
  switch (next.label) {
    case "Approve analysis":
      return { kind: "review", label: next.label, doc: "analysis" };
    case "Approve RoadMap":
      return { kind: "review", label: next.label, doc: "roadmap" };
    case "Finalize Loop":
    case "Accept work":
    case "Close Loop":
      return { kind: "finalize", label: next.label };
    default:
      return null;
  }
}

/** The header hides a review's button while the Plan tab already shows that document. */
export function decisionShown(
  decision: LoopDecision | null,
  view: { tab: string; doc: PlanTab },
): LoopDecision | null {
  if (decision?.kind === "review" && view.tab === "plan" && view.doc === decision.doc) return null;
  return decision;
}

/** Why a draft offers nothing to finalize: the server refuses it (`409 approval_required`). */
export const NOTHING_TO_FINALIZE = "Nothing to finalize yet: add a Ticket or plan the Loop";

/**
 * The "Loop actions" item that opens the completion dialog: "Close Loop" for a Loop without a plan,
 * else "Finalize Loop", which a draft shows but does not offer. None while the header's one button
 * already opens the dialog. `locked` is why the Loop is read-only, when it is.
 */
export function completionMenuItems(
  loop: Pick<Loop, "stage" | "without_plan">,
  decision: LoopDecision | null,
  locked: string | undefined,
  open: () => void,
): MenuItem[] {
  if (decision?.kind === "finalize") return [];
  const draft = loop.stage === "draft";
  return [
    {
      label: loop.without_plan ? "Close Loop" : "Finalize Loop",
      disabled: locked !== undefined || draft,
      hint: locked ?? (draft ? NOTHING_TO_FINALIZE : undefined),
      onSelect: open,
    },
  ];
}
