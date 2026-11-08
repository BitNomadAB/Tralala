import { Link } from "react-router-dom";
import { ToneMark, type MarkTone } from "@/components/ui/chip";

/** One discussion as a row shows it, in words the caller has already chosen. */
export interface DiscussionRowItem {
  id: string;
  /** The verdict, or the state while the agents talk, as a word with its mark. */
  mark: { word: string; tone: MarkTone };
  question: string;
  /** The text on the right: when, or the decision and who took it. */
  aside: string;
  /** The faint line under the question: where it belongs, the agents, the sides, the round. */
  meta: string;
}

/**
 * Discussions as rows of links: the mark and the question, the text on the right and the meta
 * line under them. It knows no page: the caller gives the words and `hrefFor`, so the inbox and a
 * Ticket's Discussions tab show the same rows.
 */
export function DiscussionRows<Row extends DiscussionRowItem>({
  rows,
  label,
  hrefFor,
}: {
  rows: readonly Row[];
  /** The list's accessible name. */
  label: string;
  hrefFor: (row: Row) => string;
}) {
  return (
    <ul aria-label={label} className="m-0 list-none border-t border-[var(--border-soft)] p-0">
      {rows.map((row) => (
        <li key={row.id} className="border-b border-[var(--border-soft)]">
          <Link
            to={hrefFor(row)}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 rounded-md px-1 py-3 text-inherit no-underline hover:bg-[var(--surface-raised)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
          >
            <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[15px] font-medium text-[var(--foreground)]">
              <ToneMark compact tone={row.mark.tone} word={row.mark.word} />
              <span className="min-w-0">{row.question}</span>
            </span>
            <span className="whitespace-nowrap text-[12.5px] text-[var(--foreground-faint)]">
              {row.aside}
            </span>
            <span className="col-span-full text-[12.5px] text-[var(--foreground-faint)]">
              {row.meta}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
