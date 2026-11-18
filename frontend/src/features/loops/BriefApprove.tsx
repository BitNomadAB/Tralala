import { approvalLine, type BriefApproval } from "./briefApproval";
import { BusyButton } from "./BusyButton";

/**
 * "Approve analysis" at the end of the brief, with the revision it approves named under it. Pressed,
 * it keeps the focus while the decision is recorded and once it reads "Approved".
 */
export function BriefApprove({ approval }: { approval: BriefApproval }) {
  return (
    <div className="grid justify-items-start gap-1.5 border-t border-[var(--border-soft)] pt-4">
      <BusyButton
        busy={approval.pending === true || approval.approved}
        disabled={approval.disabled}
        onClick={approval.onApprove}
      >
        {approval.approved ? "Approved" : "Approve analysis"}
      </BusyButton>
      <p className="m-0 text-[12.5px] tabular-nums text-[var(--muted-foreground)]">
        {approvalLine(approval)}
      </p>
    </div>
  );
}
