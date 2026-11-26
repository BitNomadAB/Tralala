import { useId } from "react";
import { HeldButton } from "@/components/ui/held-button";
import { Menu } from "@/components/ui/menu";
import { ReasonButton } from "@/components/ui/reason-button";
import type { Discussion } from "@/lib/types";
import { closeBlocked, isThreadClosed, mayClose } from "./closingRules";
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
import type { DiscussionClosing } from "./useDiscussionClosing";

/**
 * The actions row under the sign: the person's decision (Approve as the primary, Request rework,
 * Veto), then Let them talk it out, Close discussion for the one who opened it, then More (Copy
 * link, Cancel discussion). A closed thread shows none of the decision or the run, only Reopen,
 * on the button Close discussion was, and More. While the agents answer, Stop comes first and
 * More holds Pause or Resume. A button that cannot be pressed says why and stays where it is, so
 * focus stays on it: the decision shares one reason line under the row. Only Stop, once the run
 * is over, the decision, once it is taken, and Reopen pressed by someone other than the opener
 * leave; the view then gives focus to its heading (`useFocusRescue`).
 */
export function DiscussionActions({
  discussion,
  onReview,
  onTalk,
  onControl,
  busy,
  onCopyLink,
  closing,
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
  /** Close discussion (after its question) and Reopen. */
  closing: Pick<DiscussionClosing, "ask" | "reopen" | "busy">;
}) {
  const reasonId = useId();
  const shut = isThreadClosed(discussion);
  const closed = isClosed(discussion) || shut;
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
        {shut ? null : (
          <ReasonButton
            variant="secondary"
            size="sm"
            disabledReason={talkBlocked(discussion) ?? (busy ? RUN_BUSY : null)}
            onClick={onTalk}
          >
            Let them talk it out
          </ReasonButton>
        )}
        {/* One place for Close discussion and Reopen, so the button pressed keeps focus. */}
        {shut || mayClose(discussion) ? (
          <ReasonButton
            variant="secondary"
            size="sm"
            disabledReason={
              shut
                ? closing.busy
                  ? "Opening the discussion again…"
                  : null
                : closeBlocked(discussion, closing.busy)
            }
            onClick={shut ? closing.reopen : closing.ask}
          >
            {shut ? "Reopen" : "Close discussion"}
          </ReasonButton>
        ) : null}
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
