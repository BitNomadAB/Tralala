import { useId, useState, type RefObject } from "react";
import { SectionHeader } from "@/components/ui/section";
import { Segmented, SegmentedPanel } from "@/components/ui/segmented";
import { renderMarkdown, type MarkdownOptions } from "@/lib/markdown";
import type { ActivityEntry, BoardPerson, CardDetail, LoopReadiness } from "@/lib/types";
import { TicketActivity, type ActivityTab } from "./TicketActivity";
import { TicketExpanders } from "./TicketExpanders";
import { TicketFace } from "./TicketFace";
import { TicketFaceEdit } from "./TicketFaceEdit";
import { TicketFiles } from "./TicketFiles";
import { TicketNotes } from "./TicketNotes";
import { TicketRaw } from "./TicketRaw";
import type { useCardComments } from "./useCardComments";
import { useFaceEdit } from "./useFaceEdit";
import type { TicketDiscussions } from "./useTicketDiscussions";

type View = "you" | "raw";

const VIEWS = [
  { value: "you", label: "For you" },
  { value: "raw", label: "Raw text" },
] as const;

const LINK =
  "rounded border-0 bg-transparent p-0 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/**
 * The Ticket's main column, the owner's template: "What will be done" with For you (the steps,
 * then Why it is needed, If we skip it, Pro and con and Your notes as sections that expand) and
 * Raw text (everything the agent wrote, as it is); then Files and Activity. A Ticket without a
 * face shows its description in For you. The choice of view lasts while the view is open.
 */
export function TicketBody({
  boardId,
  loopId,
  card,
  readOnly,
  readOnlyReason,
  actorId,
  live,
  comments,
  history,
  discussions,
  discussionHref,
  onAsk,
  readiness,
  people,
  ticketHref,
  picker,
  activityTab,
  onActivityTabChange,
  onSaveDescription,
  refresh,
}: {
  boardId: string;
  loopId: string;
  card: CardDetail;
  readOnly: boolean;
  /** Why a person cannot write here, shown in place of the notes' composer. */
  readOnlyReason: string;
  actorId: string | undefined;
  live: boolean;
  comments: ReturnType<typeof useCardComments>;
  history: ActivityEntry[];
  discussions: TicketDiscussions;
  discussionHref: (discussionId: string) => string;
  /** Opens "Ask the agents"; absent on a read-only Ticket. */
  onAsk: (() => void) | undefined;
  readiness: LoopReadiness | undefined;
  people: readonly BoardPerson[];
  ticketHref?: MarkdownOptions["ticketHref"];
  /** The hidden file input, which the head's Add file opens. */
  picker: RefObject<HTMLInputElement | null>;
  activityTab: ActivityTab;
  onActivityTabChange: (tab: ActivityTab) => void;
  onSaveDescription: (description: string) => Promise<boolean>;
  refresh: () => void;
}) {
  const idBase = useId();
  const headingId = useId();
  const [view, setView] = useState<View>("you");
  const edit = useFaceEdit({ boardId, loopId, card, refresh });
  const face = card.face;
  const names = new Map(people.map((person) => [person.id, person.name]));

  return (
    <div className="grid min-w-0 content-start gap-[30px]">
      <section aria-labelledby={headingId}>
        <SectionHeader
          id={headingId}
          size="lg"
          title="What will be done"
          trailing={
            <div className="flex items-center gap-3">
              {view === "you" && !readOnly && !edit.editing ? (
                <button
                  type="button"
                  className={LINK}
                  aria-label="Edit what will be done"
                  onClick={edit.open}
                >
                  Edit
                </button>
              ) : null}
              <Segmented
                label="View"
                value={view}
                options={VIEWS}
                onChange={setView}
                idBase={idBase}
              />
            </div>
          }
        />
        <SegmentedPanel idBase={idBase} value="you" active={view} className="grid gap-[22px]">
          {edit.draft && edit.counts ? (
            <TicketFaceEdit
              draft={edit.draft}
              counts={edit.counts}
              errors={edit.errors}
              saving={edit.saving}
              onChange={edit.change}
              onSave={edit.save}
              onCancel={edit.cancel}
            />
          ) : face ? (
            <TicketFace steps={face.steps} />
          ) : (
            <div className="grid gap-2">
              {card.description ? (
                <div className="max-w-[70ch] text-[15px] leading-relaxed">
                  {renderMarkdown(card.description, { ticketHref })}
                </div>
              ) : null}
              <p className="m-0 text-[13px] text-[var(--foreground-faint)]">
                Written before Tickets had a plain summary.
              </p>
            </div>
          )}
          <TicketExpanders face={edit.editing ? null : face}>
            <TicketNotes
              boardId={boardId}
              loopId={loopId}
              cardId={card.id}
              actorId={actorId}
              readOnly={readOnly}
              readOnlyText={readOnlyReason}
              openByDefault={face === null}
              onChanged={refresh}
            />
          </TicketExpanders>
        </SegmentedPanel>
        <SegmentedPanel idBase={idBase} value="raw" active={view}>
          <TicketRaw
            card={card}
            readiness={readiness}
            readOnly={readOnly}
            onSaveDescription={onSaveDescription}
            ticketHref={ticketHref}
          />
        </SegmentedPanel>
      </section>
      <TicketFiles
        boardId={boardId}
        cardId={card.id}
        readOnly={readOnly}
        currentActorId={actorId}
        onChanged={refresh}
        picker={picker}
      />
      <TicketActivity
        card={card}
        live={live}
        comments={comments}
        history={history}
        nameOf={(id) => names.get(id) ?? null}
        discussions={discussions}
        discussionHref={discussionHref}
        onAsk={onAsk}
        tab={activityTab}
        onTabChange={onActivityTabChange}
        ticketHref={ticketHref}
      />
    </div>
  );
}
