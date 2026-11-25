import { useId, useRef } from "react";
import { Link } from "react-router-dom";
import { ReasonButton } from "@/components/ui/reason-button";
import { useOpenCards } from "@/lib/queries";
import type { Card } from "@/lib/types";
import { SAVING } from "./ticketWork";
import { holdUps, NEED_LABELS, needHeld, needNote, ticketNeed, type TicketNeed } from "./unblock";
import { useFocusAfter } from "./useFocusAfter";
import { useUnblock } from "./useUnblock";

const LINK =
  "justify-self-start rounded text-[var(--primary)] hover:underline focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/** The button of a Ticket's row inside `list`, or null when the row is not there. */
function rowButton(list: Element | null, cardId: string): HTMLElement | null {
  const buttons = list?.querySelectorAll<HTMLElement>("[data-unblock]") ?? [];
  return Array.from(buttons).find((button) => button.dataset.unblock === cardId) ?? null;
}

/**
 * "Held up by", under the state of a Ticket the plan blocks: every open Ticket that has to be done
 * first, with a link that opens it and the one button for what it needs now (Confirm for a
 * person's task, Complete, Clear wait, Restore). A Ticket that waits for earlier work itself keeps
 * its button held with the reason, below the ones that can be pressed, so the list is worked from
 * the top and the blocked Ticket is freed without leaving it.
 *
 * It stays mounted while the Ticket is open and draws nothing when nothing holds the Ticket up, so
 * the focus is handed on after the last step too (WCAG 2.4.3): a row that changed keeps it on its
 * button, a row that went gives it to the next row's button, and after the last row `afterLast`
 * names what takes it (the Ticket's own decision).
 */
export function TicketHoldUps({
  boardId,
  loopId,
  card,
  ticketLink,
  afterLast,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  card: Card;
  /** Where another Ticket of this Loop opens: in the dialog, or on its own page. */
  ticketLink: (cardId: string) => string;
  /** What takes the focus once nothing holds the Ticket up any more. */
  afterLast: () => HTMLElement | null;
  onChanged: () => void;
}) {
  const blocked = card.completed_at === null && !card.ready && card.blockers.length > 0;
  const open = useOpenCards(boardId, loopId, blocked);
  const unblock = useUnblock({ boardId, loopId, onChanged });
  const focusAfter = useFocusAfter();
  const list = useRef<HTMLUListElement>(null);
  const headingId = useId();
  const rows = blocked ? holdUps(card, open.data ?? []) : [];

  async function act(row: Card, need: TicketNeed) {
    if (!(await unblock.run(row, need))) return;
    focusAfter(() => {
      const same = rowButton(list.current, row.id);
      // Still the button that was pressed: the answer has not reached the list yet.
      if (same) return same.dataset.need === need ? null : same;
      return list.current?.querySelector<HTMLElement>("[data-unblock]") ?? afterLast();
    });
  }

  if (rows.length === 0) return null;
  return (
    <div className="grid gap-2 rounded-md border border-[var(--border)] p-2.5 text-[13px]">
      <p id={headingId} className="m-0 font-medium">
        Held up by
      </p>
      <ul ref={list} aria-labelledby={headingId} className="m-0 grid list-none gap-3 p-0">
        {rows.map((row) => {
          const need = ticketNeed(row);
          if (need === null) return null;
          const note = needNote(row, need);
          return (
            <li key={row.id} className="grid gap-1">
              <Link to={ticketLink(row.id)} className={LINK}>
                {row.ticket_key ? (
                  <span className="font-mono text-xs font-semibold">{row.ticket_key}</span>
                ) : null}{" "}
                {row.title}
              </Link>
              {note ? <span className="text-xs text-[var(--muted-foreground)]">{note}</span> : null}
              <ReasonButton
                variant="secondary"
                size="sm"
                wrapperClassName="justify-self-start"
                data-unblock={row.id}
                data-need={need}
                aria-label={`${NEED_LABELS[need]} ${row.ticket_key ?? row.title}`}
                disabledReason={needHeld(row, need) ?? (unblock.pending ? SAVING : null)}
                onClick={() => void act(row, need)}
              >
                {NEED_LABELS[need]}
              </ReasonButton>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
