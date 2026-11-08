import { stepsFoot } from "./ticketText";

/**
 * The face's steps, what will be done, as a numbered list with ruled rows and a foot line. Read
 * only: the Ticket view and the RoadMap review show it the same way.
 */
export function TicketFace({ steps }: { steps: readonly string[] }) {
  if (steps.length === 0) return null;
  return (
    <div>
      <ol
        aria-label="Steps"
        className="m-0 max-w-[70ch] list-none border-t border-[var(--border-soft)] p-0"
      >
        {steps.map((step, index) => (
          <li
            // A step's text may repeat; its place in the list is what it is.
            key={index}
            className="grid grid-cols-[22px_minmax(0,1fr)] items-baseline gap-3 border-b border-[var(--border-soft)] py-[11px] text-base leading-[1.45]"
          >
            <span className="text-right font-mono text-xs font-medium tabular-nums text-[var(--foreground-faint)]">
              {index + 1}
            </span>
            <span>{step}</span>
          </li>
        ))}
      </ol>
      <p className="m-0 mt-2 text-[13px] text-[var(--foreground-faint)]">
        {stepsFoot(steps.length)}
      </p>
    </div>
  );
}
