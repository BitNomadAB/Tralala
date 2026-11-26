import { CircleCheck } from "lucide-react";
import { useId } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Chip } from "@/components/ui/chip";
import { Expander } from "@/components/ui/expander";
import { RawText } from "@/components/ui/raw-text";
import type { PocDecision } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { PocAnswer, type PocAnswered } from "./PocAnswer";
import { phaseText, signLines } from "./pocDecisions";
import { pocTicketHref } from "./pocLinks";

const LINK =
  "rounded text-[var(--primary)] hover:underline focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/** The record's text as a small sign: each part under its small label, as plain text. */
function PocSign({ item }: { item: PocDecision }) {
  return (
    <dl className="m-0 grid gap-2.5">
      {signLines(item).map((line) => (
        <div key={line.label} className="grid gap-0.5">
          <dt className="m-0 text-xs font-semibold uppercase tracking-label text-[var(--foreground-faint)]">
            {line.label}
          </dt>
          <dd className="m-0 max-w-[70ch] whitespace-pre-wrap text-[14.5px] leading-snug [overflow-wrap:anywhere]">
            {line.text}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * One POC decision, or one thing missing from a person: its key and title, the Ticket it was taken
 * on as a link that opens the Ticket over this tab, the Phase of that Ticket (marked once the Phase
 * is finished), who wrote it and when; then its sign, the agent's own text behind "Raw text"
 * (shown as written, never as HTML), and the person's answer.
 */
export function PocDecisionItem({
  boardId,
  loopId,
  item,
  canAnswer,
  onAnswered,
}: {
  boardId: string;
  loopId: string;
  item: PocDecision;
  /** A person may answer: the Loop takes writes and the one signed in is a person. */
  canAnswer: boolean;
  onAnswered: PocAnswered;
}) {
  const titleId = useId();
  const phase = phaseText(item);
  return (
    <article
      aria-labelledby={titleId}
      data-poc-id={item.id}
      className="card-surface grid gap-3 px-4 py-3.5"
    >
      <header className="grid gap-1">
        <p className="m-0 flex flex-wrap items-center gap-2">
          <Chip mono>{item.key}</Chip>
          {item.kind === "missing" ? <Badge tone="warning">Missing from a person</Badge> : null}
          {item.due ? <Badge tone="brand">Due for review</Badge> : null}
        </p>
        <h4 id={titleId} className="m-0 text-[15px] font-semibold leading-snug">
          {item.title}
        </h4>
        <p className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted-foreground)]">
          {item.card_id ? (
            <span>
              On{" "}
              <Link className={LINK} to={pocTicketHref(boardId, loopId, item.card_id)}>
                {[item.ticket_key, item.ticket_title ?? "its Ticket"].filter(Boolean).join(" ")}
              </Link>
            </span>
          ) : null}
          {phase ? (
            <span className="inline-flex items-center gap-1">
              {item.phase_complete ? (
                <CircleCheck size={13} aria-hidden="true" className="text-[var(--success)]" />
              ) : null}
              {phase}
            </span>
          ) : null}
          <span>
            By {item.created_by.name} · {formatDateTime(item.created_at)}
          </span>
        </p>
      </header>
      <PocSign item={item} />
      {item.details.trim() ? (
        <Expander title="Raw text">
          <RawText text={item.details} />
        </Expander>
      ) : null}
      <PocAnswer
        boardId={boardId}
        loopId={loopId}
        item={item}
        canAnswer={canAnswer}
        onAnswered={onAnswered}
      />
    </article>
  );
}
