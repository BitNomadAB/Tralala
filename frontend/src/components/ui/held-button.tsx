import { Button, type ButtonProps } from "./button";

export interface HeldButtonProps extends Omit<ButtonProps, "aria-disabled"> {
  /** Whether a press does nothing now: its request runs, or a reason shown elsewhere holds it. */
  held: boolean;
  /** The element that says why, while held (a reason line several buttons share, a hint). */
  reasonId?: string | undefined;
}

/**
 * A button that is held up without leaving the focus (WCAG 2.4.3): by what pressing it started
 * (saving, approving, deleting) or by a reason shown elsewhere. A button that turns `disabled` once
 * pressed drops the focus to the page, and a keyboard user starts again from the top. While `held`
 * this one is `aria-disabled` instead: it stays focused, looks and reads as unavailable (described
 * by `reasonId`), and a click, Enter or Space does nothing. `disabled` stays for what the person
 * did not cause, such as a read-only Loop, and gives way while held, so a pressed button keeps the
 * focus. `ReasonButton` is this button with its reason as visible text beside it.
 */
export function HeldButton({
  held,
  reasonId,
  disabled,
  onClick,
  onKeyDown,
  "aria-describedby": describedBy,
  ...props
}: HeldButtonProps) {
  const description = [describedBy, held ? reasonId : undefined].filter(Boolean).join(" ");
  return (
    <Button
      {...props}
      disabled={held ? false : disabled}
      aria-disabled={held ? true : undefined}
      aria-describedby={description === "" ? undefined : description}
      onClick={(event) => {
        // Also cancels a submit button's form submission, implicit submission included.
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
