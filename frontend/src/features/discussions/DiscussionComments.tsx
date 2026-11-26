import { Link } from "react-router-dom";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { ticketPagePath } from "@/features/cards/ticketRules";
import { renderMarkdown } from "@/lib/markdown";
import type { DiscussionMessage } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { AFTER_CLOSING, ticketRefText } from "./closingRules";

/**
 * What people and AIs that joined by their key wrote in the thread, oldest first: who, when, the
 * mark "After closing" on a comment written while it was closed, a link to the Ticket a message
 * points at, and the text as Markdown, which never runs as HTML. Absent while there is none.
 */
export function DiscussionComments({
  boardId,
  comments,
  level,
}: {
  boardId: string;
  comments: readonly DiscussionMessage[];
  /** The heading's level, as the view's other sections under "Who stands where". */
  level: 3 | 4;
}) {
  if (comments.length === 0) return null;
  const sorted = [...comments].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return (
    <div className="grid gap-2">
      <SectionHeader title="Comments" count={comments.length} level={level} />
      <ol aria-label="Comments" className="m-0 grid list-none gap-4 p-0">
        {sorted.map((message) => {
          const ref = message.ref_ticket;
          const refText = ticketRefText(message);
          return (
            <li
              key={message.id}
              aria-label={`${message.author_name}, ${formatDateTime(message.created_at)}`}
              className="grid grid-cols-[auto_minmax(0,1fr)] gap-3"
            >
              <Avatar name={message.author_name} />
              <div className="grid min-w-0 gap-1">
                <p className="m-0 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]">
                  <span className="font-semibold text-[var(--foreground)]">
                    {message.author_name}
                  </span>
                  <span className="text-[var(--foreground-faint)]">
                    {formatDateTime(message.created_at)}
                  </span>
                  {message.after_closed ? <Badge>{AFTER_CLOSING}</Badge> : null}
                </p>
                {ref && refText ? (
                  <p className="m-0 text-[13px] text-[var(--muted-foreground)]">
                    About{" "}
                    <Link
                      to={ticketPagePath(boardId, ref.loop_id, ref.card_id)}
                      className="text-[var(--primary)] hover:underline"
                    >
                      {refText}
                    </Link>
                  </p>
                ) : null}
                <div className="max-w-[62ch] text-[15px] leading-normal">
                  {renderMarkdown(message.content, { headingLevel: level === 3 ? 4 : 5 })}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
