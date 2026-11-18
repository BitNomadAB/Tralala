import { Link, type LinkProps } from "react-router-dom";
import { cn } from "@/lib/utils";

// The look of `Button` (components/ui/button.tsx) for the variants a link takes here.
const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-lg text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";

const VARIANTS = {
  primary: "bg-[var(--primary)] text-[var(--primary-foreground)] hover:brightness-110",
  secondary:
    "bg-[var(--surface-raised)] text-[var(--foreground)] border border-[var(--border)] hover:brightness-110",
  /** The quiet "← Settings" way back above an editor's heading. */
  back: "text-xs font-normal text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline",
} as const;

const SIZES = { sm: "h-8 px-2.5", md: "h-9 px-3.5", none: "" } as const;

export interface ButtonLinkProps extends LinkProps {
  variant?: keyof typeof VARIANTS | undefined;
  size?: keyof typeof SIZES | undefined;
}

/**
 * Something that looks like a button but goes to another page, so it is a link (WCAG 4.1.2): a
 * person can open it in a new tab, copy its address, and a screen reader says where it leads.
 */
export function ButtonLink({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ButtonLinkProps) {
  return <Link className={cn(BASE, VARIANTS[variant], SIZES[size], className)} {...props} />;
}
