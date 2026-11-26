import { useEffect, useId, useRef, useState, type ReactElement } from "react";
import { SectionHeader } from "@/components/ui/section";
import { Segmented, SegmentedPanel } from "@/components/ui/segmented";
import { ConfirmDialog } from "@/features/settings/ConfirmDialog";
import { describeError } from "@/lib/describeError";
import type { Discussion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CLOSE_QUESTION } from "./closingRules";
import { DiscussionActions } from "./DiscussionActions";
import { DiscussionForYou } from "./DiscussionForYou";
import { DiscussionHead } from "./DiscussionHead";
import { DiscussionRail } from "./DiscussionRail";
import { DiscussionRaw } from "./DiscussionRaw";
import {
  isTalking,
  outcomeLine,
  progressLine,
  stateOf,
  talkRounds,
  type RunAction,
} from "./discussionRules";
import { DiscussionSign } from "./DiscussionSign";
import { ReviewDiscussionDialog } from "./ReviewDiscussionDialog";
import { TalkItOutDialog } from "./TalkItOutDialog";
import { useDiscussionLinks } from "./useDiscussionLinks";
import { useDiscussionNotices } from "./useDiscussionNotices";
import { useDiscussionView, type DiscussionViewState } from "./useDiscussionView";
import { useFocusRescue } from "./useFocusRescue";

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
 * text: everything the agents wrote) beside the rail with the status and the facts. A screen
 * reader hears what changes as the agents answer (`useDiscussionNotices`); an action that takes
 * away its own control gives focus to the heading (`useFocusRescue`). With `focusOnOpen` the
 * heading takes focus once the thread is shown, for a host that swaps the view in under the
 * keyboard (the Ticket's dialog).
 */
export function DiscussionView({
  boardId,
  discussionId,
  loopId,
  host,
  onBack,
  onClose,
  titleWrap,
  focusOnOpen = false,
}: {
  boardId: string;
  discussionId: string;
  /** The Loop the host shows, for a thread whose Ticket the API could not place. */
  loopId?: string | undefined;
  host: DiscussionHost;
  /** Back to the Ticket in the dialog; elsewhere it navigates to the Ticket or the board. */
  onBack?: ((cardId: string) => void) | undefined;
  onClose?: (() => void) | undefined;
  titleWrap?: ((heading: ReactElement) => ReactElement) | undefined;
  focusOnOpen?: boolean | undefined;
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
    // On the page this is what the page shows, so it is the page's h1.
    const Heading = host === "page" ? "h1" : "h2";
    return (
      <div className="p-7">
        {wrap(<Heading className="sr-only">Discussion</Heading>)}
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
      focusOnOpen={focusOnOpen}
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
  focusOnOpen,
}: {
  boardId: string;
  loopId: string | null;
  discussion: Discussion;
  view: DiscussionViewState;
  host: DiscussionHost;
  onBack: ((cardId: string) => void) | undefined;
  onClose: (() => void) | undefined;
  titleWrap: ((heading: ReactElement) => ReactElement) | undefined;
  focusOnOpen: boolean;
}) {
  const idBase = useId();
  const headingId = useId();
  const [tab, setTab] = useState<View>("you");
  const root = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useFocusRescue(root, heading);
  useDiscussionNotices(discussion, view.run, view.eventsReady);
  useEffect(() => {
    if (focusOnOpen) heading.current?.focus();
  }, [focusOnOpen]);
  const modal = host === "modal";
  // The sections under the question: h2 under the page's h1, h3 under the dialog's h2.
  const level = host === "page" ? 2 : 3;
  const links = useDiscussionLinks({ boardId, loopId, discussion, host, onBack });

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
    <div ref={root} className={cn(modal && "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]")}>
      <DiscussionHead
        discussion={discussion}
        level={host === "page" ? 1 : 2}
        headingRef={heading}
        titleWrap={titleWrap}
        page={host === "page"}
        onBack={links.back}
        onOpenPage={host !== "page" ? links.openPage : undefined}
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
          onCopyLink={links.copyLink}
          closing={view.closing}
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
              level={level}
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
              <DiscussionForYou
                boardId={boardId}
                discussion={discussion}
                view={view}
                level={level === 2 ? 3 : 4}
              />
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
            onCopyLink={links.copyLink}
            level={level}
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
      <ConfirmDialog
        question={view.closing.asking ? CLOSE_QUESTION : null}
        onConfirm={view.closing.confirm}
        onCancel={view.closing.cancel}
      />
    </div>
  );
}
