import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

const DIALOG = '[role="dialog"], [role="alertdialog"]';

/** Focus fell back to the body: the element that had it has gone, or a dialog has closed. */
function dropped(): boolean {
  const active = document.activeElement;
  return active === null || active === document.body;
}

/**
 * Keeps the keyboard's place in the view `root` (WCAG 2.4.3), checked after every change on
 * screen. When an action takes away its own control (Stop once the run has stopped, the decision
 * once it is taken) and focus fell back to the body, `target` takes it, so a screen reader says
 * where the person is and the next Tab goes on from the view instead of the page's start. When a
 * dialog opened from the view closes, focus goes back to the control that opened it: Radix gives
 * it back only to a `DialogTrigger`, which these dialogs, opened from state, do not have. Focus
 * the person moved elsewhere, even to nothing, is left alone.
 */
export function useFocusRescue(
  root: RefObject<HTMLElement | null>,
  target: RefObject<HTMLElement | null>,
): void {
  const focused = useRef<HTMLElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const node = root.current;
    if (!node) return undefined;
    const enter = (event: FocusEvent) => {
      focused.current = event.target instanceof HTMLElement ? event.target : null;
      opener.current = null;
    };
    const leave = (event: FocusEvent) => {
      const left = event.target;
      const next = event.relatedTarget;
      if (next instanceof Element && !node.contains(next) && next.closest(DIALOG)) {
        opener.current = left instanceof HTMLElement ? left : null;
      }
      // A control that leaves the page is no longer connected; one the person left still is.
      if (next !== null || (left instanceof Node && left.isConnected)) focused.current = null;
    };
    node.addEventListener("focusin", enter);
    node.addEventListener("focusout", leave);
    return () => {
      node.removeEventListener("focusin", enter);
      node.removeEventListener("focusout", leave);
    };
  }, [root]);

  useLayoutEffect(() => {
    const lost = focused.current;
    if (lost !== null && !lost.isConnected) {
      focused.current = null;
      if (dropped()) target.current?.focus();
      return;
    }
    const back = opener.current;
    if (back !== null && dropped()) {
      opener.current = null;
      (back.isConnected ? back : target.current)?.focus();
    }
  });
}
