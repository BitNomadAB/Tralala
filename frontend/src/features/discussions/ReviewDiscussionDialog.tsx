import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import type { ReviewDecision } from "./discussionRules";

const TITLES: Record<ReviewDecision, string> = {
  approve: "Approve outcome",
  veto: "Veto outcome",
  rework: "Request rework",
};

/**
 * Asks for the person's decision on a discussion: a note for an approval, an explanation for a
 * veto or rework. `onConfirm` records it (the view's review mutation); a decision never changes
 * the Ticket.
 */
export function ReviewDiscussionDialog({
  decision,
  pending,
  onClose,
  onConfirm,
}: {
  decision: ReviewDecision | null;
  pending: boolean;
  onClose: () => void;
  onConfirm: (decision: ReviewDecision, reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const close = () => {
    setReason("");
    onClose();
  };

  return (
    <Dialog open={decision !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent
        title={decision ? TITLES[decision] : "Decision"}
        description="A decision is recorded on the discussion only; it never changes the Ticket. Veto and rework need an explanation."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!decision) return;
            if (decision === "approve" || reason.trim()) onConfirm(decision, reason.trim());
          }}
        >
          <Field
            label={decision === "approve" ? "Note (optional)" : "Explanation"}
            htmlFor="review-reason"
          >
            <Textarea
              id="review-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              required={decision !== "approve"}
              maxLength={20000}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={close}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant={decision === "approve" ? "primary" : "danger"}
              disabled={pending || (decision !== "approve" && !reason.trim())}
            >
              Confirm
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
