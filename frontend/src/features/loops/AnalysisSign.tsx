import { Chip, ToneMark } from "@/components/ui/chip";
import { Section } from "@/components/ui/section";
import type { BriefDecision, BriefPoint, HumanBrief } from "@/lib/types";
import { LEVEL_TEXT, SIZE_TEXT, VERDICT_MARK, VERDICT_TEXT } from "./briefs";

const GONE = "No longer in the technical version";

/** A short list with a mark in front of each item, as the Ticket's Pro and con shows it. */
function MarkedList({
  label,
  items,
  mark,
  tone,
}: {
  label: string;
  items: readonly { text: string; detail?: string | undefined }[];
  mark: string;
  tone: string;
}) {
  return (
    <ul aria-label={label} className="m-0 grid list-none content-start gap-[7px] p-0 text-[14.5px]">
      {items.map((item, index) => (
        <li key={index} className="grid grid-cols-[16px_minmax(0,1fr)] items-baseline gap-2">
          <span aria-hidden="true" className={`text-[13px] font-bold ${tone}`}>
            {mark}
          </span>
          <span>
            {item.text}
            {item.detail ? (
              <span className="ml-1.5 text-[12.5px] text-[var(--foreground-faint)]">
                {item.detail}
              </span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Nothing({ children }: { children: string }) {
  return <p className="m-0 text-[13px] text-[var(--foreground-faint)]">{children}</p>;
}

/** One question to the person, with the findings it rests on as chips (their ids on hover). */
function Decision({
  decision,
  titles,
}: {
  decision: BriefDecision;
  titles: ReadonlyMap<string, string>;
}) {
  return (
    <li className="grid gap-1.5 border-b border-[var(--border-soft)] pb-3 last:border-b-0 last:pb-0">
      <p className="m-0 text-[15px] font-medium leading-snug">{decision.question}</p>
      {decision.finding_ids.length > 0 ? (
        <ul aria-label="Rests on" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {decision.finding_ids.map((id) => (
            <li key={id}>
              <Chip title={id} className="text-xs text-[var(--muted-foreground)]">
                {titles.get(id) ?? GONE}
              </Chip>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function points(items: readonly BriefPoint[]) {
  return items.map((point) => ({ text: point.text }));
}

/**
 * The analysis brief as a sign, in the order a person decides: In short (the verdict as a mark and
 * its one line), Why (the reasons), What you decide (each question, with the findings it rests on),
 * How big, and For and against. A brief written before the sign has no line and no size; those
 * parts are left out. Nothing of the findings' text is shown here: it is in Raw text.
 */
export function AnalysisSign({
  brief,
  titles,
}: {
  brief: HumanBrief;
  titles: ReadonlyMap<string, string>;
}) {
  const line = brief.verdict_line?.trim();
  const size = brief.size;
  return (
    <div className="grid gap-[22px]">
      <Section title="In short">
        <div className="grid gap-1.5">
          <ToneMark tone={VERDICT_MARK[brief.verdict]} word={VERDICT_TEXT[brief.verdict]} />
          {line ? (
            <p className="m-0 max-w-[60ch] text-[19px] font-medium leading-[1.45]">{line}</p>
          ) : null}
        </div>
      </Section>
      <Section title="Why">
        {brief.obstacles.length > 0 ? (
          <MarkedList
            label="Why"
            items={brief.obstacles.map((obstacle) => ({
              text: obstacle.text,
              detail: LEVEL_TEXT[obstacle.level],
            }))}
            mark="!"
            tone="text-[var(--warning)]"
          />
        ) : (
          <Nothing>Nothing was found that stands in the way.</Nothing>
        )}
      </Section>
      <Section title="What you decide">
        {brief.decisions.length > 0 ? (
          <ol className="m-0 grid list-none gap-3 p-0">
            {brief.decisions.map((decision, index) => (
              <Decision key={index} decision={decision} titles={titles} />
            ))}
          </ol>
        ) : (
          <Nothing>Nothing for you to decide.</Nothing>
        )}
      </Section>
      {size ? (
        <Section title="How big">
          <p className="m-0 max-w-[60ch] text-[14.5px]">
            <b className="font-semibold">{SIZE_TEXT[size.kind]}.</b> {size.text}
          </p>
        </Section>
      ) : null}
      <Section title="For and against">
        <div className="grid grid-cols-1 gap-7 sm:grid-cols-2">
          {brief.pros.length > 0 ? (
            <MarkedList
              label="For"
              items={points(brief.pros)}
              mark="+"
              tone="text-[var(--success)]"
            />
          ) : (
            <Nothing>Nothing for.</Nothing>
          )}
          {brief.cons.length > 0 ? (
            <MarkedList
              label="Against"
              items={points(brief.cons)}
              mark="–"
              tone="text-[var(--warning)]"
            />
          ) : (
            <Nothing>Nothing against.</Nothing>
          )}
        </div>
      </Section>
    </div>
  );
}
