import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Breadcrumb, CRUMB_LINK } from "@/components/ui/breadcrumb";
import { api } from "@/lib/api";
import { keys, useBoard, useLoop, useReadiness } from "@/lib/queries";
import { loopPagePath, phaseText } from "./ticketRules";
import { TicketView } from "./TicketView";

/**
 * A Ticket on its own page (`/boards/:boardId/loops/:loopId/tickets/:cardId`), a URL that can be
 * sent: the breadcrumb Board / Loop / Phase / key, "Back to the board", and the same view the
 * dialog over the Kanban shows.
 */
export function TicketPage() {
  const { boardId = "", loopId = "", cardId = "" } = useParams();
  const navigate = useNavigate();
  const board = useBoard(boardId);
  const loop = useLoop(boardId, loopId);
  const readiness = useReadiness(boardId, loopId);
  // The view reads the same query, so this costs no second request.
  const card = useQuery({
    queryKey: keys.card(boardId, loopId, cardId),
    queryFn: () => api.getCard(boardId, loopId, cardId),
  });
  const loopPath = loopPagePath(boardId, loopId);
  const phase = card.data ? phaseText(card.data, readiness.data) : null;

  const crumbs = [
    <Link key="board" to={`/boards/${encodeURIComponent(boardId)}`} className={CRUMB_LINK}>
      <span className="font-semibold text-[var(--foreground)]">{board.data?.name ?? "Board"}</span>
    </Link>,
    <Link key="loop" to={loopPath} className={CRUMB_LINK}>
      {loop.data ? `${loop.data.key} ${loop.data.name}` : "Loop"}
    </Link>,
    ...(phase ? [<span key="phase">{phase}</span>] : []),
    <span key="here" aria-current="page" className="font-medium text-[var(--foreground)]">
      {card.data?.ticket_key ?? card.data?.title ?? "Ticket"}
    </span>,
  ];

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        crumbs={crumbs}
        trailing={
          <Link to={loopPath} className={`inline-flex items-center gap-1.5 ${CRUMB_LINK}`}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to the board
          </Link>
        }
      />
      <article className="mx-auto w-full max-w-[1180px]">
        <TicketView
          boardId={boardId}
          loopId={loopId}
          cardId={cardId}
          host="page"
          onClose={() => void navigate(loopPath)}
        />
      </article>
    </div>
  );
}
