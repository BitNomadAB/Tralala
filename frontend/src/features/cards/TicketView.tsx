import type { ReactElement } from "react";
import { useToast } from "@/components/ui/useToast";
import { useAuth } from "@/features/auth/useAuth";
import { describeError } from "@/lib/describeError";
import type { MarkdownOptions } from "@/lib/markdown";
import { useCardTools } from "@/webmcp/useWebMcp";
import { CardChecklists } from "./CardChecklists";
import { TicketLayout } from "./TicketLayout";
import { useCardChecklists } from "./useCardChecklists";
import { useCardComments } from "./useCardComments";
import { useTicketData } from "./useTicketData";

/**
 * One Ticket, the same tree over the Kanban (`TicketModal`) and on its own page (`TicketPage`):
 * the head with the decision, the main column, and the rail with the column, the state and the
 * facts. The hosts only draw the frame around it. The title is the host's h1 on the page and the
 * dialog's h2, so every section under it is one level deeper: h2 on the page, h3 in the dialog.
 */
export function TicketView({
  boardId,
  loopId,
  cardId,
  host,
  onClose,
  onArchived,
  pageHref,
  titleWrap,
  ticketHref,
  focusOnOpen = false,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  host: "modal" | "page";
  /** Leaves the Ticket: closes the dialog, or goes back to the board from the page. */
  onClose: () => void;
  /** Leaves the Ticket once it is archived; `onClose` when not given. */
  onArchived?: (() => void) | undefined;
  /** The Ticket's own page, linked from the dialog's head. */
  pageHref?: string | undefined;
  /** Wraps the title heading, so the dialog is named by it. */
  titleWrap?: ((heading: ReactElement) => ReactElement) | undefined;
  ticketHref?: MarkdownOptions["ticketHref"];
  /** Gives the title the focus once the Ticket is shown: the host swapped it in. */
  focusOnOpen?: boolean | undefined;
}) {
  const toast = useToast();
  const { actor } = useAuth();
  const data = useTicketData(boardId, loopId, cardId);
  const onError = (error: unknown) => {
    toast.push({
      title: "Change rejected",
      description: describeError(error, undefined),
      variant: "error",
    });
    data.refresh();
  };
  const checklists = useCardChecklists({ boardId, loopId, cardId, refresh: data.refresh, onError });
  const comments = useCardComments({ boardId, loopId, cardId, refresh: data.refresh, onError });
  useCardTools({ boardId, loopId, cardId, onOpen: () => undefined, onClose });

  const card = data.card.data;
  const wrap = titleWrap ?? ((heading: ReactElement) => heading);
  const Heading = host === "page" ? "h1" : "h2";
  const sectionLevel = host === "page" ? 2 : 3;

  if (data.card.isLoading) {
    return (
      <div className="p-7">
        {/* Keeps the outline (and the dialog's name) until the title comes; route focus waits. */}
        {wrap(
          <Heading className="sr-only" data-heading-placeholder="">
            Ticket
          </Heading>,
        )}
        <p className="text-sm text-[var(--muted-foreground)]">Loading Ticket…</p>
      </div>
    );
  }
  if (!card) {
    return (
      <div className="p-7">
        {wrap(<Heading className="sr-only">Ticket</Heading>)}
        <p role="alert" className="text-sm text-[var(--destructive)]">
          {describeError(data.card.error, "Ticket unavailable.")}
        </p>
      </div>
    );
  }
  return (
    <TicketLayout
      boardId={boardId}
      loopId={loopId}
      card={card}
      data={data}
      modal={host === "modal"}
      onClose={onClose}
      onArchived={onArchived}
      pageHref={pageHref}
      titleWrap={titleWrap}
      ticketHref={ticketHref}
      actorId={actor?.id}
      comments={comments}
      focusOnOpen={focusOnOpen}
      checklists={
        <CardChecklists
          level={sectionLevel}
          checklists={card.checklists ?? []}
          checklistTitle={checklists.checklistTitle}
          onChecklistTitleChange={checklists.setChecklistTitle}
          onAddChecklist={checklists.addChecklist}
          itemText={checklists.itemText}
          onItemTextChange={checklists.changeItemText}
          onAddItem={checklists.addItem}
          onToggleItem={checklists.toggleItem}
        />
      }
    />
  );
}
