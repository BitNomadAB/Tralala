import { useId } from "react";
import { Menu } from "@/components/ui/menu";
import { ReasonButton } from "@/components/ui/reason-button";
import type { Discussion } from "@/lib/types";
import {
  decisionBlocked,
  isClosed,
  isTalking,
  NOT_YET,
  RUN_BUSY,
  runControlBlocked,
  runControls,
  talkBlocked,
  type ReviewDecision,
  type RunAction,
} from "./discussionRules";
import { HeldButton } from "./HeldButton";

/**
 * The actions row under the sign: the person's decision (Approve as the primary, Request rework,
 * Veto), then Let them talk it out, then More (Copy link, Cancel discussion). While the agents
 * answer, Stop comes first and More holds Pause or Resume. A button that cannot be pressed says
 * why and stays where it is, so focus stays on it: the decision shares one reason line under the
 * row. Only Stop, once the run is over, and the decision, once it is taken, leave; the view then
 * gives focus to its heading (`useFocusRescue`).
 */
export function DiscussionActions({
  discussion,
  onReview,
  onTalk,
  onControl,
  busy,
  onCopyLink,
}: {
  discussion: Discussion;
  onReview: (decision: ReviewDecision) => void;
  /** Opens "Let them talk it out". */
  onTalk: () => void;
  /** Pause, Resume or Stop the run under way. */
  onControl: (action: RunAction) => void;
  /** A run is being started or changed: the run actions wait for it. */
  busy: boolean;
  onCopyLink: () => void;
}) {
  const reasonId = useId();
  const closed = isClosed(discussion);
  const blocked = closed ? null : decisionBlocked(discussion);
  const decision = { held: blocked !== null, reasonId, size: "sm" as const };
  const control = runControlBlocked(discussion, busy);
  return (
    <div className="mb-4 mt-[18px] grid gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        {isTalking(discussion) ? (
          <ReasonButton
            variant="danger-quiet"
            size="sm"
            disabledReason={control}
            onClick={() => onControl("stop")}
          >
            Stop
          </ReasonButton>
        ) : null}
        {closed ? null : (
          <>
            <HeldButton {...decision} onClick={() => onReview("approve")}>
              Approve
            </HeldButton>
            <HeldButton {...decision} variant="secondary" onClick={() => onReview("rework")}>
              Request rework
            </HeldButton>
            <HeldButton {...decision} variant="danger" onClick={() => onReview("veto")}>
              Veto
            </HeldButton>
            <span aria-hidden="true" className="mx-1 h-5 w-px bg-[var(--border)]" />
          </>
        )}
        <ReasonButton
          variant="secondary"
          size="sm"
          disabledReason={talkBlocked(discussion) ?? (busy ? RUN_BUSY : null)}
          onClick={onTalk}
        >
          Let them talk it out
        </ReasonButton>
        <Menu
          label="More actions"
          items={[
            ...runControls(discussion).map((item) => ({
              label: item.label,
              onSelect: () => onControl(item.action),
              disabled: control !== null,
              hint: control ?? undefined,
            })),
            { label: "Copy link", onSelect: onCopyLink },
            ...(closed
              ? []
              : [
                  {
                    label: "Cancel discussion",
                    onSelect: () => undefined,
                    disabled: true,
                    hint: NOT_YET,
                  },
                ]),
          ]}
        />
      </div>
      {blocked === null ? null : (
        <p id={reasonId} className="m-0 text-xs text-[var(--muted-foreground)]">
          {blocked}
        </p>
      )}
    </div>
  );
}
