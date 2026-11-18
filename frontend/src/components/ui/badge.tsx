import { Check } from "lucide-react";
import type { CSSProperties, HTMLAttributes } from "react";
import { labelInk } from "@/lib/labelInk";
import { cn } from "@/lib/utils";

/** Each tone's text sits on 18% of its own colour; the palette test reads these to check them. */
const tones = {
  neutral: "border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted-foreground)]",
  brand:
    "border-transparent bg-[color-mix(in_srgb,var(--primary)_18%,transparent)] text-[var(--primary)]",
  success:
    "border-transparent bg-[color-mix(in_srgb,var(--success)_18%,transparent)] text-[var(--success)]",
  warning:
    "border-transparent bg-[color-mix(in_srgb,var(--warning)_18%,transparent)] text-[var(--warning)]",
  danger:
    "border-transparent bg-[color-mix(in_srgb,var(--destructive)_18%,transparent)] text-[var(--destructive)]",
} as const;

export type BadgeTone = keyof typeof tones;

export function Badge({
  className,
  tone = "neutral",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

/**
 * A board label: its name in the label's own colour, moved only as far as each mode needs for 4.5:1
 * (`labelInk`; the `.label-ink` rule in index.css picks the dark or the light one), and its border
 * in the colour exactly as chosen. `selected` adds a check mark, so a chosen label does not rely on
 * colour or opacity to show it.
 */
export function LabelChip({
  name,
  color,
  selected = false,
}: {
  name: string;
  color: string;
  selected?: boolean | undefined;
}) {
  const ink = labelInk(color);
  const style: CSSProperties & Record<`--${string}`, string> = ink
    ? { borderColor: color, "--label-ink-dark": ink.dark, "--label-ink-light": ink.light }
    : { borderColor: color };
  return (
    <span
      className="label-ink inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={style}
    >
      {selected ? <Check size={12} aria-hidden="true" /> : null}
      {name}
    </span>
  );
}
