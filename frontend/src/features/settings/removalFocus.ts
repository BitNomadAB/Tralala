import { useRef } from "react";
import { idPart } from "@/components/ui/roving";

/** The id of a list entry's control, so focus can be sent to it by the entry's id. */
export function entryControlId(list: string, entryId: string): string {
  return `${list}-${idPart(entryId)}`;
}

/**
 * Where focus goes once `removed` leaves the list of `ids` (WCAG 2.4.3): the next entry's control,
 * else the previous one's, else `fallback` (the list's heading). The removed entry's own control
 * disappears with it, and focus left on it would fall to the start of the page.
 */
export function removalFocusTarget(
  ids: readonly string[],
  removed: string,
  controlId: (entryId: string) => string,
  fallback: string,
): string {
  const index = ids.indexOf(removed);
  if (index === -1) return fallback;
  const neighbour = ids[index + 1] ?? ids[index - 1];
  return neighbour === undefined ? fallback : controlId(neighbour);
}

/**
 * Focuses the element with `id`, if it is in the page. A heading is not focusable by itself, so it
 * gets `tabindex="-1"` first: focus from a script, with no Tab stop.
 */
export function focusById(id: string): void {
  const element = document.getElementById(id);
  if (!element) return;
  if (!element.matches("a[href], button, input, select, textarea, [tabindex]")) {
    element.setAttribute("tabindex", "-1");
  }
  element.focus();
}

/**
 * Focus for a dialog that removes an entry from a list. Once the removal succeeded, `remember` the
 * element that should take focus (`removalFocusTarget`); the dialog's `onCloseAutoFocus` then
 * sends it there instead of back to the removed entry's button. A dialog closed without removing
 * anything gives focus back as usual.
 */
export function useRemovalFocus() {
  const target = useRef<string | null>(null);
  return {
    remember: (id: string) => {
      target.current = id;
    },
    onCloseAutoFocus: (event: Event) => {
      const id = target.current;
      target.current = null;
      if (id === null) return;
      event.preventDefault();
      focusById(id);
    },
  };
}
