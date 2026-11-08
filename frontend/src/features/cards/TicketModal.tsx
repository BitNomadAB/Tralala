import { useNavigate } from "react-router-dom";
import { Dialog, DialogFrame, DialogTitle } from "@/components/ui/dialog";
import type { MarkdownOptions } from "@/lib/markdown";
import { ticketPagePath } from "./ticketRules";
import { TicketView } from "./TicketView";

/**
 * A Ticket over the Kanban (`?card=` on the Loop page): the dialog frame around `TicketView`,
 * named by the Ticket's title. "Open as page" goes to the Ticket's own route.
 */
export function TicketModal({
  boardId,
  loopId,
  cardId,
  onClose,
  ticketHref,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  onClose: () => void;
  /** Links a Ticket key in the description to that Ticket; the page knows which exist. */
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  const navigate = useNavigate();
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogFrame className="inset-x-4 top-[calc(1.5rem+env(safe-area-inset-top,0px))] bottom-[calc(1.5rem+env(safe-area-inset-bottom,0px))] mx-auto max-w-[1140px] rounded-xl max-[700px]:inset-0 max-[700px]:rounded-none max-[700px]:border-0">
        <TicketView
          boardId={boardId}
          loopId={loopId}
          cardId={cardId}
          host="modal"
          onClose={onClose}
          onOpenPage={() => void navigate(ticketPagePath(boardId, loopId, cardId))}
          titleWrap={(heading) => <DialogTitle asChild>{heading}</DialogTitle>}
          ticketHref={ticketHref}
        />
      </DialogFrame>
    </Dialog>
  );
}
