import { createContext, useContext, useId, useMemo, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { onTabKeyDown, tabIds } from "./roving";

interface TabsState {
  value: string;
  onChange: (value: string) => void;
  base: string;
}

const TabsContext = createContext<TabsState | null>(null);

function useTabs(part: string): TabsState {
  const state = useContext(TabsContext);
  if (!state) throw new Error(`${part} must be rendered inside <Tabs>`);
  return state;
}

/**
 * A set of tabs with their panels, controlled by `value` and `onChange`. The tabs are a
 * `role="tablist"` with a roving tab index: one Tab stop for the list, Left/Right, Home and End
 * move the focus and the selection together, and only the selected panel is shown.
 */
export function Tabs({
  value,
  onChange,
  children,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  className?: string | undefined;
}) {
  const base = useId();
  const state = useMemo(() => ({ value, onChange, base }), [value, onChange, base]);
  return (
    <TabsContext.Provider value={state}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

/** The row of tabs, underlined; `label` names it for a screen reader ("Activity"). */
export function TabList({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string | undefined;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn("mb-3.5 flex gap-0.5 border-b border-[var(--border-soft)]", className)}
    >
      {children}
    </div>
  );
}

/** One tab; selected when its `value` is the Tabs' value. */
export function Tab({
  value,
  children,
  disabled,
  className,
}: {
  value: string;
  children: ReactNode;
  disabled?: boolean | undefined;
  className?: string | undefined;
}) {
  const tabs = useTabs("Tab");
  const ids = tabIds(tabs.base, value);
  const selected = tabs.value === value;
  return (
    <button
      type="button"
      role="tab"
      id={ids.tab}
      data-value={value}
      aria-selected={selected}
      aria-controls={ids.panel}
      tabIndex={selected ? 0 : -1}
      disabled={disabled}
      onClick={() => {
        if (!selected) tabs.onChange(value);
      }}
      onKeyDown={(event) => onTabKeyDown(event, tabs.onChange)}
      className={cn(
        "-mb-px cursor-pointer border-b-2 border-transparent bg-transparent px-3 py-2 text-sm font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:cursor-default disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] aria-selected:border-[var(--primary)] aria-selected:text-[var(--foreground)]",
        className,
      )}
    >
      {children}
    </button>
  );
}

/** The panel a tab shows; `hidden` while another tab is selected. */
export function TabPanel({
  value,
  children,
  className,
}: {
  value: string;
  children: ReactNode;
  className?: string | undefined;
}) {
  const tabs = useTabs("TabPanel");
  const ids = tabIds(tabs.base, value);
  return (
    <div
      role="tabpanel"
      id={ids.panel}
      aria-labelledby={ids.tab}
      hidden={tabs.value !== value}
      className={className}
    >
      {children}
    </div>
  );
}
