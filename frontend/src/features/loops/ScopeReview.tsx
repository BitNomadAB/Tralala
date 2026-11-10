import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";

/** Feedback, reset and the human decision on the open Analysis or RoadMap. */
export function ScopeReview({
  scopeLabel,
  isHuman,
  readOnly,
  feedback,
  onFeedbackChange,
  canReset,
  confirmReset,
  onConfirmResetChange,
  resetPending,
  onReset,
  canReview,
  approveInBrief = false,
  approved,
  reviewPending,
  onDecision,
  approveLabel,
  approveNote,
  onRegenerate,
  regenerateDisabled = false,
}: {
  scopeLabel: string;
  isHuman: boolean;
  readOnly: boolean;
  feedback: string;
  onFeedbackChange: (value: string) => void;
  canReset: boolean;
  confirmReset: boolean;
  onConfirmResetChange: (confirm: boolean) => void;
  resetPending: boolean;
  onReset: () => void;
  canReview: boolean;
  /** The brief above carries the approve button (an analysis brief), so it is not repeated here. */
  approveInBrief?: boolean | undefined;
  approved: boolean;
  reviewPending: boolean;
  onDecision: (decision: "approved" | "changes_requested") => void;
  /** The approve button's words when they say more than "Approve RoadMap" ("· 3 Tickets"). */
  approveLabel?: string | undefined;
  /** The line under the decision: the revision it binds to and what approving does. */
  approveNote?: string | null | undefined;
  /** Writes the scope again from its approved input and the feedback above (the RoadMap review). */
  onRegenerate?: (() => void) | undefined;
  regenerateDisabled?: boolean | undefined;
}) {
  const label = approveLabel ?? `Approve ${scopeLabel}`;
  return (
    <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3">
      {!isHuman ? (
        <p className="text-[11px] text-[var(--warning)]">
          Approving is a human decision; agents can generate and comment only.
        </p>
      ) : null}
      <Field label="Feedback (optional)" htmlFor="loop-review-feedback">
        <Input
          id="loop-review-feedback"
          value={feedback}
          onChange={(event) => onFeedbackChange(event.target.value)}
          maxLength={20000}
          disabled={readOnly || !isHuman}
        />
      </Field>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {canReset ? (
            confirmReset ? (
              <>
                <span className="text-[11px] text-[var(--destructive)]">
                  Resetting clears the {scopeLabel} and any approval behind it. It has to be
                  generated again.
                </span>
                <Button size="sm" variant="danger" disabled={resetPending} onClick={onReset}>
                  Reset and clear
                </Button>
                <Button size="sm" variant="ghost" onClick={() => onConfirmResetChange(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="danger"
                disabled={resetPending}
                onClick={() => onConfirmResetChange(true)}
              >
                Reset {scopeLabel}
              </Button>
            )
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {onRegenerate ? (
            <Button
              variant="outline"
              disabled={readOnly || !isHuman || regenerateDisabled}
              onClick={onRegenerate}
            >
              <RefreshCw size={14} /> Regenerate {scopeLabel}
            </Button>
          ) : null}
          <Button
            variant="outline"
            disabled={readOnly || !isHuman || reviewPending}
            onClick={() => onDecision("changes_requested")}
          >
            Request changes
          </Button>
          {approveInBrief ? null : (
            <Button
              disabled={readOnly || !canReview || reviewPending || approved}
              onClick={() => onDecision("approved")}
            >
              {approved ? "Approved" : label}
            </Button>
          )}
        </div>
      </div>
      {onRegenerate ? (
        <p className="m-0 text-right text-xs text-[var(--muted-foreground)]">
          Regenerate writes a new {scopeLabel} from the approved analysis and the feedback above.
          The current plan stays until you approve the new one; then its Tickets nobody has touched
          are removed.
        </p>
      ) : null}
      {approveNote && !approved ? (
        <p className="m-0 text-right text-xs text-[var(--muted-foreground)]">{approveNote}</p>
      ) : null}
    </div>
  );
}
