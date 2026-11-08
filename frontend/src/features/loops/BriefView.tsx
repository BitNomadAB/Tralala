import { useId, useState, type ReactNode } from "react";
import { Segmented, SegmentedPanel } from "@/components/ui/segmented";
import type { HumanBrief, RoadmapBrief } from "@/lib/types";
import { AnalysisRaw } from "./AnalysisRaw";
import { AnalysisSign } from "./AnalysisSign";
import type { BriefApproval } from "./briefApproval";
import { BriefApprove } from "./BriefApprove";
import { findingTitles, orderedSteps, phaseSources, planTitles, sourcesOf } from "./briefs";

/** Where an item of the brief comes from: the findings, Phases or Tickets it rests on, by title. */
function Sources({ titles }: { titles: string[] }) {
  if (titles.length === 0) return null;
  return (
    <details className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
      <summary className="cursor-pointer">Where does this come from?</summary>
      <ul className="mt-1 list-disc pl-4">
        {titles.map((title, index) => (
          <li key={`${index}-${title}`}>{title}</li>
        ))}
      </ul>
    </details>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1">
      <h4 className="text-xs font-semibold text-[var(--foreground)]">{title}</h4>
      {children}
    </section>
  );
}

function Item({ label, text, sources }: { label?: string; text: string; sources: string[] }) {
  return (
    <li>
      {label ? <span className="font-medium">{label}: </span> : null}
      {text}
      <Sources titles={sources} />
    </li>
  );
}

function Points({ children }: { children: ReactNode }) {
  return <ul className="flex list-disc flex-col gap-1 pl-4">{children}</ul>;
}

type View = "you" | "raw";

const VIEWS = [
  { value: "you", label: "For you" },
  { value: "raw", label: "Raw text" },
] as const;

/**
 * The analysis brief for the person who decides: For you is the sign (`AnalysisSign`), Raw text the
 * findings and the technical analysis as they were written. With `approval` the brief ends with
 * "Approve analysis" and the revision it approves, under either view. The choice of view lasts
 * while the brief is shown.
 */
export function AnalysisBriefView({
  brief,
  technical,
  approval,
}: {
  brief: HumanBrief;
  technical: unknown;
  approval?: BriefApproval | undefined;
}) {
  const idBase = useId();
  const [view, setView] = useState<View>("you");
  return (
    <div className="grid gap-4 text-sm">
      <div className="flex justify-end">
        <Segmented
          label="Brief view"
          value={view}
          options={VIEWS}
          onChange={setView}
          idBase={idBase}
        />
      </div>
      <SegmentedPanel idBase={idBase} value="you" active={view}>
        <AnalysisSign brief={brief} titles={findingTitles(technical)} />
      </SegmentedPanel>
      <SegmentedPanel idBase={idBase} value="raw" active={view}>
        <AnalysisRaw technical={technical} />
      </SegmentedPanel>
      {approval ? <BriefApprove approval={approval} /> : null}
    </div>
  );
}

/** The RoadMap brief for the person who approves it: the order of work, their part, the risks. */
export function RoadmapBriefView({
  brief,
  technical,
}: {
  brief: RoadmapBrief;
  technical: unknown;
}) {
  const plan = planTitles(technical);
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>{brief.summary}</p>
      <Section title="The order of work">
        <ol className="flex flex-col gap-2">
          {orderedSteps(brief, plan).map((step) => (
            <li key={step.phase_id}>
              <span className="font-medium">
                {plan.phases.get(step.phase_id)?.title ?? "A Phase"}
              </span>
              <p>{step.what_happens}</p>
              <p className="text-[var(--muted-foreground)]">Done when: {step.done_when}</p>
            </li>
          ))}
        </ol>
      </Section>
      {brief.your_part.length > 0 ? (
        <Section title="Your part">
          <Points>
            {brief.your_part.map((part, index) => (
              <Item
                key={index}
                text={part.text}
                sources={[
                  ...phaseSources(part.phase_ids, plan),
                  ...sourcesOf(part.ticket_ids, plan.tickets),
                ]}
              />
            ))}
          </Points>
        </Section>
      ) : null}
      {brief.could_block.length > 0 ? (
        <Section title="What could block it">
          <Points>
            {brief.could_block.map((risk, index) => (
              <Item key={index} text={risk.text} sources={phaseSources(risk.phase_ids, plan)} />
            ))}
          </Points>
        </Section>
      ) : null}
    </div>
  );
}
