import type { ReactNode } from "react";

const HEADINGS = { 3: "h3", 4: "h4", 5: "h5" } as const;

/**
 * One block of agent text under "Raw text": the small uppercase label, a link beside it
 * (`action`), and the text under it. The label is a heading one level under the section around
 * the blocks: `level` 4 (the default) under an h3, 3 under a page's h2.
 */
export function RawBlock({
  label,
  action,
  level = 4,
  children,
}: {
  label: string;
  action?: ReactNode;
  level?: keyof typeof HEADINGS | undefined;
  children: ReactNode;
}) {
  const Heading = HEADINGS[level];
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <Heading className="m-0 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-[var(--foreground-faint)]">
          {label}
        </Heading>
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
