import { useId, useState, type ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import { SectionHeader } from "@/components/ui/section";
import { Segmented, SegmentedPanel } from "@/components/ui/segmented";
import { useToast } from "@/components/ui/useToast";
import { useAuth } from "@/features/auth/useAuth";
import { ticketPagePath } from "@/features/cards/ticketRules";
import { describeError } from "@/lib/describeError";
import type { Discussion } from "@/lib/types";
import { clipboard, cn } from "@/lib/utils";
import { DiscussionActions } from "./DiscussionActions";
import { roundLines, stanceRows } from "./discussionData";
import { DiscussionExpanders } from "./DiscussionExpanders";
import { DiscussionHead } from "./DiscussionHead";
import { DiscussionRail } from "./DiscussionRail";
import { DiscussionRaw } from "./DiscussionRaw";
import { DiscussionReply } from "./DiscussionReply";
import {
  discussionPagePath,
  isClosed,
  isTalking,
  outcomeLine,
  progressLine,
  replyHint,
  roundsText,
  stateOf,
  talkRounds,
  ticketOnLoopPath,
  type RunAction,
} from "./discussionRules";
import { DiscussionSign } from "./DiscussionSign";
import { ReviewDiscussionDialog } from "./ReviewDiscussionDialog";
import { StanceRows } from "./StanceRows";
import { TalkItOutDialog } from "./TalkItOutDialog";
import { useDiscussionView, type DiscussionViewState } from "./useDiscussionView";

type View = "you" | "raw";

const VIEWS = [
  { value: "you", label: "For you" },
  { value: "raw", label: "Raw text" },
] as const;

/** Where the view is shown: over the Kanban in the Ticket's dialog, or as a page of its Ticket. */
export type DiscussionHost = "modal" | "page";

/**
 * One discussion, the Ticket view's shape: the head with the question, the sign and the
 * decision, then "Who stands where" (For you: a row per agent, the expanders, your reply; Raw
 * text: everything the agents wrote) beside the rail with the status and the facts.
 */
export function DiscussionView({
  boardId,
  discussionId,
  loopId,
  host,
  onBack,
  onClose,
  titleWrap,
}: {
  boardId: string;
  discussionId: string;
  /** The Loop the host shows, for a thread whose Ticket the API could not place. */
  loopId?: string | undefined;
  host: DiscussionHost;
  /** Back to the Ticket in the dialog; elsewhere it navigates to the Ticket. */
  onBack?: ((cardId: string) => void) | undefined;
  onClose?: (() => void) | undefined;
  titleWrap?: ((heading: ReactElement) => ReactElement) | undefined;
}) {
  const view = useDiscussionView(boardId, discussionId);
  const discussion = view.query.data;
  const wrap = titleWrap ?? ((heading: ReactElement) => heading);

  if (view.query.isLoading) {
    return (
      <div className="p-7">
        {wrap(<h2 className="sr-only">Discussion</h2>)}
        <p className="text-sm text-[var(--muted-foreground)]">Loading discussion…</p>
      </div>
    );
  }
  if (!discussion) {
    return (
      <div className="p-7">
        {wrap(<h2 className="sr-only">Discussion</h2>)}
        <p role="alert" className="text-sm text-[var(--destructive)]">
          {describeError(view.query.error, "Discussion unavailable.")}
        </p>
      </div>
    );
  }
  return (
    <DiscussionLayout
      boardId={boardId}
      loopId={discussion.loop_id ?? loopId ?? null}
      discussion={discussion}
      view={view}
      host={host}
      onBack={onBack}
      onClose={onClose}
      titleWrap={titleWrap}
    />
  );
}

/** The view once the thread has loaded. */
function DiscussionLayout({
  boardId,
  loopId,
  discussion,
  view,
  host,
  onBack,
  onClose,
  titleWrap,
}: {
  boardId: string;
  loopId: string | null;
  discussion: Discussion;
  view: DiscussionViewState;
  host: DiscussionHost;
  onBack: ((cardId: string) => void) | undefined;
  onClose: (() => void) | undefined;
  titleWrap: ((heading: ReactElement) => ReactElement) | undefined;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const { actor } = useAuth();
  const idBase = useId();
  const headingId = useId();
  const [tab, setTab] = useState<View>("you");
  const modal = host === "modal";
  const cardId = discussion.card_id;
  const pagePath = loopId ? discussionPagePath(boardId, loopId, cardId, discussion.id) : null;

  const back = onBack
    ? () => {
        onBack(cardId);
      }
    : loopId
      ? () =>
          void navigate(
            host === "page"
              ? ticketPagePath(boardId, loopId, cardId)
              : ticketOnLoopPath(boardId, loopId, cardId),
          )
      : undefined;

  function copyLink() {
    const target = clipboard();
    if (!target || pagePath === null) {
      toast.push({ title: "This browser does not allow copying here", variant: "warning" });
      return;
    }
    target.writeText(`${window.location.origin}${pagePath}`).then(
      () => toast.push({ title: "Link copied", variant: "success" }),
      () => toast.push({ title: "Could not copy", variant: "error" }),
    );
  }

  const synthesis = discussion.synthesis ?? null;
  const { runs, run } = view;
  const talking = isTalking(discussion);
  const busy = runs.starting || runs.controlling;
  const stoppedBy = run?.stoppedBy ?? null;
  const control = (action: RunAction) => {
    const runId = discussion.active_run?.id;
    if (runId) runs.control(runId, action);
  };
  const activity = talking
    ? {
        state: stateOf(discussion),
        progress:
          discussion.run_state === "running"
            ? progressLine(run?.answered ?? 0, discussion.participants.length)
            : null,
      }
    : null;
  return (
    <div className={cn(modal && "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]")}>
      <DiscussionHead
        discussion={discussion}
        level={host === "page" ? 1 : 2}
        titleWrap={titleWrap}
        page={host === "page"}
        onBack={back}
        onOpenPage={host !== "page" && pagePath ? () => void navigate(pagePath) : undefined}
        onClose={modal ? onClose : undefined}
      >
        <DiscussionSign
          synthesis={synthesis}
          activity={activity}
          outcome={talking ? null : outcomeLine(run?.run ?? null, stoppedBy)}
        />
        <DiscussionActions
          discussion={discussion}
          onReview={view.setReviewing}
          onTalk={() => runs.setTalkOpen(true)}
          onControl={control}
          busy={busy}
          onCopyLink={copyLink}
        />
      </DiscussionHead>
      <div
        className={cn("px-4 pb-10 pt-[18px] sm:px-7", modal && "overflow-y-auto scrollbar-thin")}
      >
        <div className="mt-2 grid grid-cols-1 gap-7 min-[860px]:grid-cols-[minmax(0,1fr)_280px] min-[860px]:gap-11">
          <section aria-labelledby={headingId} className="grid min-w-0 content-start">
            <SectionHeader
              id={headingId}
              size="lg"
              title="Who stands where"
              trailing={
                <Segmented
                  label="View"
                  value={tab}
                  options={VIEWS}
                  onChange={setTab}
                  idBase={idBase}
                />
              }
            />
            <SegmentedPanel idBase={idBase} value="you" active={tab} className="grid gap-6">
              <StanceRows rows={stanceRows(discussion)} failed={run?.failed ?? new Map()} />
              <DiscussionExpanders
                conditions={synthesis?.conditions ?? []}
                openQuestions={synthesis?.open_questions ?? []}
                rounds={roundLines(discussion, actor?.id ?? null)}
                roundsHint={roundsText(discussion)}
              />
              {isClosed(discussion) ? null : (
                <DiscussionReply
                  author={actor?.name ?? "You"}
                  value={view.reply}
                  onChange={view.setReply}
                  hint={replyHint(discussion)}
                  disabled={talking}
                  sending={view.sending}
                  onSend={view.sendReply}
                />
              )}
            </SegmentedPanel>
            <SegmentedPanel idBase={idBase} value="raw" active={tab}>
              <DiscussionRaw discussion={discussion} failures={run?.failures ?? new Map()} />
            </SegmentedPanel>
          </section>
          <DiscussionRail
            boardId={boardId}
            discussion={discussion}
            stoppedBy={stoppedBy}
            onControl={control}
            busy={busy}
            onCopyLink={copyLink}
          />
        </div>
      </div>
      <TalkItOutDialog
        key={runs.talkOpen ? "open" : "closed"}
        open={runs.talkOpen}
        rounds={talkRounds(discussion)}
        pending={runs.starting}
        onClose={() => runs.setTalkOpen(false)}
        onStart={runs.talk}
      />
      <ReviewDiscussionDialog
        key={view.reviewing ?? "none"}
        decision={view.reviewing}
        pending={view.reviewPending}
        onClose={() => view.setReviewing(null)}
        onConfirm={view.review}
      />
    </div>
  );
}
