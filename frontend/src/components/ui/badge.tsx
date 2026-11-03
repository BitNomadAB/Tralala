import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

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

export function LabelChip({ name, color }: { name: string; color: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{ borderColor: color, color }}
    >
      {name}
    </span>
  );
}
