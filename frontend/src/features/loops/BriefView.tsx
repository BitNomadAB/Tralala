import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import type { HumanBrief, RoadmapBrief } from "@/lib/types";
import {
  findingTitles,
  LEVEL_TEXT,
  orderedSteps,
  phaseSources,
  planTitles,
  sourcesOf,
  VERDICT_TEXT,
  VERDICT_TONE,
} from "./briefs";

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

/** The analysis brief for the person who decides: the verdict first, then the reasons. */
export function AnalysisBriefView({ brief, technical }: { brief: HumanBrief; technical: unknown }) {
  const titles = findingTitles(technical);
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>
        <span className="font-semibold">Can it be done? </span>
        <Badge tone={VERDICT_TONE[brief.verdict]}>{VERDICT_TEXT[brief.verdict]}</Badge>{" "}
        {brief.verdict_reason}
      </p>
      <p>{brief.summary}</p>
      <Section title="What stands in the way">
        {brief.obstacles.length > 0 ? (
          <Points>
            {brief.obstacles.map((obstacle, index) => (
              <Item
                key={index}
                label={LEVEL_TEXT[obstacle.level]}
                text={obstacle.text}
                sources={sourcesOf(obstacle.finding_ids, titles)}
              />
            ))}
          </Points>
        ) : (
          <p className="text-[var(--muted-foreground)]">
            Nothing was found that stands in the way.
          </p>
        )}
      </Section>
      {(
        [
          ["For", brief.pros],
          ["Against", brief.cons],
        ] as const
      ).map(([title, points]) =>
        points.length > 0 ? (
          <Section key={title} title={title}>
            <Points>
              {points.map((point, index) => (
                <Item
                  key={index}
                  text={point.text}
                  sources={sourcesOf(point.finding_ids, titles)}
                />
              ))}
            </Points>
          </Section>
        ) : null,
      )}
      {brief.decisions.length > 0 ? (
        <Section title="What you need to decide">
          <Points>
            {brief.decisions.map((decision, index) => (
              <Item
                key={index}
                text={decision.question}
                sources={sourcesOf(decision.finding_ids, titles)}
              />
            ))}
          </Points>
        </Section>
      ) : null}
      <Section title="Recommendation">
        <p>{brief.recommendation}</p>
      </Section>
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
