import { useId, useState } from "react";
import { Avatar } from "@/components/ui/avatar";
import { ToneMark } from "@/components/ui/chip";
import type { DiscussionAnswer } from "@/lib/types";
import type { StanceRow } from "./discussionData";
import { confidenceText, failedLine, positionLabel, positionTone } from "./discussionRules";

const TOGGLE =
  "rounded border-0 bg-transparent p-0 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/** The level of the headings For, Against, Conditions and Open questions: under "Who stands where". */
export type PointLevel = 3 | 4;

/** One of the four lists of an answer, each item with its mark, or a faint "None.". */
function Points({
  label,
  items,
  mark,
  tone,
  level,
}: {
  label: string;
  items: readonly string[];
  mark: string;
  tone: string;
  level: PointLevel;
}) {
  const Heading = level === 3 ? "h3" : "h4";
  return (
    <div className="grid content-start gap-1.5">
      <Heading className="m-0 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-[var(--foreground-faint)]">
        {label}
      </Heading>
      {items.length === 0 ? (
        <p className="m-0 text-[13px] text-[var(--foreground-faint)]">None.</p>
      ) : (
        <ul aria-label={label} className="m-0 grid list-none gap-[7px] p-0 text-[14px]">
          {items.map((item, index) => (
            <li key={index} className="grid grid-cols-[14px_minmax(0,1fr)] items-baseline gap-2">
              <span aria-hidden="true" className={`text-[13px] font-bold ${tone}`}>
                {mark}
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** For, Against, Conditions and Open questions of one answer, in two columns. */
function AnswerDetails({
  id,
  answer,
  open,
  level,
}: {
  id: string;
  answer: DiscussionAnswer;
  open: boolean;
  level: PointLevel;
}) {
  return (
    <div
      id={id}
      hidden={!open}
      className="mt-3 grid grid-cols-1 gap-x-7 gap-y-4 border-t border-[var(--border-soft)] pt-3 sm:grid-cols-2"
    >
      <Points label="For" items={answer.pros} mark="+" tone="text-[var(--success)]" level={level} />
      <Points
        label="Against"
        items={answer.cons}
        mark="–"
        tone="text-[var(--warning)]"
        level={level}
      />
      <Points
        label="Conditions"
        items={answer.conditions}
        mark="·"
        tone="text-[var(--muted-foreground)]"
        level={level}
      />
      <Points
        label="Open questions"
        items={answer.open_questions}
        mark="?"
        tone="text-[var(--muted-foreground)]"
        level={level}
      />
    </div>
  );
}

function Stance({ row, failed, level }: { row: StanceRow; failed: boolean; level: PointLevel }) {
  const detailsId = useId();
  const [open, setOpen] = useState(false);
  const { stance, answer } = row;
  const confidence = stance ? confidenceText(stance.confidence) : null;
  return (
    <li
      aria-label={row.name}
      className="border-b border-[var(--border-soft)] py-3.5 first:pt-0 last:border-b-0"
    >
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3">
        <Avatar name={row.name} />
        <div className="grid min-w-0 gap-1">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <span className="text-[14.5px] font-semibold">{row.name}</span>
            {row.role ? (
              <span className="text-[13px] text-[var(--muted-foreground)]">{row.role}</span>
            ) : null}
            {stance ? (
              <ToneMark
                compact
                tone={positionTone(stance.position)}
                word={positionLabel(stance.position)}
              />
            ) : null}
          </div>
          {row.kind === "answer" && stance ? (
            <p className="m-0 max-w-[62ch] text-[15px] leading-normal">{stance.recommendation}</p>
          ) : (
            <p className="m-0 text-[14px] text-[var(--foreground-faint)]">
              {row.kind === "prose" ? "Answered in prose only" : "No answer yet"}
            </p>
          )}
          {confidence || (row.kind === "answer" && answer) ? (
            <div className="flex flex-wrap items-center gap-3 text-[13px] text-[var(--foreground-faint)]">
              {confidence ? <span>{confidence}</span> : null}
              {row.kind === "answer" && answer ? (
                <button
                  type="button"
                  className={TOGGLE}
                  aria-expanded={open}
                  aria-controls={detailsId}
                  aria-label={`${open ? "Hide details" : "Details"} from ${row.name}`}
                  onClick={() => setOpen(!open)}
                >
                  {open ? "Hide details" : "Details"}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {failed ? (
        <p className="m-0 mt-2 pl-11 text-[13.5px] text-[var(--destructive)]">
          {failedLine(row.name)}
        </p>
      ) : null}
      {row.kind === "answer" && answer ? (
        <AnswerDetails id={detailsId} answer={answer} open={open} level={level} />
      ) : null}
    </li>
  );
}

/**
 * Who stands where: one row per agent with its position, its one recommendation and its
 * confidence; Details opens what it said for and against, its conditions and its open questions.
 * An agent with no answer, or with an answer outside the standard, says so; its prose is in Raw
 * text. An agent the latest round could not reach (`failed`, by agent id) says so under its row.
 */
export function StanceRows({
  rows,
  failed,
  level,
}: {
  rows: readonly StanceRow[];
  failed: ReadonlyMap<string, string>;
  level: PointLevel;
}) {
  if (rows.length === 0) {
    return (
      <p className="m-0 text-sm text-[var(--foreground-faint)]">No agents in this discussion.</p>
    );
  }
  return (
    <ul aria-label="Answers" className="m-0 grid list-none p-0">
      {rows.map((row) => (
        <Stance key={row.id} row={row} failed={failed.has(row.participantId)} level={level} />
      ))}
    </ul>
  );
}
