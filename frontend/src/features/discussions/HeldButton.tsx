import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * A button held up by a reason shown elsewhere: the decision buttons that share one reason line,
 * or "Ask again", whose reason is the reply's hint. Like `ReasonButton` it stays focusable while
 * `held` (`aria-disabled`, described by `reasonId`), and a click, Enter or Space does nothing, so
 * focus stays on it when it becomes unavailable under the keyboard.
 */
export function HeldButton({
  held,
  reasonId,
  onClick,
  onKeyDown,
  ...props
}: Omit<ButtonProps, "disabled" | "aria-describedby" | "aria-disabled"> & {
  held: boolean;
  /** The element that says why, while held. */
  reasonId?: string | undefined;
}) {
  return (
    <Button
      {...props}
      aria-disabled={held ? true : undefined}
      aria-describedby={held ? reasonId : undefined}
      onClick={(event) => {
        // Also cancels a submit button's form submission.
        if (held) event.preventDefault();
        else onClick?.(event);
      }}
      onKeyDown={(event) => {
        if (held && (event.key === "Enter" || event.key === " ")) event.preventDefault();
        onKeyDown?.(event);
      }}
    />
  );
}
