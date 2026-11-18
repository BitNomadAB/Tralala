import { focusTarget } from "./useFocusAfter";

/** The title button of a Ticket's card on the Kanban (`data-ticket-open` in TicketCard). */
function cardTitle(cardId: string): HTMLElement | null {
  const titles = document.querySelectorAll<HTMLElement>("[data-ticket-open]");
  return Array.from(titles).find((title) => title.dataset.ticketOpen === cardId) ?? null;
}

/**
 * Where the focus goes when the Ticket's dialog closes because the Ticket was archived (WCAG
 * 2.4.3): not to its card, which leaves the board with it, but to "Add card" of the column it was
 * in (marked `data-focus-target="add-card"` in KanbanColumn), else to the page's main region. Null when neither is on the page (the dialog's own rule).
 */
export function afterArchiveTarget(cardId: string): HTMLElement | null {
  const addCard = focusTarget(cardTitle(cardId)?.closest("section"), "add-card");
  return addCard && !addCard.matches(":disabled") ? addCard : document.getElementById("main");
}

/**
 * After Undo the toast has gone with the focus; once the restored card is back on the board its
 * title takes the focus, unless the person has put it somewhere already.
 */
export function focusRestoredCard(cardId: string): void {
  requestAnimationFrame(() => {
    const active = document.activeElement;
    if (active !== null && active !== document.body) return;
    cardTitle(cardId)?.focus();
  });
}
