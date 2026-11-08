import { useState } from "react";
import { EmptyState } from "@/components/ui/empty-state";
import { Section } from "@/components/ui/section";
import { Tab, TabList, TabPanel, Tabs } from "@/components/ui/tabs";
import { renderMarkdown, type MarkdownOptions } from "@/lib/markdown";
import type { ActivityEntry, CardDetail } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { CardComments } from "./CardComments";
import { CardHistory } from "./CardHistory";
import { completionComments } from "./ticketText";
import type { useCardComments } from "./useCardComments";

/**
 * "Work": what a coding session recorded on the Ticket: the summary it wrote, the completion
 * (and a person's confirmation of a human-only one), and each completion comment with its
 * evidence. Says so when nothing is recorded yet.
 */
function TicketWork({
  card,
  ticketHref,
}: {
  card: CardDetail;
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  const summary = card.summary_source === "agent" && card.summary ? card.summary : null;
  const completions = completionComments(card.comments ?? []);
  if (summary === null && card.completed_at === null && completions.length === 0) {
    return (
      <EmptyState message="No work recorded yet. A coding session's summaries and the completion with its evidence appear here." />
    );
  }
  return (
    <ul aria-label="Work" className="m-0 grid list-none gap-3 p-0 text-sm">
      {summary ? (
        <li className="grid gap-1">
          <span className="text-xs text-[var(--foreground-faint)]">
            A coding session wrote the summary
          </span>
          <p className="m-0">{summary}</p>
          {card.summary_stale ? (
            <p className="m-0 text-xs text-[var(--warning)]">
              The Ticket changed after this summary was written; it may be out of date.
            </p>
          ) : null}
        </li>
      ) : null}
      {card.completed_at ? (
        <li>
          <b className="font-semibold">Completed</b>
          <span className="text-[var(--muted-foreground)]">
            {" "}
            · {formatDateTime(card.completed_at)}
          </span>
          {card.human_confirmed_at ? (
            <div className="text-xs text-[var(--foreground-faint)]">
              A person confirmed the human action · {formatDateTime(card.human_confirmed_at)}
            </div>
          ) : null}
        </li>
      ) : null}
      {completions.map((comment) => (
        <li key={comment.id} className="grid gap-1 rounded-lg border border-[var(--border)] p-3">
          <span className="text-xs text-[var(--foreground-faint)]">
            {comment.actor_name ?? "Unknown"} · {formatDateTime(comment.created_at)}
          </span>
          <div className="text-sm">{renderMarkdown(comment.content, { ticketHref })}</div>
        </li>
      ))}
    </ul>
  );
}

export type ActivityTab = "comments" | "history" | "work";

/**
 * "Activity": the Ticket's comments (live, with the composer), its history as event rows, and the
 * work a coding session recorded, as tabs. The composer stays mounted while another tab shows, so
 * the head's Comment can focus it once the Comments tab is back.
 */
export function TicketActivity({
  card,
  live,
  comments,
  history,
  nameOf,
  tab,
  onTabChange,
  ticketHref,
}: {
  card: CardDetail;
  live: boolean;
  comments: ReturnType<typeof useCardComments>;
  history: readonly ActivityEntry[];
  nameOf: (actorId: string) => string | null;
  /** The tab shown; the view owns it, so its Comment action can switch back to Comments. */
  tab?: ActivityTab | undefined;
  onTabChange?: ((tab: ActivityTab) => void) | undefined;
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  const [own, setOwn] = useState<ActivityTab>("comments");
  const shown = tab ?? own;
  const change = (next: string) => {
    const value: ActivityTab = next === "history" || next === "work" ? next : "comments";
    setOwn(value);
    onTabChange?.(value);
  };
  return (
    <Section title="Activity">
      <Tabs value={shown} onChange={change}>
        <TabList label="Activity">
          <Tab value="comments">Comments</Tab>
          <Tab value="history">History</Tab>
          <Tab value="work">Work</Tab>
        </TabList>
        <TabPanel value="comments">
          <CardComments
            live={live}
            mentions={comments.mentions}
            retrying={comments.retryMention.isPending}
            onRetryMention={(jobId) => comments.retryMention.mutate(jobId)}
            comments={card.comments ?? []}
            comment={comments.comment}
            onCommentChange={comments.changeComment}
            onCommentBlur={comments.closeSuggestions}
            suggestions={comments.suggestions}
            mentionIndex={comments.mentionIndex}
            onMentionIndexChange={comments.setMentionIndex}
            onChooseAgent={comments.chooseAgent}
            commentField={comments.commentField}
            onSubmitComment={(content) => comments.addComment.mutate(content)}
          />
        </TabPanel>
        <TabPanel value="history">
          <CardHistory entries={history} nameOf={nameOf} />
        </TabPanel>
        <TabPanel value="work">
          <TicketWork card={card} ticketHref={ticketHref} />
        </TabPanel>
      </Tabs>
    </Section>
  );
}
