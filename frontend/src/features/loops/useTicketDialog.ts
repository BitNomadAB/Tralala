import { useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Which Ticket the Loop page shows over its tabs, and which of its discussions: `?card=` opens a
 * Ticket (and a later change of it, a Ticket key's link, opens that one), `?discussion=` shows a
 * discussion of it in the same dialog. Back to the Ticket drops the discussion and sets `?card=`
 * again; Close drops both.
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

  const openCard = useCallback((id: string) => setCardId(id), []);

  const close = useCallback(() => {
    setCardId(null);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("card");
        next.delete("discussion");
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

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
    cardId,
    discussionId,
    open: cardId !== null || discussionId !== null,
    openCard,
    close,
    backToTicket,
  };
}
