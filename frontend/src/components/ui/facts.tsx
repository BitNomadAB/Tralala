import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A list of facts about one thing (a Ticket's Details), one row per Fact. */
export function Facts({
  children,
  className,
}: {
  children: ReactNode;
  className?: string | undefined;
}) {
  return (
    <dl className={cn("m-0 grid border-t border-[var(--border-soft)]", className)}>{children}</dl>
  );
}

/** One fact: its `label` on the left, the value on the right, or a muted "None" with `none`. */
export function Fact({
  label,
  none = false,
  children,
  className,
}: {
  label: ReactNode;
  none?: boolean | undefined;
  children?: ReactNode;
  className?: string | undefined;
}) {
  return (
    <div
      className={cn(
        "grid min-h-10 grid-cols-[96px_minmax(0,1fr)] items-center gap-3 border-b border-[var(--border-soft)] py-[9px] text-[14px]",
        className,
      )}
    >
      <dt className="m-0 text-[13px] text-[var(--muted-foreground)]">{label}</dt>
      <dd
        className={cn(
          "m-0 flex min-w-0 flex-wrap items-center gap-2",
          none && "text-[var(--foreground-faint)]",
        )}
      >
        {none ? "None" : children}
      </dd>
    </div>
  );
}
