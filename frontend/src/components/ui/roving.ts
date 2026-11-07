import type { KeyboardEvent } from "react";

/** How a set of items is laid out, which decides the arrow keys that move between them. */
export type Orientation = "horizontal" | "vertical";

/**
 * The index a key moves a roving focus to among `count` items, or null for a key that does not
 * move it. A horizontal set (a tablist) takes Left and Right and wraps at the ends; a vertical one
 * (a listbox) takes Up and Down and stops at the ends. Home and End go to the first and the last.
 */
export function rovingIndex(
  key: string,
  current: number,
  count: number,
  orientation: Orientation,
): number | null {
  if (count <= 0) return null;
  const last = count - 1;
  if (key === "Home") return 0;
  if (key === "End") return last;
  const back = orientation === "horizontal" ? "ArrowLeft" : "ArrowUp";
  const forward = orientation === "horizontal" ? "ArrowRight" : "ArrowDown";
  if (key !== back && key !== forward) return null;
  const step = key === forward ? 1 : -1;
  if (orientation === "horizontal") return (current + step + count) % count;
  return Math.min(last, Math.max(0, current + step));
}

/** A value as a fragment of an element id: anything but letters, digits, `-` and `_` becomes `_`. */
export function idPart(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, "_");
}

/** The ids that pair a tab with its panel, so `aria-controls` and `aria-labelledby` agree. */
export function tabIds(base: string, value: string): { tab: string; panel: string } {
  const part = idPart(value);
  return { tab: `${base}-tab-${part}`, panel: `${base}-panel-${part}` };
}

/**
 * The keys of a tab inside a `role="tablist"`: Left/Right, Home and End move the focus to another
 * tab of the same list and select it (selection follows focus). The tab's value is read from its
 * `data-value`, so every tab of the kit carries one.
 */
export function onTabKeyDown(event: KeyboardEvent<HTMLElement>, select: (value: string) => void) {
  const list = event.currentTarget.closest('[role="tablist"]');
  if (!list) return;
  const tabs = Array.from(list.querySelectorAll<HTMLElement>('[role="tab"]')).filter(
    (tab) => tab.closest('[role="tablist"]') === list && !tab.hasAttribute("disabled"),
  );
  const next = rovingIndex(event.key, tabs.indexOf(event.currentTarget), tabs.length, "horizontal");
  if (next === null) return;
  const target = tabs[next];
  if (!target) return;
  event.preventDefault();
  target.focus();
  const value = target.dataset.value;
  if (value !== undefined) select(value);
}
