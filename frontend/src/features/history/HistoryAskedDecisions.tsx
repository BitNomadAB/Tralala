import { askedDecisions } from "./askedThrough";

/** The decisions of a completed Loop that answered a coding session's question (`askedDecisions`). */
export function HistoryAskedDecisions({ envelope }: { envelope: Record<string, unknown> }) {
  const lines = askedDecisions(envelope);
  if (lines.length === 0) return null;
  return (
    <section className="flex flex-col gap-1">
      <h2 className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        Decisions asked from a coding session
      </h2>
      <ul aria-label="Decisions asked from a coding session" className="text-sm">
        {lines.map((line, index) => (
          <li key={`${index}-${line}`}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
