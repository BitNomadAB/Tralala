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

const STATES: Record<TicketState, { word: string; dot: string }> = {
  ready: {
    word: "Ready",
    dot: "bg-[var(--success)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--success)_20%,transparent)]",
  },
  needs_input: {
    word: "Needs input",
    dot: "bg-[var(--warning)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--warning)_20%,transparent)]",
  },
  blocked: {
    word: "Blocked",
    dot: "bg-[var(--destructive)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--destructive)_20%,transparent)]",
  },
};

/**
 * Where a Ticket stands, in words with a coloured dot: Ready, Needs input or Blocked. The dot only
 * repeats the word, so it is hidden from a screen reader; `reason` follows muted ("nothing holds
 * it up").
 */
export function StateChip({
  state,
  reason,
  className,
}: {
  state: TicketState;
  reason?: ReactNode;
  className?: string | undefined;
}) {
  const shown = STATES[state];
  return (
    <span className={cn("inline-flex items-center gap-2 text-sm", className)}>
      <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", shown.dot)} />
      <b className="font-semibold text-[var(--foreground)]">{shown.word}</b>
      {reason === undefined ? null : (
        <span className="text-[var(--muted-foreground)]">· {reason}</span>
      )}
    </span>
  );
}
