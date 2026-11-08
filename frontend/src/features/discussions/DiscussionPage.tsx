import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Breadcrumb, CRUMB_LINK } from "@/components/ui/breadcrumb";
import { loopPagePath, ticketPagePath } from "@/features/cards/ticketRules";
import { api } from "@/lib/api";
import { keys, useBoard, useLoop } from "@/lib/queries";
import { DiscussionView } from "./DiscussionView";

/**
 * A discussion as a page of its Ticket
 * (`/boards/:boardId/loops/:loopId/tickets/:cardId/discussions/:discussionId`), a URL that can be
 * sent: the breadcrumb Board / Loop / the Ticket / the question, and the same view the dialog over
 * the Kanban shows. Back to the Ticket goes to the Ticket's page.
 */
export function DiscussionPage() {
  const { boardId = "", loopId = "", cardId = "", discussionId = "" } = useParams();
  const board = useBoard(boardId);
  const loop = useLoop(boardId, loopId);
  // The view reads the same query, so this costs no second request.
  const discussion = useQuery({
    queryKey: keys.discussion(boardId, discussionId),
    queryFn: () => api.getDiscussion(boardId, discussionId),
  });

  const crumbs = [
    <Link key="board" to={`/boards/${encodeURIComponent(boardId)}`} className={CRUMB_LINK}>
      <span className="font-semibold text-[var(--foreground)]">{board.data?.name ?? "Board"}</span>
    </Link>,
    <Link key="loop" to={loopPagePath(boardId, loopId)} className={CRUMB_LINK}>
      {loop.data ? `${loop.data.key} ${loop.data.name}` : "Loop"}
    </Link>,
    <Link key="ticket" to={ticketPagePath(boardId, loopId, cardId)} className={CRUMB_LINK}>
      {discussion.data?.ticket_key ?? discussion.data?.card_title ?? "Ticket"}
    </Link>,
    <span
      key="here"
      aria-current="page"
      className="max-w-[48ch] truncate font-medium text-[var(--foreground)]"
      title={discussion.data?.goal}
    >
      {discussion.data?.goal ?? "Discussion"}
    </span>,
  ];

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb crumbs={crumbs} />
      <article className="mx-auto w-full max-w-[1180px]">
        <DiscussionView boardId={boardId} discussionId={discussionId} loopId={loopId} host="page" />
      </article>
    </div>
  );
}
