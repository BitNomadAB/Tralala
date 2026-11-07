import type { Card } from "@/lib/types";

/**
 * The Ticket-key resolver the Loop page gives the Markdown renderer: a key of a Ticket the page has
 * loaded becomes the path that opens it (`?card=` on this Loop page); any other key stays text, so
 * a link never points at a Ticket that does not exist.
 */
export function ticketHrefResolver(
  boardId: string,
  loopId: string,
  cards: Iterable<Pick<Card, "id" | "ticket_key">>,
): (key: string) => string | null {
  const ids = new Map<string, string>();
  for (const card of cards) {
    if (card.ticket_key) ids.set(card.ticket_key, card.id);
  }
  const page = `/boards/${encodeURIComponent(boardId)}/loops/${encodeURIComponent(loopId)}`;
  return (key) => {
    const id = ids.get(key);
    return id === undefined ? null : `${page}?card=${encodeURIComponent(id)}`;
  };
}
