import { useCallback, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

/** The title button of the Ticket's card on the Kanban (`data-ticket-open` in TicketCard). */
function cardTitle(cardId: string | null): HTMLElement | null {
  if (cardId === null) return null;
  const titles = document.querySelectorAll<HTMLElement>("[data-ticket-open]");
  return Array.from(titles).find((title) => title.dataset.ticketOpen === cardId) ?? null;
}

/**
 * Which Ticket the Loop page shows over its tabs, and which of its discussions: `?card=` opens a
 * Ticket (and a later change of it, a Ticket key's link, opens that one), `?discussion=` shows a
 * discussion of it in the same dialog. Back to the Ticket drops the discussion and sets `?card=`
 * again; Close drops both, and `?focus=` (the button a link to the Ticket's decision focused).
 *
 * `returnFocus` says where the focus goes when the dialog closes (WCAG 2.4.3): back to what opened
 * it, the card's title, while that is still on the page, else to the title of the card the dialog
 * showed (it moved to another column meanwhile, or the dialog was opened from a link).
 */
export function useTicketDialog() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlCard = searchParams.get("card");
  const discussionId = searchParams.get("discussion");
  const [cardId, setCardId] = useState<string | null>(urlCard);
  const [seenCard, setSeenCard] = useState<string | null>(urlCard);
  if (urlCard !== seenCard) {
    setSeenCard(urlCard);
    if (urlCard !== null) setCardId(urlCard);
  }

  const opener = useRef<HTMLElement | null>(null);
  const shownCard = useRef<string | null>(null);

  const openCard = useCallback((id: string) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setCardId(id);
  }, []);

  const returnFocus = useCallback((): HTMLElement | null => {
    const target = opener.current;
    opener.current = null;
    if (target?.isConnected && target !== document.body) return target;
    return cardTitle(shownCard.current);
  }, []);

  const close = useCallback(() => {
    shownCard.current = cardId;
    setCardId(null);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("card");
        next.delete("discussion");
        // A link's button (`?focus=`, useTicketFocus) belongs to the Ticket that closes.
        next.delete("focus");
        return next;
      },
      { replace: true },
    );
  }, [cardId, setSearchParams]);

  const backToTicket = useCallback(
    (id: string) => {
      setCardId(id);
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("discussion");
          next.set("card", id);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return {
    returnFocus,
    cardId,
    discussionId,
    open: cardId !== null || discussionId !== null,
    openCard,
    close,
    backToTicket,
  };
}
