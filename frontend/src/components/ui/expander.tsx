import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A section that opens on request, on the platform's `<details>`: the title (and a muted `hint`
 * after it, "3 for, 3 against") is the button, the chevron turns when open. Pass `open` and
 * `onToggle` to control it; without `open` the browser keeps the state, `defaultOpen` sets where
 * it starts.
 */
export function Expander({
  title,
  hint,
  open,
  defaultOpen,
  onToggle,
  children,
  className,
}: {
  title: ReactNode;
  hint?: ReactNode;
  open?: boolean | undefined;
  defaultOpen?: boolean | undefined;
  onToggle?: ((open: boolean) => void) | undefined;
  children: ReactNode;
  className?: string | undefined;
}) {
  return (
    <details
      open={open ?? defaultOpen}
      onToggle={(event) => onToggle?.(event.currentTarget.open)}
      className={cn(
        "group rounded-lg border border-[var(--border)] bg-[var(--surface)]",
        className,
      )}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2.5 rounded-lg px-3.5 py-3 text-[14.5px] font-semibold text-[var(--foreground)] hover:bg-[var(--surface-raised)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] group-open:rounded-b-none group-open:border-b group-open:border-[var(--border-soft)] [&::-webkit-details-marker]:hidden">
        {title}
        {hint === undefined ? null : (
          <span className="text-[13px] font-normal text-[var(--foreground-faint)]">{hint}</span>
        )}
        <ChevronRight
          size={14}
          aria-hidden="true"
          className="ml-auto shrink-0 text-[var(--foreground-faint)] transition-transform duration-150 group-open:rotate-90 motion-reduce:transition-none"
        />
      </summary>
      <div className="grid gap-3.5 px-3.5 pb-4 pt-3.5">{children}</div>
    </details>
  );
}
