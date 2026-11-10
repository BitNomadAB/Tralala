import { useId, useState } from "react";
import { Section } from "@/components/ui/section";
import { Segmented, SegmentedPanel } from "@/components/ui/segmented";
import { renderMarkdown } from "@/lib/markdown";
import type { LoopDocument, LoopDocuments } from "@/lib/types";
import { roadmapGoal } from "./briefs";
import { isBrief } from "./loopUi";
import { PlanDocumentPanel } from "./PlanDocumentPanel";
import { RoadmapPhases } from "./RoadmapPhases";
import { payloadText, planSummary, reviewPlan, ticketCount, ticketsText } from "./roadmapPlan";

type View = "you" | "raw";

const VIEWS = [
  { value: "you", label: "For you" },
  { value: "raw", label: "Raw text" },
] as const;

/** One line of the plan in short, and how many Tickets the plan holds under it. */
function Goal({ text, tickets }: { text: string; tickets: number }) {
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p className="m-0">{text}</p>
      {tickets > 0 ? (
        <p className="m-0 text-[var(--muted-foreground)]">{ticketsText(tickets)}</p>
      ) : null}
    </div>
  );
}

/**
 * The plan in short: the goal the brief gives and the number of Tickets, nothing the Phases under
 * it already say (a brief written before the goal shows its summary); for a RoadMap rendered from
 * its structure the plan's own summary; an earlier view written as text, as it is.
 */
function InShort({
  roadmap,
  technical,
  tickets,
}: {
  roadmap: LoopDocument;
  technical: LoopDocument;
  tickets: number;
}) {
  const goal = isBrief(roadmap) ? roadmapGoal(roadmap.current_payload) : null;
  if (goal !== null) return <Goal text={goal} tickets={tickets} />;
  if (roadmap.current_provenance?.rendered === true && reviewPlan(technical.current_payload)) {
    const summary = planSummary(technical.current_payload);
    return (
      <Goal
        text={summary || "No brief was written for this RoadMap; its Phases follow."}
        tickets={tickets}
      />
    );
  }
  return <div className="prose-sm text-sm">{renderMarkdown(roadmap.current_content ?? "")}</div>;
}

/** The plan as the agent wrote it: the payload as indented JSON, wrapped, never interpreted. */
function RawPlan({ technical }: { technical: LoopDocument }) {
  const shown =
    technical.current_payload === null
      ? (technical.current_content ?? "")
      : payloadText(technical.current_payload);
  return (
    <pre
      aria-label="The plan as JSON"
      className="m-0 max-h-[32rem] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-[var(--border-soft)] bg-[var(--surface)] px-3.5 py-3 font-mono text-[13px] leading-relaxed text-[var(--muted-foreground)] scrollbar-thin"
    >
      {shown}
    </pre>
  );
}

/**
 * The RoadMap a person reviews, the way they read a Ticket: For you is the brief ("In short"), then
 * one Section per Phase with a row per Ticket that expands to its face; Raw text is the technical
 * RoadMap (AI) with the plan as JSON. The approval under it binds to the revisions shown here.
 */
export function RoadmapReview({ documents }: { documents: LoopDocuments["documents"] }) {
  const [view, setView] = useState<View>("you");
  const idBase = useId();
  const roadmap = documents.roadmap;
  const technical = documents.roadmap_ai;
  const phases = reviewPlan(technical.current_payload);
  return (
    <div className="flex flex-col gap-3">
      <Segmented
        label="RoadMap view"
        value={view}
        options={VIEWS}
        onChange={setView}
        idBase={idBase}
        className="self-start"
      />
      <SegmentedPanel idBase={idBase} value="you" active={view}>
        <PlanDocumentPanel
          kind="roadmap"
          document={roadmap}
          technical={technical.current_payload}
          body={
            <div className="grid gap-7">
              <Section title="In short">
                <InShort roadmap={roadmap} technical={technical} tickets={ticketCount(phases)} />
              </Section>
              {phases ? <RoadmapPhases phases={phases} /> : null}
            </div>
          }
        />
      </SegmentedPanel>
      <SegmentedPanel idBase={idBase} value="raw" active={view}>
        {view === "raw" ? (
          <PlanDocumentPanel
            kind="roadmap_ai"
            document={technical}
            body={<RawPlan technical={technical} />}
          />
        ) : null}
      </SegmentedPanel>
    </div>
  );
}
