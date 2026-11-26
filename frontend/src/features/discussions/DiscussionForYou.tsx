import { useAuth } from "@/features/auth/useAuth";
import type { Discussion } from "@/lib/types";
import { commentsOf, replyWords } from "./closingRules";
import { DiscussionComments } from "./DiscussionComments";
import { roundLines, stanceRows } from "./discussionData";
import { DiscussionExpanders } from "./DiscussionExpanders";
import { DiscussionReply } from "./DiscussionReply";
import { isClosed, isTalking, roundsText } from "./discussionRules";
import { StanceRows } from "./StanceRows";
import type { DiscussionViewState } from "./useDiscussionView";

/**
 * "For you": a row per agent, the expanders, the comments people and joined AIs wrote, and your
 * reply, which stays in a closed thread as a comment after the close and goes only once the
 * thread is decided for good.
 */
export function DiscussionForYou({
  boardId,
  discussion,
  view,
  level,
}: {
  boardId: string;
  discussion: Discussion;
  view: DiscussionViewState;
  /** The level of the headings under "Who stands where". */
  level: 3 | 4;
}) {
  const { actor } = useAuth();
  const synthesis = discussion.synthesis ?? null;
  const words = replyWords(discussion);
  return (
    <>
      <StanceRows
        rows={stanceRows(discussion)}
        failed={view.run?.failed ?? new Map()}
        level={level}
      />
      <DiscussionExpanders
        conditions={synthesis?.conditions ?? []}
        openQuestions={synthesis?.open_questions ?? []}
        rounds={roundLines(discussion, actor?.id ?? null)}
        roundsHint={roundsText(discussion)}
      />
      <DiscussionComments boardId={boardId} comments={commentsOf(discussion)} level={level} />
      {isClosed(discussion) ? null : (
        <DiscussionReply
          author={actor?.name ?? "You"}
          value={view.reply}
          onChange={view.setReply}
          ticket={view.ticket}
          onTicketChange={view.setTicket}
          refusal={view.replyRefusal}
          hint={words.hint}
          action={words.action}
          disabled={isTalking(discussion)}
          sending={view.sending}
          onSend={view.sendReply}
        />
      )}
    </>
  );
}
