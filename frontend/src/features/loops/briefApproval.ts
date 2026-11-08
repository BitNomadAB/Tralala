import type { LoopDocument } from "@/lib/types";
import { isHumanBrief } from "./briefs";
import { isBrief } from "./loopUi";

/** What the analysis brief needs to carry the approval: the revisions it binds and the decision. */
export interface BriefApproval {
  /** The revision of the analysis for people (this brief) an approval binds. */
  revisionNumber: number | null;
  /** The technical revision the brief was written from, bound with it. */
  technicalRevisionNumber: number | null;
  approved: boolean;
  disabled: boolean;
  onApprove: () => void;
}

/** The line under the button: which revisions the approval binds, or bound. */
export function approvalLine(approval: BriefApproval): string {
  const revision = approval.revisionNumber ?? "–";
  if (approval.approved) return `Approved: revision ${revision} of this analysis.`;
  const technical = approval.technicalRevisionNumber;
  const from = technical === null ? "" : `, written from technical revision ${technical}`;
  return `Approves revision ${revision} of this analysis${from}.`;
}

/**
 * Whether the analysis for people is a brief, which then shows as the sign (read whole, with no
 * scroll box of its own) and carries "Approve analysis" at its end.
 */
export function showsAnalysisBrief(document: LoopDocument): boolean {
  return (
    isBrief(document) && document.kind === "analysis" && isHumanBrief(document.current_payload)
  );
}
