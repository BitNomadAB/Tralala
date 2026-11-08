import { Button } from "@/components/ui/button";
import { Menu } from "@/components/ui/menu";
import type { Discussion } from "@/lib/types";
import {
  decisionBlocked,
  isClosed,
  isTalking,
  runControls,
  talkBlocked,
  type ReviewDecision,
  type RunAction,
} from "./discussionRules";

/**
 * The actions row under the sign: the person's decision (Approve as the primary, Request rework,
 * Veto), then Let them talk it out, then More (Copy link, Cancel discussion). While the agents
 * answer, Stop takes the place of the decision and More holds Pause or Resume. A decided
 * discussion keeps Let them talk it out, disabled with the reason, and More; an action that
 * cannot be taken yet says why on its button.
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
  const closed = isClosed(discussion);
  const talking = isTalking(discussion);
  const blocked = decisionBlocked(discussion);
  const decision = { disabled: blocked !== null, title: blocked ?? undefined };
  const talkReason = talkBlocked(discussion);
  return (
    <div className="mb-4 mt-[18px] flex flex-wrap items-center gap-2">
      {talking ? (
        <Button
          variant="danger-quiet"
          size="sm"
          disabled={busy || !discussion.active_run}
          onClick={() => onControl("stop")}
        >
          Stop
        </Button>
      ) : (
        <>
          {closed ? null : (
            <>
              <Button size="sm" {...decision} onClick={() => onReview("approve")}>
                Approve
              </Button>
              <Button
                variant="secondary"
                size="sm"
                {...decision}
                onClick={() => onReview("rework")}
              >
                Request rework
              </Button>
              <Button variant="danger" size="sm" {...decision} onClick={() => onReview("veto")}>
                Veto
              </Button>
              <span aria-hidden="true" className="mx-1 h-5 w-px bg-[var(--border)]" />
            </>
          )}
          <Button
            variant="secondary"
            size="sm"
            disabled={talkReason !== null || busy}
            title={talkReason ?? undefined}
            onClick={onTalk}
          >
            Let them talk it out
          </Button>
        </>
      )}
      <Menu
        label="More actions"
        items={[
          ...runControls(discussion).map((item) => ({
            label: item.label,
            onSelect: () => onControl(item.action),
            disabled: busy || !discussion.active_run,
          })),
          { label: "Copy link", onSelect: onCopyLink },
          ...(closed
            ? []
            : [
                {
                  label: "Cancel discussion",
                  onSelect: () => undefined,
                  disabled: true,
                  hint: "Later",
                },
              ]),
        ]}
      />
    </div>
  );
}
