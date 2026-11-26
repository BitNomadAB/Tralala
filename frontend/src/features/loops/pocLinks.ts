import { loopHref } from "./loopNextAction";

/** A Ticket opened over the Loop's Decisions tab (`?tab=decisions&card=`), so closing it returns. */
export function pocTicketHref(boardId: string, loopId: string, cardId: string): string {
  return `${loopHref(boardId, loopId, "decisions")}&card=${encodeURIComponent(cardId)}`;
}
