import { useRef, useState, type ReactElement, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useToast } from "@/components/ui/useToast";
import { AskAgentsDialog } from "@/features/discussions/AskAgentsDialog";
import { ticketDiscussionPath } from "@/features/discussions/inboxRules";
import type { MarkdownOptions } from "@/lib/markdown";
import type { CardDetail } from "@/lib/types";
import { clipboard, cn } from "@/lib/utils";
import { TicketActions, type PrimaryAction } from "./TicketActions";
import type { ActivityTab } from "./TicketActivity";
import { TicketBody } from "./TicketBody";
import { TicketHead } from "./TicketHead";
import { TicketRail } from "./TicketRail";
import { completeBlocked, phaseName, ticketPagePath } from "./ticketRules";
import type { useCardComments } from "./useCardComments";
import { useTicketActions } from "./useTicketActions";
import type { useTicketData } from "./useTicketData";
import { useTicketDiscussions } from "./useTicketDiscussions";
import { useTicketFocus, type Decision } from "./useTicketFocus";

/**
 * The view once the card has loaded: the head, the main column and the rail, and "Ask the agents"
 * (from Activity's header or the actions' More), which opens the new discussion where the Ticket
 * is shown: in the dialog over the Kanban, or as a page of the Ticket. A decision that takes away
 * its own button hands the focus on (`useTicketFocus`).
 */
export function TicketLayout({
  boardId,
  loopId,
  card,
  data,
  modal,
  onClose,
  pageHref,
  titleWrap,
  ticketHref,
  actorId,
  comments,
  checklists,
  focusOnOpen,
}: {
  boardId: string;
  loopId: string;
  card: CardDetail;
  data: ReturnType<typeof useTicketData>;
  modal: boolean;
  onClose: () => void;
  pageHref: string | undefined;
  titleWrap: ((heading: ReactElement) => ReactElement) | undefined;
  ticketHref: MarkdownOptions["ticketHref"] | undefined;
  actorId: string | undefined;
  comments: ReturnType<typeof useCardComments>;
  checklists: ReactNode;
  /** Gives the title the focus once shown: the dialog swapped this view in. */
  focusOnOpen: boolean;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const picker = useRef<HTMLInputElement | null>(null);
  const [waitOpen, setWaitOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const [activityTab, setActivityTab] = useState<ActivityTab>("comments");
  // The title is h1 on the page and h2 in the dialog; the sections are one level under it.
  const level = modal ? 3 : 2;
  const discussions = useTicketDiscussions(boardId, card.id, activityTab === "discussions");
  const discussionHref = (discussionId: string) =>
    ticketDiscussionPath(modal ? "modal" : "page", boardId, loopId, card.id, discussionId);
  const onAsk = data.readOnly
    ? undefined
    : () => {
        setAsking(true);
      };
  const actions = useTicketActions({
    boardId,
    loopId,
    card,
    lists: data.lists,
    actorId: actorId ?? null,
    refresh: data.refresh,
    onArchived: onClose,
  });
  const { root, heading, afterDecision } = useTicketFocus(focusOnOpen);

  /** Runs a decision; once it went through, the focus goes on from its button. */
  async function decide(change: () => Promise<boolean>, decision: Decision) {
    if (await change()) afterDecision(decision);
  }

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
    ? { kind: "start", onStart: () => void decide(actions.startWork, "start") }
    : completed || card.human_action_required
      ? null
      : {
          kind: "complete",
          onComplete: () => void decide(() => actions.setCompleted(true), "complete"),
          blocked: completeBlocked(card),
        };

  return (
    <div ref={root} className={cn(modal && "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]")}>
      <TicketHead
        card={card}
        headingRef={heading}
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
        pageHref={pageHref}
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
            onAsk={() => setAsking(true)}
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
            level={level}
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
            discussions={discussions}
            discussionHref={discussionHref}
            onAsk={onAsk}
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
            level={level}
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
            onConfirm={() => void decide(() => actions.confirm(""), "confirm")}
            onCopyLink={copyLink}
            checklists={checklists}
          />
        </div>
      </div>
      <AskAgentsDialog
        key={asking ? "open" : "closed"}
        open={asking}
        boardId={boardId}
        cardId={card.id}
        onClose={() => setAsking(false)}
        onAsked={(discussionId) => {
          setAsking(false);
          void navigate(discussionHref(discussionId));
        }}
      />
    </div>
  );
}
