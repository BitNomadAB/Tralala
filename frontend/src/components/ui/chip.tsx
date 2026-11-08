import type { HTMLAttributes, ReactNode } from "react";
import type { TicketState } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * A small rounded fact inside a line ("PLN-014 done"): `mono` for a key or an id, `trailing` for
 * what follows the text (a mark such as "done").
 */
export function Chip({
  mono = false,
  trailing,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> & {
  mono?: boolean | undefined;
  trailing?: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] px-2 py-0.5 text-[12.5px] text-[var(--foreground)]",
        mono && "font-mono text-xs",
        className,
      )}
      {...props}
    >
      {children}
      {trailing}
    </span>
  );
}

export type MarkTone = "success" | "warning" | "danger";

const DOTS: Record<MarkTone, string> = {
  success:
    "bg-[var(--success)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--success)_20%,transparent)]",
  warning:
    "bg-[var(--warning)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--warning)_20%,transparent)]",
  danger:
    "bg-[var(--destructive)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--destructive)_20%,transparent)]",
};

const STATES: Record<TicketState, { word: string; tone: MarkTone }> = {
  ready: { word: "Ready", tone: "success" },
  needs_input: { word: "Needs input", tone: "warning" },
  blocked: { word: "Blocked", tone: "danger" },
};

/**
 * A word with a coloured dot in front of it (the state line's mark, an analysis verdict): the dot
 * only repeats the word, so it is hidden from a screen reader; `reason` follows muted.
 */
export function ToneMark({
  tone,
  word,
  reason,
  compact = false,
  title,
  className,
}: {
  tone: MarkTone;
  word: ReactNode;
  reason?: ReactNode;
  /** The bordered pill a Kanban card carries in its bottom row. */
  compact?: boolean | undefined;
  /** The longer reason for a pointer ("Waiting for SES-1-PH01-001"). */
  title?: string | undefined;
  className?: string | undefined;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center",
        compact
          ? "gap-1.5 rounded-full border border-[var(--border)] px-1.5 py-px text-xs"
          : "gap-2 text-sm",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn("shrink-0 rounded-full", compact ? "size-1.5" : "size-2", DOTS[tone])}
      />
      <b className="font-semibold text-[var(--foreground)]">{word}</b>
      {reason === undefined ? null : (
        <span className="text-[var(--muted-foreground)]">· {reason}</span>
      )}
    </span>
  );
}

/**
 * Where a Ticket stands, in words with a coloured dot: Ready, Needs input or Blocked. The dot only
 * repeats the word, so it is hidden from a screen reader; `reason` follows muted ("nothing holds
 * it up"). `compact` is the bordered pill a Kanban card carries in its bottom row.
 */
export function StateChip({
  state,
  reason,
  compact = false,
  title,
  className,
}: {
  state: TicketState;
  reason?: ReactNode;
  compact?: boolean | undefined;
  /** The longer reason for a pointer ("Waiting for SES-1-PH01-001"). */
  title?: string | undefined;
  className?: string | undefined;
}) {
  const shown = STATES[state];
  return (
    <ToneMark
      tone={shown.tone}
      word={shown.word}
      reason={reason}
      compact={compact}
      title={title}
      className={className}
    />
  );
}
