import type { ReactNode } from "react";

/**
 * One block of agent text under "Raw text": the small uppercase label, a link beside it
 * (`action`), and the text under it.
 */
export function RawBlock({
  label,
  action,
  children,
}: {
  label: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <h4 className="m-0 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-[var(--foreground-faint)]">
          {label}
        </h4>
        {action}
      </div>
      {children}
    </div>
  );
}

/** Text as it was written, monospaced and unstyled on purpose; long lines wrap. */
export function RawText({ text }: { text: string }) {
  return (
    <pre className="m-0 whitespace-pre-wrap rounded-md border border-[var(--border-soft)] bg-[var(--surface)] px-3.5 py-3 font-mono text-[13px] leading-[1.6] [overflow-wrap:anywhere] text-[var(--muted-foreground)]">
      {text}
    </pre>
  );
}
