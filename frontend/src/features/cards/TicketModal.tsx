import type { ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import { Dialog, DialogFrame, DialogTitle } from "@/components/ui/dialog";
import { DiscussionView } from "@/features/discussions/DiscussionView";
import type { MarkdownOptions } from "@/lib/markdown";
import { ticketPagePath } from "./ticketRules";
import { TicketView } from "./TicketView";

/**
 * A Ticket over the Kanban (`?card=` on the Loop page): the dialog frame around `TicketView`,
 * named by the Ticket's title. "Open as page" goes to the Ticket's own route. With a
 * `discussionId` (`?discussion=`) the same frame shows that discussion of the Ticket instead,
 * named by its question; "Back to the Ticket" hands the Ticket's id to `onBackToTicket`.
 */
export function TicketModal({
  boardId,
  loopId,
  cardId,
  discussionId = null,
  onClose,
  onBackToTicket,
  ticketHref,
}: {
  boardId: string;
  loopId: string;
  /** Null when only a discussion is named; the discussion knows its Ticket. */
  cardId: string | null;
  discussionId?: string | null | undefined;
  onClose: () => void;
  onBackToTicket?: ((cardId: string) => void) | undefined;
  /** Links a Ticket key in the description to that Ticket; the page knows which exist. */
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  const navigate = useNavigate();
  const titleWrap = (heading: ReactElement) => <DialogTitle asChild>{heading}</DialogTitle>;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogFrame className="inset-x-4 top-[calc(1.5rem+env(safe-area-inset-top,0px))] bottom-[calc(1.5rem+env(safe-area-inset-bottom,0px))] mx-auto max-w-[1140px] rounded-xl max-[700px]:inset-0 max-[700px]:rounded-none max-[700px]:border-0">
        {discussionId ? (
          <DiscussionView
            key={discussionId}
            boardId={boardId}
            discussionId={discussionId}
            loopId={loopId}
            host="modal"
            onBack={onBackToTicket}
            onClose={onClose}
            titleWrap={titleWrap}
          />
        ) : cardId ? (
          <TicketView
            boardId={boardId}
            loopId={loopId}
            cardId={cardId}
            host="modal"
            onClose={onClose}
            onOpenPage={() => void navigate(ticketPagePath(boardId, loopId, cardId))}
            titleWrap={titleWrap}
            ticketHref={ticketHref}
          />
        ) : null}
      </DialogFrame>
    </Dialog>
  );
}
