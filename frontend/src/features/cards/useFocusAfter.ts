import { useCallback, useEffect, useRef, useState } from "react";

/** Finds the element that takes the focus next, or null while it is not on the page yet. */
export type FocusFinder = () => HTMLElement | null | undefined;

/**
 * Whether nobody holds the focus: it fell to the body (the page) or to the dialog's own container
 * (Radix puts it there when the focused control leaves), or it is still where the request was made.
 */
function focusIsFree(from: Element | null): boolean {
  const active = document.activeElement;
  return (
    active === null ||
    active === document.body ||
    active === from ||
    active.getAttribute("role") === "dialog"
  );
}

/**
 * Where the focus goes once a change has taken away, or replaced, the control that had it
 * (WCAG 2.4.3): Start work that became Mark complete, an editor that closed, a row that was
 * deleted. Without this the browser drops the focus on the page (Radix on the dialog), and a
 * keyboard or screen reader user starts again from the top of the Ticket.
 *
 * `focusAfter(find)` focuses what `find` returns after the next render of the calling component
 * that has it on the page, so `find` may wait for the change to show (return null until then).
 * A later request replaces an earlier one, and a request is dropped once the person has put the
 * focus somewhere else themselves.
 */
export function useFocusAfter(): (find: FocusFinder) => void {
  const request = useRef<{ find: FocusFinder; from: Element | null } | null>(null);
  const [, rerender] = useState(0);

  useEffect(() => {
    const pending = request.current;
    if (!pending) return;
    if (!focusIsFree(pending.from)) {
      request.current = null;
      return;
    }
    const target = pending.find();
    if (!target?.isConnected) return;
    request.current = null;
    target.focus();
  });

  return useCallback((find: FocusFinder) => {
    request.current = { find, from: document.activeElement };
    rerender((count) => count + 1);
  }, []);
}

/** The element inside `root` marked `data-focus-target="name"`, or null. */
export function focusTarget(root: Element | null | undefined, name: string): HTMLElement | null {
  return root?.querySelector<HTMLElement>(`[data-focus-target="${name}"]`) ?? null;
}
