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

/** Where the row `id` stands among the rows under `root`, -1 when it is not there. */
export function rowIndex(root: Element | null, attribute: string, id: string): number {
  return rowsOf(root, attribute).findIndex((row) => row.getAttribute(`data-${attribute}`) === id);
}

/**
 * Where the focus goes once the row `id` was deleted from a list (WCAG 2.4.3): the control marked
 * `target` in the next row, else in the row before it, else `fallback` (the section's heading or
 * button), so the person stays where they were. The deleted row may still be on screen for a
 * moment, and is then skipped; once it has left, `index` (where it stood, `rowIndex` taken before
 * the delete) says which row came after it.
 */
export function afterDeletedRow(
  root: Element | null,
  {
    attribute,
    id,
    target,
    index,
  }: { attribute: string; id: string; target: string; index: number },
  fallback: () => HTMLElement | null | undefined,
): HTMLElement | null {
  const rows = rowsOf(root, attribute);
  const shown = rows.findIndex((row) => row.getAttribute(`data-${attribute}`) === id);
  const at = shown >= 0 ? shown : Math.min(Math.max(index, 0), rows.length);
  const next = shown >= 0 ? at + 1 : at;
  const others = [...rows.slice(next), ...rows.slice(0, at).reverse()];
  for (const row of others) {
    const control = focusTarget(row, target);
    if (control) return control;
  }
  return fallback() ?? null;
}
