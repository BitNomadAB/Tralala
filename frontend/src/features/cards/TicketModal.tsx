import { useRef, useState, type ReactElement } from "react";
import { Dialog, DialogFrame, DialogTitle } from "@/components/ui/dialog";
import { DiscussionView } from "@/features/discussions/DiscussionView";
import type { MarkdownOptions } from "@/lib/markdown";
import { afterArchiveTarget } from "./archiveFocus";
import { ticketPagePath } from "./ticketRules";
import { TicketView } from "./TicketView";

/**
 * A Ticket over the Kanban (`?card=` on the Loop page): the dialog frame around `TicketView`,
 * named by the Ticket's title. "Open as page" goes to the Ticket's own route. With a
 * `discussionId` (`?discussion=`) the same frame shows that discussion of the Ticket instead,
 * named by its question; "Back to the Ticket" hands the Ticket's id to `onBackToTicket`.
 * `returnFocus` names the element that takes the focus when the dialog closes (the card's title).
 * Once the frame has swapped one view for the other (Ask, a discussion's row, Back to the Ticket),
 * the new view's heading takes the focus, since the control that had it went with the old view.
 * A Ticket archived from the dialog leaves the board, so the focus goes to its column's Add card
 * instead of its card.
 */
export function TicketModal({
  boardId,
  loopId,
  cardId,
  discussionId = null,
  onClose,
  onBackToTicket,
  ticketHref,
  returnFocus,
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
  returnFocus?: (() => HTMLElement | null) | undefined;
}) {
  const titleWrap = (heading: ReactElement) => <DialogTitle asChild>{heading}</DialogTitle>;
  const view = discussionId ? `discussion:${discussionId}` : `ticket:${cardId ?? ""}`;
  const [shown, setShown] = useState(view);
  const [swapped, setSwapped] = useState(false);
  if (view !== shown) {
    setShown(view);
    setSwapped(true);
  }
  const archived = useRef(false);
  const focusOnClose = () => {
    const fallback = returnFocus?.() ?? null;
    return archived.current && cardId ? (afterArchiveTarget(cardId) ?? fallback) : fallback;
  };
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogFrame
        returnFocus={focusOnClose}
        className="inset-x-4 top-[calc(1.5rem+env(safe-area-inset-top,0px))] bottom-[calc(1.5rem+env(safe-area-inset-bottom,0px))] mx-auto max-w-[1140px] rounded-xl max-[700px]:inset-0 max-[700px]:rounded-none max-[700px]:border-0"
      >
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
            focusOnOpen={swapped}
          />
        ) : cardId ? (
          <TicketView
            boardId={boardId}
            loopId={loopId}
            cardId={cardId}
            host="modal"
            onClose={onClose}
            onArchived={() => {
              archived.current = true;
              onClose();
            }}
            pageHref={ticketPagePath(boardId, loopId, cardId)}
            titleWrap={titleWrap}
            ticketHref={ticketHref}
            focusOnOpen={swapped}
          />
        ) : null}
      </DialogFrame>
    </Dialog>
  );
}
