import { focusTarget } from "./useFocusAfter";

/** The rows under `root` that carry `data-{attribute}`, in order. */
export function rowsOf(root: Element | null, attribute: string): HTMLElement[] {
  return Array.from(root?.querySelectorAll<HTMLElement>(`[data-${attribute}]`) ?? []);
}

/** The row under `root` whose `data-{attribute}` is `id`, or undefined. */
export function rowOf(
  root: Element | null,
  attribute: string,
  id: string,
): HTMLElement | undefined {
  return rowsOf(root, attribute).find((row) => row.getAttribute(`data-${attribute}`) === id);
}

/**
 * Where the focus goes once the row `id` was deleted from a list (WCAG 2.4.3): the control marked
 * `target` in the next row, else in the row before it, else `fallback` (the section's heading or
 * button), so the person stays where they were. The deleted row may still be on screen for a
 * moment; it is skipped.
 */
export function afterDeletedRow(
  root: Element | null,
  { attribute, id, target }: { attribute: string; id: string; target: string },
  fallback: () => HTMLElement | null | undefined,
): HTMLElement | null {
  const rows = rowsOf(root, attribute);
  const at = rows.findIndex((row) => row.getAttribute(`data-${attribute}`) === id);
  const others = [...rows.slice(at + 1), ...rows.slice(0, Math.max(at, 0)).reverse()];
  for (const row of others) {
    if (row.getAttribute(`data-${attribute}`) === id) continue;
    const control = focusTarget(row, target);
    if (control) return control;
  }
  return fallback() ?? null;
}
