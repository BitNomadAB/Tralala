import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";

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
  approved,
  reviewPending,
  onDecision,
  approveLabel,
  approveNote,
  quietReset = false,
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
  approved: boolean;
  reviewPending: boolean;
  onDecision: (decision: "approved" | "changes_requested") => void;
  /** The approve button's words when they say more than "Approve RoadMap" ("· 3 Tickets"). */
  approveLabel?: string | undefined;
  /** The line under the decision: the revision it binds to and what approving does. */
  approveNote?: string | null | undefined;
  /** Reset sits in a quiet menu instead of a button of its own (the RoadMap review). */
  quietReset?: boolean | undefined;
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
            ) : quietReset ? null : (
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
          <Button
            variant="outline"
            disabled={readOnly || !isHuman || reviewPending}
            onClick={() => onDecision("changes_requested")}
          >
            Request changes
          </Button>
          <Button
            disabled={readOnly || !canReview || reviewPending || approved}
            onClick={() => onDecision("approved")}
          >
            {approved ? "Approved" : label}
          </Button>
          {quietReset && canReset && !confirmReset ? (
            <Menu
              label={`${scopeLabel} actions`}
              items={[
                {
                  label: `Reset ${scopeLabel}`,
                  danger: true,
                  disabled: resetPending,
                  onSelect: () => onConfirmResetChange(true),
                },
              ]}
            />
          ) : null}
        </div>
      </div>
      {approveNote && !approved ? (
        <p className="m-0 text-right text-xs text-[var(--muted-foreground)]">{approveNote}</p>
      ) : null}
    </div>
  );
}
