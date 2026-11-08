import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { DiscussionRows, type DiscussionRowItem } from "@/features/discussions/DiscussionRows";
import {
  noTicketDiscussion,
  ticketDiscussionAside,
  ticketDiscussionMark,
  ticketDiscussionMeta,
} from "@/features/discussions/inboxRules";
import { describeError } from "@/lib/describeError";
import type { Discussion } from "@/lib/types";
import type { TicketDiscussions as TicketDiscussionsState } from "./useTicketDiscussions";

function item(discussion: Discussion): DiscussionRowItem {
  return {
    id: discussion.id,
    mark: ticketDiscussionMark(discussion),
    question: discussion.goal,
    aside: ticketDiscussionAside(discussion),
    meta: ticketDiscussionMeta(discussion),
  };
}

/**
 * The Discussions tab: the Ticket's discussions as rows (the verdict or the state while the
 * agents answer, the question, what it waits for or the decision, and the agents, sides, round,
 * who asked and when), each opening the discussion where the Ticket is shown (`hrefFor`). With
 * none it says so and offers "Ask the agents" (`onAsk`, absent on a read-only Ticket).
 */
export function TicketDiscussions({
  discussions,
  hrefFor,
  onAsk,
}: {
  discussions: TicketDiscussionsState;
  hrefFor: (discussionId: string) => string;
  onAsk: (() => void) | undefined;
}) {
  if (discussions.error) {
    return (
      <p role="alert" className="m-0 text-sm text-[var(--destructive)]">
        {describeError(discussions.error, "Could not read the discussions.")}
      </p>
    );
  }
  if (discussions.loading) {
    return <p className="m-0 text-sm text-[var(--muted-foreground)]">Reading the discussions…</p>;
  }
  if (discussions.rows.length === 0) {
    return (
      <div className="grid justify-items-start gap-3">
        <EmptyState message={noTicketDiscussion(onAsk === undefined)} />
        {onAsk ? (
          <Button variant="secondary" size="sm" onClick={onAsk}>
            Ask the agents
          </Button>
        ) : null}
      </div>
    );
  }
  return (
    <DiscussionRows
      rows={discussions.rows.map(item)}
      label="Discussions"
      hrefFor={(row) => hrefFor(row.id)}
    />
  );
}
