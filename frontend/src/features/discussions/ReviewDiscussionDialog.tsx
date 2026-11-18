import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import type { ReviewDecision } from "./discussionRules";

const TITLES: Record<ReviewDecision, string> = {
  approve: "Approve outcome",
  veto: "Veto outcome",
  rework: "Request rework",
};

/**
 * Asks for the person's decision on a discussion: a note for an approval, an explanation for a
 * veto or rework. `onConfirm` records it (the view's review mutation); a decision never changes
 * the Ticket. Until Confirm can be pressed it says why beside it, and stays focusable.
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
  const blocked = pending
    ? "Recording the decision…"
    : decision !== "approve" && !reason.trim()
      ? "Write the explanation first"
      : null;
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
            if (decision && blocked === null) onConfirm(decision, reason.trim());
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
            <ReasonButton
              type="submit"
              variant={decision === "approve" ? "primary" : "danger"}
              disabledReason={blocked}
            >
              Confirm
            </ReasonButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
