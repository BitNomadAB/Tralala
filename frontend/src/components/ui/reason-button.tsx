import { useId } from "react";
import { cn } from "@/lib/utils";
import { Button, type ButtonProps } from "./button";

export interface ReasonButtonProps extends Omit<ButtonProps, "disabled"> {
  /** Why the button cannot be used now; null, undefined or empty when it can. */
  disabledReason: string | null | undefined;
  /** Classes for the span that holds the button and its reason (the button takes `className`). */
  wrapperClassName?: string | undefined;
}

/**
 * A button that says why it cannot be used (WCAG 1.3.1, 3.3.2). A disabled button leaves the tab
 * order and never shows its `title`, so a person cannot find out what holds it up. While
 * `disabledReason` is set this one is `aria-disabled` instead: it stays focusable (and keeps focus
 * when it becomes blocked), a screen reader reads it as unavailable with the reason as its
 * description, the reason is visible text beside it, and a click, Enter or Space does nothing.
 */
export function ReasonButton({
  disabledReason,
  wrapperClassName,
  onClick,
  onKeyDown,
  "aria-describedby": describedBy,
  ...props
}: ReasonButtonProps) {
  const reasonId = useId();
  const blocked = typeof disabledReason === "string" && disabledReason !== "";
  const description = [describedBy, blocked ? reasonId : undefined].filter(Boolean).join(" ");
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", wrapperClassName)}>
      <Button
        {...props}
        aria-disabled={blocked ? true : undefined}
        aria-describedby={description === "" ? undefined : description}
        onClick={(event) => {
          // Also cancels a submit button's form submission, implicit submission included.
          if (blocked) event.preventDefault();
          else onClick?.(event);
        }}
        onKeyDown={(event) => {
          if (blocked && (event.key === "Enter" || event.key === " ")) event.preventDefault();
          onKeyDown?.(event);
        }}
      />
      {blocked ? (
        <span id={reasonId} className="text-xs text-[var(--muted-foreground)]">
          {disabledReason}
        </span>
      ) : null}
    </span>
  );
}
