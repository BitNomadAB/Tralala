import { Button } from "@/components/ui/button";
import { Menu } from "@/components/ui/menu";
import type { Discussion } from "@/lib/types";
import { decisionBlocked, isClosed, type ReviewDecision } from "./discussionRules";

/**
 * The actions row under the sign: the person's decision (Approve as the primary, Request rework,
 * Veto), then Let them talk it out, then More (Copy link, Cancel discussion). A decided discussion
 * keeps only More; a decision that cannot be taken yet says why on its buttons.
 */
export function DiscussionActions({
  discussion,
  onReview,
  onTalk,
  onCopyLink,
}: {
  discussion: Discussion;
  onReview: (decision: ReviewDecision) => void;
  /** Runs the rounds that are left; absent until the run actions are wired. */
  onTalk?: (() => void) | undefined;
  onCopyLink: () => void;
}) {
  const closed = isClosed(discussion);
  const blocked = decisionBlocked(discussion);
  const decision = { disabled: blocked !== null, title: blocked ?? undefined };
  return (
    <div className="mb-4 mt-[18px] flex flex-wrap items-center gap-2">
      {closed ? null : (
        <>
          <Button size="sm" {...decision} onClick={() => onReview("approve")}>
            Approve
          </Button>
          <Button variant="secondary" size="sm" {...decision} onClick={() => onReview("rework")}>
            Request rework
          </Button>
          <Button variant="danger" size="sm" {...decision} onClick={() => onReview("veto")}>
            Veto
          </Button>
          <span aria-hidden="true" className="mx-1 h-5 w-px bg-[var(--border)]" />
          <Button
            variant="secondary"
            size="sm"
            disabled={onTalk === undefined}
            title={onTalk === undefined ? "Later" : undefined}
            onClick={onTalk}
          >
            Let them talk it out
          </Button>
        </>
      )}
      <Menu
        label="More actions"
        items={[
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
