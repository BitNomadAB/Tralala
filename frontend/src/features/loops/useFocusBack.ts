import { useEffect, useEffectEvent, useRef } from "react";

/** Whether the focus is on nothing: the element that had it left the page and took it along. */
export function focusIsLost(): boolean {
  const active = document.activeElement;
  return active === null || active === document.body;
}

/**
 * Gives the focus to `target()` when `open` turns false while the focus fell to the page with
 * what closed (a confirmation, a question, a run panel), so a keyboard user goes on from the
 * control that opened it instead of from the top of the page (WCAG 2.4.3). A focus the person
 * moved somewhere else is left where it is. `target` is read when the focus goes back, so it may
 * name an element that the same render brought back.
 */
export function useFocusBack(open: boolean, target: () => HTMLElement | null | undefined): void {
  const wasOpen = useRef(open);
  const giveBack = useEffectEvent(() => {
    if (focusIsLost()) target()?.focus();
  });
  useEffect(() => {
    if (wasOpen.current && !open) giveBack();
    wasOpen.current = open;
  }, [open]);
}
