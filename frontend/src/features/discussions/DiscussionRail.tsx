import { Link } from "react-router-dom";
import { Avatar } from "@/components/ui/avatar";
import { ToneMark } from "@/components/ui/chip";
import { Expander } from "@/components/ui/expander";
import { Fact, Facts } from "@/components/ui/facts";
import { SectionHeader } from "@/components/ui/section";
import type { Discussion } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { roundsText, stateOf, ticketOnLoopPath, tokensText } from "./discussionRules";

const MORE_ITEM =
  "rounded text-left text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:text-[var(--muted-foreground)]";

/**
 * The rail beside the discussion, the Ticket rail's shape: where it stands in words, the facts
 * (the Ticket as a link that opens it over the Kanban, who asked, the agents, the rounds, the
 * tokens, when it started), and More.
 */
export function DiscussionRail({
  boardId,
  discussion,
  onCopyLink,
}: {
  boardId: string;
  discussion: Discussion;
  onCopyLink: () => void;
}) {
  const state = stateOf(discussion);
  const ticket = discussion.ticket_key ?? discussion.card_title ?? "Ticket";
  return (
    <aside aria-label="Status and facts" className="grid content-start gap-[22px]">
      <section aria-label="Status">
        <SectionHeader title="Status" />
        <ToneMark tone={state.tone} word={state.word} reason={state.reason ?? undefined} />
      </section>

      <section aria-label="Facts">
        <SectionHeader title="Facts" />
        <Facts>
          <Fact label="Ticket">
            {discussion.loop_id ? (
              <Link
                to={ticketOnLoopPath(boardId, discussion.loop_id, discussion.card_id)}
                className="font-mono text-[13px] text-[var(--primary)] hover:underline"
              >
                {ticket}
              </Link>
            ) : (
              <span className="font-mono text-[13px]">{ticket}</span>
            )}
          </Fact>
          <Fact label="Asked by">
            <Avatar name={discussion.created_by_name} size="sm" />
            {discussion.created_by_name}
          </Fact>
          <Fact label="Agents">
            <span className="tabular-nums">{discussion.participants.length}</span>
          </Fact>
          <Fact label="Rounds">
            <span className="tabular-nums">{roundsText(discussion)}</span>
          </Fact>
          <Fact label="Tokens">
            <span className="tabular-nums">{tokensText(discussion.tokens_used)}</span>
          </Fact>
          <Fact label="Started">{formatDate(discussion.created_at)}</Fact>
        </Facts>
      </section>

      <Expander title="More">
        <ul className="m-0 grid list-none gap-1.5 p-0">
          <li>
            <button type="button" className={MORE_ITEM} onClick={onCopyLink}>
              Copy link
            </button>
          </li>
          <li>
            <button type="button" className={MORE_ITEM} disabled title="Later">
              Cancel discussion
            </button>
          </li>
        </ul>
      </Expander>
    </aside>
  );
}
