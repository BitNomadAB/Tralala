import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import type { ReviewDecision } from "./DiscussionThread";

/** Records a human decision on a thread's outcome; veto and rework need an explanation. */
export function ReviewDiscussionDialog({
  boardId,
  discussionId,
  decision,
  onClose,
  onReviewed,
}: {
  boardId: string;
  discussionId: string | null;
  decision: ReviewDecision | null;
  onClose: () => void;
  onReviewed: () => void;
}) {
  const toast = useToast();
  const [reason, setReason] = useState("");

  const reviewMutation = useMutation({
    mutationFn: (input: { decision: ReviewDecision; reason: string }) =>
      api.reviewDiscussion(boardId, String(discussionId), input),
    onSuccess: (discussion) => {
      onClose();
      setReason("");
      onReviewed();
      toast.push({ title: `Discussion ${discussion.status}`, variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not record the decision",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  return (
    <Dialog open={decision !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={
          decision === "approve"
            ? "Approve outcome"
            : decision === "veto"
              ? "Veto outcome"
              : "Request rework"
        }
        description="Approval records a decision only — it never changes the ticket. Veto and rework require an explanation."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!decision) return;
            if (decision === "approve" || reason.trim()) {
              reviewMutation.mutate({ decision, reason: reason.trim() });
            }
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
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant={decision === "approve" ? "primary" : "danger"}
              disabled={reviewMutation.isPending || (decision !== "approve" && !reason.trim())}
            >
              Confirm
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
