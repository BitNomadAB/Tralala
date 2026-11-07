import { Badge } from "@/components/ui/badge";
import { renderMarkdown } from "@/lib/markdown";
import type { DiscussionAnswer, DiscussionMessage } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { positionLabel, positionTone } from "./positions";

function Items({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-[11px] font-medium text-[var(--muted-foreground)]">{title}</p>
      <ul className="list-disc pl-4 text-xs">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Byline({ message }: { message: DiscussionMessage }) {
  return (
    <span className="text-[11px] text-[var(--muted-foreground)]">
      <span className="font-medium text-[var(--foreground)]">{message.author_name}</span> ·{" "}
      {message.author_role ?? message.author_type}
      {message.round_number > 0 ? ` · round ${message.round_number}` : ""} ·{" "}
      {formatDateTime(message.created_at)}
    </span>
  );
}

/** A participant's answer at a glance: position, recommendation, the lists; the prose collapsed. */
function StructuredAnswer({
  message,
  answer,
}: {
  message: DiscussionMessage;
  answer: DiscussionAnswer;
}) {
  const proseOnly = answer.format === "prose";
  return (
    <article
      aria-label={`Answer from ${message.author_name}`}
      className="rounded-md border border-[var(--border)] p-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Byline message={message} />
        <span className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
          <Badge tone={positionTone(answer.position)}>{positionLabel(answer.position)}</Badge>
          {answer.confidence ? `${answer.confidence} confidence` : null}
        </span>
      </div>
      {proseOnly ? (
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          Answered in prose only: the answer did not follow the standard form.
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm font-medium">{answer.recommendation}</p>
          <div className="mt-1 grid gap-1.5 sm:grid-cols-2">
            <Items title="For" items={answer.pros} />
            <Items title="Against" items={answer.cons} />
            <Items title="Conditions" items={answer.conditions} />
            <Items title="Open questions" items={answer.open_questions} />
          </div>
        </>
      )}
      <details className="mt-1" open={proseOnly}>
        <summary className="cursor-pointer text-[11px] text-[var(--brand)]">Full answer</summary>
        <div className="mt-1 text-sm">{renderMarkdown(message.content)}</div>
      </details>
    </article>
  );
}

/** One message of the thread: a person's text, or a participant's answer as a card. */
export function MessageItem({ message }: { message: DiscussionMessage }) {
  if (message.answer) return <StructuredAnswer message={message} answer={message.answer} />;
  return (
    <div>
      <Byline message={message} />
      <div className="mt-0.5 text-sm">{renderMarkdown(message.content)}</div>
    </div>
  );
}
