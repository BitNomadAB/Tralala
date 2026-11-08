import type { ReactNode } from "react";
import { Expander } from "@/components/ui/expander";
import { SectionHeader } from "@/components/ui/section";
import { SelectMenu } from "@/components/ui/select-menu";
import type { BoardList, BoardPerson, Card, Label, LoopReadiness } from "@/lib/types";
import { TicketFacts } from "./TicketFacts";
import { columnsInOrder, completeBlocked } from "./ticketRules";
import { TicketState } from "./TicketState";
import type { TicketActions } from "./useTicketActions";

const MORE_ITEM =
  "rounded text-left text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:text-[var(--muted-foreground)]";

/**
 * The rail beside the Ticket: its column as a menu with each column's count, where it stands,
 * the Details, and More (checklists, Copy link, Move to another Loop, Archive).
 */
export function TicketRail({
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
  checklists,
  onCopyLink,
}: {
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
  checklists: ReactNode;
  onCopyLink: () => void;
}) {
  const columns = columnsInOrder(lists);
  const checklistCount = card.checklist_total;

  return (
    <aside aria-label="Status and details" className="grid content-start gap-[22px]">
      <section aria-label="Status" className="grid gap-2.5">
        <SelectMenu
          label="Column"
          value={card.list_id}
          options={columns.map((list) => ({
            value: list.id,
            label: list.name,
            count: list.card_count,
          }))}
          disabled={readOnly || actions.pending}
          onChange={(listId) => void actions.move(listId)}
        />
        <TicketState
          boardId={boardId}
          loopId={loopId}
          card={card}
          readOnly={readOnly}
          onChanged={refresh}
          waitOpen={waitOpen}
          onWaitOpenChange={onWaitOpenChange}
          onConfirm={() => void actions.confirm("")}
          confirmBlocked={completeBlocked(card)}
          pending={actions.pending}
        />
      </section>

      <section aria-label="Details">
        <SectionHeader title="Details" />
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
            <button type="button" className={MORE_ITEM} disabled title="Later">
              Move to another Loop…
            </button>
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
