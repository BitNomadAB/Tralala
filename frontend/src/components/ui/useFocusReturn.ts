import { useRef } from "react";

type AutoFocusHandler = (event: Event) => void;

/**
 * Radix gives focus back on close only to a `DialogTrigger`. Most dialogs here open from state (a
 * menu item, a button that sets `open`), and those would leave focus on the body, so a keyboard user
 * starts again from the top of the page. This remembers what had focus when the dialog opened and
 * gives focus back to it on close. A caller that moves focus itself on close (it calls
 * `preventDefault`, for example to focus the next row after a removal) keeps the last word, and an
 * opener that has left the page falls back to what Radix does.
 */
export function useFocusReturn(
  onOpenAutoFocus?: AutoFocusHandler,
  onCloseAutoFocus?: AutoFocusHandler,
): { onOpenAutoFocus: AutoFocusHandler; onCloseAutoFocus: AutoFocusHandler } {
  const opener = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: (event) => {
      // Radix sends this before it moves focus into the dialog, so the active element is the opener.
      const active = document.activeElement;
      opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
      onOpenAutoFocus?.(event);
    },
    onCloseAutoFocus: (event) => {
      onCloseAutoFocus?.(event);
      const target = opener.current;
      opener.current = null;
      if (event.defaultPrevented || !target?.isConnected) return;
      event.preventDefault();
      target.focus();
    },
  };
}
