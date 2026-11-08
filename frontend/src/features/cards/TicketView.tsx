import { useRef, useState, type ReactElement, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { useToast } from "@/components/ui/useToast";
import { useAuth } from "@/features/auth/useAuth";
import { describeError } from "@/lib/describeError";
import type { MarkdownOptions } from "@/lib/markdown";
import type { CardDetail } from "@/lib/types";
import { clipboard, cn } from "@/lib/utils";
import { useCardTools } from "@/webmcp/useWebMcp";
import { CardChecklists } from "./CardChecklists";
import { TicketActions, type PrimaryAction } from "./TicketActions";
import type { ActivityTab } from "./TicketActivity";
import { TicketBody } from "./TicketBody";
import { TicketHead } from "./TicketHead";
import { TicketRail } from "./TicketRail";
import { completeBlocked, phaseName, ticketPagePath } from "./ticketRules";
import { useCardChecklists } from "./useCardChecklists";
import { useCardComments } from "./useCardComments";
import { useTicketActions } from "./useTicketActions";
import { useTicketData } from "./useTicketData";

/**
 * One Ticket, the same tree over the Kanban (`TicketModal`) and on its own page (`TicketPage`):
 * the head with the decision, the main column, and the rail with the column, the state and the
 * facts. The hosts only draw the frame around it.
 */
export function TicketView({
  boardId,
  loopId,
  cardId,
  host,
  onClose,
  onOpenPage,
  titleWrap,
  ticketHref,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  host: "modal" | "page";
  /** Leaves the Ticket: closes the dialog, or goes back to the board from the page. */
  onClose: () => void;
  onOpenPage?: (() => void) | undefined;
  /** Wraps the title heading, so the dialog is named by it. */
  titleWrap?: ((heading: ReactElement) => ReactElement) | undefined;
  ticketHref?: MarkdownOptions["ticketHref"];
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

  if (data.card.isLoading) {
    return (
      <div className="p-7">
        {wrap(<h2 className="sr-only">Ticket</h2>)}
        <p className="text-sm text-[var(--muted-foreground)]">Loading Ticket…</p>
      </div>
    );
  }
  if (!card) {
    return (
      <div className="p-7">
        {wrap(<h2 className="sr-only">Ticket</h2>)}
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
      onOpenPage={onOpenPage}
      titleWrap={titleWrap}
      ticketHref={ticketHref}
      actorId={actor?.id}
      comments={comments}
      checklists={
        <CardChecklists
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

/** The view once the card has loaded: the head, the main column and the rail. */
function TicketLayout({
  boardId,
  loopId,
  card,
  data,
  modal,
  onClose,
  onOpenPage,
  titleWrap,
  ticketHref,
  actorId,
  comments,
  checklists,
}: {
  boardId: string;
  loopId: string;
  card: CardDetail;
  data: ReturnType<typeof useTicketData>;
  modal: boolean;
  onClose: () => void;
  onOpenPage: (() => void) | undefined;
  titleWrap: ((heading: ReactElement) => ReactElement) | undefined;
  ticketHref: MarkdownOptions["ticketHref"] | undefined;
  actorId: string | undefined;
  comments: ReturnType<typeof useCardComments>;
  checklists: ReactNode;
}) {
  const toast = useToast();
  const picker = useRef<HTMLInputElement | null>(null);
  const [waitOpen, setWaitOpen] = useState(false);
  const [activityTab, setActivityTab] = useState<ActivityTab>("comments");
  const actions = useTicketActions({
    boardId,
    loopId,
    card,
    lists: data.lists,
    actorId: actorId ?? null,
    refresh: data.refresh,
    onArchived: onClose,
  });

  function copy(text: string, done: string) {
    const target = clipboard();
    if (!target) {
      toast.push({ title: "This browser does not allow copying here", variant: "warning" });
      return;
    }
    target.writeText(text).then(
      () => toast.push({ title: done, variant: "success" }),
      () => toast.push({ title: "Could not copy", variant: "error" }),
    );
  }
  const copyLink = () => {
    copy(`${window.location.origin}${ticketPagePath(boardId, loopId, card.id)}`, "Link copied");
  };

  const completed = card.completed_at !== null;
  const primary: PrimaryAction = actions.startTarget
    ? { kind: "start", onStart: () => void actions.startWork() }
    : completed || card.human_action_required
      ? null
      : {
          kind: "complete",
          onComplete: () => void actions.setCompleted(true),
          blocked: completeBlocked(card),
        };

  return (
    <div className={cn(modal && "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]")}>
      <TicketHead
        card={card}
        phase={
          card.phase_number === null
            ? null
            : { number: card.phase_number, name: phaseName(card, data.readiness) }
        }
        level={modal ? 2 : 1}
        titleWrap={titleWrap}
        readOnly={data.readOnly}
        onSaveTitle={(title) => void actions.update({ title })}
        onCopyKey={(key) => copy(key, "Copied")}
        onOpenPage={onOpenPage}
        onClose={modal ? onClose : undefined}
        page={!modal}
        actions={
          <TicketActions
            primary={primary}
            pending={actions.pending}
            readOnly={data.readOnly}
            completed={completed}
            waiting={card.waiting_for !== "nothing"}
            onWait={() => setWaitOpen(true)}
            onComment={() => {
              // The composer is in the Comments tab: show it before it takes the focus.
              flushSync(() => setActivityTab("comments"));
              comments.commentField.current?.focus();
            }}
            onAddFile={() => picker.current?.click()}
            onCopyLink={copyLink}
            onReopen={() => void actions.setCompleted(false)}
            onArchive={actions.archive}
          />
        }
      />
      <div
        className={cn("px-4 pb-10 pt-[26px] sm:px-7", modal && "overflow-y-auto scrollbar-thin")}
      >
        <div className="grid grid-cols-1 gap-7 min-[860px]:grid-cols-[minmax(0,1fr)_280px] min-[860px]:gap-11">
          <TicketBody
            boardId={boardId}
            loopId={loopId}
            card={card}
            readOnly={data.readOnly}
            readOnlyReason={
              data.loop?.stage === "completed"
                ? "This Loop is completed; notes are read-only."
                : "This Ticket is read-only, so notes cannot be added or changed."
            }
            actorId={actorId}
            live={data.live}
            comments={comments}
            history={data.history}
            readiness={data.readiness}
            people={data.people}
            ticketHref={ticketHref}
            picker={picker}
            activityTab={activityTab}
            onActivityTabChange={setActivityTab}
            onSaveDescription={(description) => actions.update({ description })}
            refresh={data.refresh}
          />
          <TicketRail
            boardId={boardId}
            loopId={loopId}
            card={card}
            lists={data.lists}
            readiness={data.readiness}
            people={data.people}
            labels={data.labels}
            readOnly={data.readOnly}
            actions={actions}
            refresh={data.refresh}
            waitOpen={waitOpen}
            onWaitOpenChange={setWaitOpen}
            onCopyLink={copyLink}
            checklists={checklists}
          />
        </div>
      </div>
    </div>
  );
}
