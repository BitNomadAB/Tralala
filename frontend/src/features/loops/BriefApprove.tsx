import { Button } from "@/components/ui/button";
import { approvalLine, type BriefApproval } from "./briefApproval";

/** "Approve analysis" at the end of the brief, with the revision it approves named under it. */
export function BriefApprove({ approval }: { approval: BriefApproval }) {
  return (
    <div className="grid justify-items-start gap-1.5 border-t border-[var(--border-soft)] pt-4">
      <Button disabled={approval.disabled || approval.approved} onClick={approval.onApprove}>
        {approval.approved ? "Approved" : "Approve analysis"}
      </Button>
      <p className="m-0 text-[12.5px] tabular-nums text-[var(--muted-foreground)]">
        {approvalLine(approval)}
      </p>
    </div>
  );
}
