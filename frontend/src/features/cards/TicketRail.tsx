import type { ReactNode } from "react";
import { Expander } from "@/components/ui/expander";
import { ReasonButton } from "@/components/ui/reason-button";
import { SectionHeader } from "@/components/ui/section";
import { SelectMenu } from "@/components/ui/select-menu";
import type { BoardList, BoardPerson, Card, Label, LoopReadiness } from "@/lib/types";
import { NoReportLine } from "./NoReport";
import { TicketFacts } from "./TicketFacts";
import { TicketHoldUps } from "./TicketHoldUps";
import { columnsInOrder, completeBlocked } from "./ticketRules";
import { TicketState } from "./TicketState";
import { NOT_YET } from "./ticketWork";
import type { TicketActions } from "./useTicketActions";

const MORE_ITEM =
  "rounded text-left text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/** MORE_ITEM for a `Button`: its size and fill taken off, so it reads as the links beside it. */
const MORE_BUTTON =
  "h-auto justify-start rounded border-0 px-0 py-0 text-left text-[13px] font-normal text-[var(--muted-foreground)] hover:bg-transparent hover:text-[var(--foreground)]";

/**
 * The rail beside the Ticket: its column as a menu with each column's count, where it stands (with
 * what holds a blocked Ticket up and the button that takes each of those away), the Details, and
 * More (checklists, Copy link, Move to another Loop, Archive).
 */
export function TicketRail({
  level,
  boardId,
  loopId,
  card,
  lists,
  readiness,
  people,
  labels,
  readOnly,
  actions,
  refresh,
  waitOpen,
  onWaitOpenChange,
  onConfirm,
  ticketLink,
  afterUnblock,
  checklists,
  onCopyLink,
}: {
  /** The heading level of Details: 2 under the page's h1, 3 under the dialog's h2. */
  level: 2 | 3;
  boardId: string;
  loopId: string;
  card: Card;
  lists: readonly BoardList[];
  readiness: LoopReadiness | undefined;
  people: readonly BoardPerson[];
  labels: readonly Label[];
  readOnly: boolean;
  actions: TicketActions;
  refresh: () => void;
  waitOpen: boolean;
  onWaitOpenChange: (open: boolean) => void;
  /** A person's confirmation of a human-only Ticket. */
  onConfirm: () => void;
  /** Where another Ticket of this Loop opens: in the dialog, or on its own page. */
  ticketLink: (cardId: string) => string;
  /** What takes the focus once nothing holds the Ticket up any more: its own decision. */
  afterUnblock: () => HTMLElement | null;
  checklists: ReactNode;
  onCopyLink: () => void;
}) {
  const columns = columnsInOrder(lists);
  const checklistCount = card.checklist_total;

  return (
    <aside
      aria-label="Status and details"
      className="grid min-w-0 grid-cols-1 content-start gap-[22px] [overflow-wrap:anywhere]"
    >
      <section aria-label="Status" className="grid gap-2.5">
        <SelectMenu
          label="Column"
          value={card.list_id}
          options={columns.map((list) => ({
            value: list.id,
            label: list.name,
            count: list.card_count,
          }))}
          // Not disabled while a change is saved: the menu's button has the focus then, and a
          // disabled button would drop it. A choice made meanwhile waits for the next one.
          disabled={readOnly}
          onChange={(listId) => {
            if (!actions.pending) void actions.move(listId);
          }}
        />
        <TicketState
          boardId={boardId}
          loopId={loopId}
          card={card}
          readOnly={readOnly}
          onChanged={refresh}
          holdUps={
            readOnly || (card.completed_at !== null && !card.awaiting_confirmation) ? null : (
              <TicketHoldUps
                boardId={boardId}
                loopId={loopId}
                card={card}
                ticketLink={ticketLink}
                afterLast={afterUnblock}
                onChanged={refresh}
              />
            )
          }
          waitOpen={waitOpen}
          onWaitOpenChange={onWaitOpenChange}
          onConfirm={onConfirm}
          confirmBlocked={completeBlocked(card)}
          pending={actions.pending}
        />
        <NoReportLine card={card} />
      </section>

      <section aria-label="Details">
        <SectionHeader title="Details" level={level} />
        <TicketFacts
          card={card}
          readiness={readiness}
          people={people}
          labels={labels}
          readOnly={readOnly}
          actions={actions}
        />
      </section>

      <Expander title="More" hint={`Checklists (${String(checklistCount)})`}>
        {checklists}
        <ul className="m-0 grid list-none gap-1.5 p-0">
          <li>
            <button type="button" className={MORE_ITEM} onClick={onCopyLink}>
              Copy link
            </button>
          </li>
          <li>
            <ReasonButton
              variant="quiet"
              size="sm"
              className={MORE_BUTTON}
              disabledReason={NOT_YET}
              onClick={() => undefined}
            >
              Move to another Loop…
            </ReasonButton>
          </li>
          {readOnly ? null : (
            <li>
              <button
                type="button"
                className={`${MORE_ITEM} hover:text-[var(--destructive)]`}
                onClick={actions.archive}
              >
                Archive
              </button>
            </li>
          )}
        </ul>
      </Expander>
    </aside>
  );
}
