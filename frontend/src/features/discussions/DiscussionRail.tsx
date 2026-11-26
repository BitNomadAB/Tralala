import { useId } from "react";
import { Link } from "react-router-dom";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { ToneMark } from "@/components/ui/chip";
import { Expander } from "@/components/ui/expander";
import { Fact, Facts } from "@/components/ui/facts";
import { ReasonButton } from "@/components/ui/reason-button";
import { SectionHeader } from "@/components/ui/section";
import { useBoard } from "@/lib/queries";
import type { Discussion } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";
import {
  boardPagePath,
  NOT_YET,
  roundsText,
  runControlBlocked,
  runControls,
  stateOf,
  ticketOnLoopPath,
  tokensText,
  type RunAction,
} from "./discussionRules";

// The quiet button, made to read as a line of text in the rail's More.
const MORE_ITEM =
  "h-auto justify-start rounded border-0 px-0 py-0 text-left text-[13px] font-normal text-[var(--muted-foreground)] hover:bg-transparent hover:text-[var(--foreground)]";

const DANGER = "hover:text-[var(--destructive)]";

const LINK = "text-[13px] text-[var(--primary)] hover:underline";

/**
 * The rail beside the discussion, the Ticket rail's shape: where it stands in words, the facts
 * (the Ticket as a link that opens it over the Kanban, or the board for a discussion on the board,
 * who asked, the agents, the rounds, the tokens, when it started and when it was closed), and More
 * (Pause or Resume and Stop the run while the agents answer, Copy link, Cancel discussion). Status
 * and Facts are named groups, not landmarks: the rail is the one landmark. Their headings sit at
 * `level`, under the view's heading.
 */
export function DiscussionRail({
  boardId,
  discussion,
  stoppedBy,
  onControl,
  busy,
  onCopyLink,
  level,
}: {
  boardId: string;
  discussion: Discussion;
  /** Who stopped the latest run, when the events say so. */
  stoppedBy: string | null;
  onControl: (action: RunAction) => void;
  busy: boolean;
  onCopyLink: () => void;
  level: 2 | 3;
}) {
  const statusId = useId();
  const factsId = useId();
  // Already read by the page; only a discussion on the board names it.
  const board = useBoard(discussion.card_id === null ? boardId : "");
  const control = runControlBlocked(discussion, busy);
  const state = stateOf(discussion, { decidedBy: discussion.decided_by_name, stoppedBy });
  const ticket = discussion.ticket_key ?? discussion.card_title ?? "Ticket";
  return (
    <aside aria-label="Status and facts" className="grid content-start gap-[22px]">
      <div role="group" aria-labelledby={statusId}>
        <SectionHeader id={statusId} title="Status" level={level} />
        <ToneMark tone={state.tone} word={state.word} reason={state.reason ?? undefined} />
      </div>

      <div role="group" aria-labelledby={factsId}>
        <SectionHeader id={factsId} title="Facts" level={level} />
        <Facts>
          {discussion.card_id === null ? (
            <Fact label="Board">
              <Link to={boardPagePath(boardId)} className={LINK}>
                {board.data?.name ?? "Board"}
              </Link>
            </Fact>
          ) : (
            <Fact label="Ticket">
              {discussion.loop_id ? (
                <Link
                  to={ticketOnLoopPath(boardId, discussion.loop_id, discussion.card_id)}
                  className={cn(LINK, "font-mono")}
                >
                  {ticket}
                </Link>
              ) : (
                <span className="font-mono text-[13px]">{ticket}</span>
              )}
            </Fact>
          )}
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
          {discussion.closed_at ? (
            <Fact label="Closed">{formatDate(discussion.closed_at)}</Fact>
          ) : null}
        </Facts>
      </div>

      <Expander title="More">
        <ul className="m-0 grid list-none gap-1.5 p-0">
          {runControls(discussion, true).map((item, index) => (
            // By place, not by action: Pause becomes Resume on the same button, which keeps focus.
            <li key={index}>
              <ReasonButton
                variant="quiet"
                size="sm"
                className={cn(MORE_ITEM, item.action === "stop" && DANGER)}
                disabledReason={control}
                onClick={() => onControl(item.action)}
              >
                {item.label}
              </ReasonButton>
            </li>
          ))}
          <li>
            <Button variant="quiet" size="sm" className={MORE_ITEM} onClick={onCopyLink}>
              Copy link
            </Button>
          </li>
          <li>
            <ReasonButton
              variant="quiet"
              size="sm"
              className={MORE_ITEM}
              disabledReason={NOT_YET}
              onClick={() => undefined}
            >
              Cancel discussion
            </ReasonButton>
          </li>
        </ul>
      </Expander>
    </aside>
  );
}
