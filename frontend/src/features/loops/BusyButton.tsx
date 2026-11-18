import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * A button that keeps the focus through what pressing it started (WCAG 2.4.3). A button that turns
 * `disabled` once pressed (saving, approving) drops the focus to the page, and a keyboard user
 * starts again from the top. While `busy` this one is `aria-disabled` instead: it stays focused, a
 * screen reader reads it as unavailable, and a press does nothing. `disabled` stays for what the
 * person did not cause, such as a read-only Loop.
 */
export function BusyButton({ busy, disabled, onClick, ...props }: ButtonProps & { busy: boolean }) {
  return (
    <Button
      {...props}
      disabled={busy ? false : disabled}
      aria-disabled={busy ? true : undefined}
      onClick={(event) => {
        // Also cancels a submit button's form submission.
        if (busy) event.preventDefault();
        else onClick?.(event);
      }}
    />
  );
}
