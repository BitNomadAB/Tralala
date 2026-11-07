import { cn } from "@/lib/utils";

const SIZES = {
  sm: "size-[22px] text-[11px]",
  md: "size-8 text-[13px]",
} as const;

/** The first letters of the first two words, upper case: "Mike Hansen" is MH, "Mike" is M. */
function initials(name: string): string {
  const letters = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => Array.from(word)[0] ?? "")
    .join("");
  return letters === "" ? "?" : letters.toLocaleUpperCase();
}

/**
 * A person or an agent as a round mark with initials. Beside the name it repeats, it is decoration
 * and hidden from a screen reader; pass `label` where it stands alone, and it is an image with that
 * name. `title` carries the full name for a pointer either way.
 */
export function Avatar({
  name,
  size = "md",
  label,
  className,
}: {
  name: string;
  size?: keyof typeof SIZES | undefined;
  label?: string | undefined;
  className?: string | undefined;
}) {
  return (
    <span
      title={name}
      {...(label === undefined ? { "aria-hidden": true } : { role: "img", "aria-label": label })}
      className={cn(
        "inline-grid shrink-0 place-items-center rounded-full border border-[var(--border)] bg-[var(--surface-raised)] font-semibold leading-none text-[var(--foreground)]",
        SIZES[size],
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}
