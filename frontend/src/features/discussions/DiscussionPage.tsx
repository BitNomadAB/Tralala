import { useQuery } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { Link, useParams } from "react-router-dom";
import { usePageTitle } from "@/app/usePageTitle";
import { Breadcrumb, CRUMB_LINK } from "@/components/ui/breadcrumb";
import { loopPagePath, ticketPagePath } from "@/features/cards/ticketRules";
import { api } from "@/lib/api";
import { keys, useBoard, useLoop } from "@/lib/queries";
import { boardPagePath } from "./discussionRules";
import { DiscussionView } from "./DiscussionView";

const HERE = "max-w-[48ch] truncate font-medium text-[var(--foreground)]";

/**
 * A discussion as a page, a URL that can be sent, with the same view the dialog over the Kanban
 * shows. On a Ticket (`/boards/:boardId/loops/:loopId/tickets/:cardId/discussions/:discussionId`)
 * the breadcrumb is Board / Loop / the Ticket / the question, and Back to the Ticket goes to the
 * Ticket's page. On the board (`/boards/:boardId/discussions/:discussionId`) it is Board /
 * Discussions / the title, and Back to the board goes to the board. A thread with a Ticket opened
 * at the board's address still shows its Ticket.
 */
export function DiscussionPage() {
  const params = useParams();
  const boardId = params.boardId ?? "";
  const discussionId = params.discussionId ?? "";
  // The view reads the same query, so this costs no second request.
  const discussion = useQuery({
    queryKey: keys.discussion(boardId, discussionId),
    queryFn: () => api.getDiscussion(boardId, discussionId),
  });
  const loopId = params.loopId ?? discussion.data?.loop_id ?? "";
  const cardId = params.cardId ?? discussion.data?.card_id ?? "";
  const onTicket = Boolean(params.cardId) || Boolean(loopId && cardId);
  const board = useBoard(boardId);
  const loop = useLoop(boardId, onTicket ? loopId : "");
  usePageTitle(
    onTicket
      ? { page: "discussion", question: discussion.data?.goal }
      : { page: "board-discussion", title: discussion.data?.title, board: board.data?.name },
  );

  const boardCrumb = (
    <Link key="board" to={boardPagePath(boardId)} className={CRUMB_LINK}>
      <span className="font-semibold text-[var(--foreground)]">{board.data?.name ?? "Board"}</span>
    </Link>
  );
  const crumbs: ReactElement[] = onTicket
    ? [
        boardCrumb,
        <Link key="loop" to={loopPagePath(boardId, loopId)} className={CRUMB_LINK}>
          {loop.data ? `${loop.data.key} ${loop.data.name}` : "Loop"}
        </Link>,
        <Link key="ticket" to={ticketPagePath(boardId, loopId, cardId)} className={CRUMB_LINK}>
          {discussion.data?.ticket_key ?? discussion.data?.card_title ?? "Ticket"}
        </Link>,
        <span key="here" aria-current="page" className={HERE} title={discussion.data?.goal}>
          {discussion.data?.goal ?? "Discussion"}
        </span>,
      ]
    : [
        boardCrumb,
        <Link key="discussions" to="/discussions" className={CRUMB_LINK}>
          Discussions
        </Link>,
        <span key="here" aria-current="page" className={HERE} title={discussion.data?.title}>
          {discussion.data?.title ?? "Discussion"}
        </span>,
      ];

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb crumbs={crumbs} />
      <article className="mx-auto w-full max-w-[1180px]">
        <DiscussionView
          boardId={boardId}
          discussionId={discussionId}
          loopId={loopId || undefined}
          host="page"
        />
      </article>
    </div>
  );
}
