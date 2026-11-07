import { useId, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { onTabKeyDown, tabIds } from "./roving";

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
}

/**
 * Two or three views of the same thing as a pill ("For you | Raw text"): a `role="tablist"` with
 * the same keys as Tabs (Left/Right, Home, End move focus and selection). With `idBase` each
 * segment controls the SegmentedPanel of the same value, so a screen reader can follow it.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  idBase,
  className,
}: {
  /** The accessible name of the control ("View"). */
  label: string;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
  /** Pairs each segment with `<SegmentedPanel idBase={…} value={…}>`. */
  idBase?: string | undefined;
  className?: string | undefined;
}) {
  const own = useId();
  const base = idBase ?? own;

  function select(next: string) {
    const option = options.find((candidate) => candidate.value === next);
    if (option && option.value !== value) onChange(option.value);
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn(
        "inline-flex rounded-md border border-[var(--border)] bg-[var(--surface)] p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const ids = tabIds(base, option.value);
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            id={ids.tab}
            data-value={option.value}
            aria-selected={selected}
            aria-controls={idBase === undefined ? undefined : ids.panel}
            tabIndex={selected ? 0 : -1}
            onClick={() => select(option.value)}
            onKeyDown={(event) => onTabKeyDown(event, select)}
            className="cursor-pointer rounded px-2.5 py-1 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] aria-selected:bg-[var(--surface-raised)] aria-selected:text-[var(--foreground)]"
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/** The panel a segment shows: `value` is the segment it belongs to, `active` the selected one. */
export function SegmentedPanel<T extends string>({
  idBase,
  value,
  active,
  children,
  className,
}: {
  idBase: string;
  value: T;
  active: T;
  children: ReactNode;
  className?: string | undefined;
}) {
  const ids = tabIds(idBase, value);
  return (
    <div
      role="tabpanel"
      id={ids.panel}
      aria-labelledby={ids.tab}
      hidden={value !== active}
      className={className}
    >
      {children}
    </div>
  );
}
