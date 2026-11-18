import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * A button that stays focusable while its request runs (WCAG 2.4.3): `aria-disabled` instead of
 * `disabled`, which would drop the focus on the page, and a press does nothing until the answer
 * is in. Read as unavailable by a screen reader, dimmed on screen as a disabled button is.
 */
export function PendingButton({
  pending,
  onClick,
  onKeyDown,
  ...props
}: ButtonProps & { pending: boolean }) {
  return (
    <Button
      {...props}
      aria-disabled={pending ? true : undefined}
      onClick={(event) => {
        // Also cancels a submit button's form submission.
        if (pending) event.preventDefault();
        else onClick?.(event);
      }}
      onKeyDown={(event) => {
        if (pending && (event.key === "Enter" || event.key === " ")) event.preventDefault();
        onKeyDown?.(event);
      }}
    />
  );
}
