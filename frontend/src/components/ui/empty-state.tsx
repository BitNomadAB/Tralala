import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** What a section says while it has nothing to show: one line, and an optional small line. */
export function EmptyState({
  message,
  detail,
  className,
}: {
  message: ReactNode;
  detail?: ReactNode;
  className?: string | undefined;
}) {
  return (
    <div className={cn("grid gap-1", className)}>
      <p className="m-0 text-sm text-[var(--foreground-faint)]">{message}</p>
      {detail === undefined ? null : (
        <p className="m-0 text-xs text-[var(--foreground-faint)]">{detail}</p>
      )}
    </div>
  );
}
