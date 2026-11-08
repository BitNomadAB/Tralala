import { useId, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const HEADINGS = { 2: "h2", 3: "h3", 4: "h4" } as const;

type HeadingLevel = keyof typeof HEADINGS;

interface HeaderProps {
  title: ReactNode;
  count?: number | undefined;
  /** A link or a control on the right ("Add file", the For you | Raw text switch). */
  trailing?: ReactNode;
  /** `sm`: the small uppercase label; `lg`: the bold sentence-case heading ("What will be done"). */
  size?: "sm" | "lg" | undefined;
  level?: HeadingLevel | undefined;
}

/** A section's heading line: the title, a muted `count` after it, and the `trailing` slot. */
export function SectionHeader({
  title,
  count,
  trailing,
  size = "sm",
  level = 3,
  id,
  className,
}: HeaderProps & { id?: string | undefined; className?: string | undefined }) {
  const Heading = HEADINGS[level];
  return (
    <header className={cn("mb-2.5 flex items-baseline justify-between gap-3", className)}>
      <Heading
        id={id}
        className={cn(
          "m-0 font-semibold",
          size === "lg"
            ? "text-base tracking-[0.005em] text-[var(--foreground)]"
            : "text-xs uppercase tracking-label text-[var(--foreground-faint)]",
        )}
      >
        {title}
        {count === undefined ? null : (
          <>
            {/* The space keeps the accessible name "Files 0", not "Files0". */}{" "}
            <span className="ml-1 font-medium tabular-nums text-[var(--foreground-faint)]">
              {count}
            </span>
          </>
        )}
      </Heading>
      {trailing}
    </header>
  );
}

/** A `<section>` named by its SectionHeader, with the content under it. */
export function Section({
  children,
  className,
  ...header
}: HeaderProps & { children: ReactNode; className?: string | undefined }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={className}>
      <SectionHeader id={headingId} {...header} />
      {children}
    </section>
  );
}
