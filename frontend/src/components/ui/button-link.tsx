import { Link, type LinkProps } from "react-router-dom";
import { cn } from "@/lib/utils";
import { buttonVariants, type ButtonVariantProps } from "./buttonVariants";

/** The quiet "← Settings" way back above an editor's heading: a link's look, not a button's. */
const BACK =
  "text-xs font-normal text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline";

export interface ButtonLinkProps extends LinkProps {
  variant?: NonNullable<ButtonVariantProps["variant"]> | "back" | undefined;
  /** `none` for the way back, which is sized by its text. */
  size?: "sm" | "md" | "none" | undefined;
}

/**
 * Something that looks like a button but goes to another page, so it is a link (WCAG 4.1.2): a
 * person can open it in a new tab, copy its address, and a screen reader says where it leads. It
 * takes `Button`'s look (`buttonVariants`), so the two never drift apart.
 */
export function ButtonLink({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ButtonLinkProps) {
  const look = buttonVariants({
    variant: variant === "back" ? null : variant,
    size: size === "none" ? null : size,
  });
  return <Link className={cn(look, variant === "back" && BACK, className)} {...props} />;
}
