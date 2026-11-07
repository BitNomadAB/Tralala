import type { BadgeTone } from "@/components/ui/badge";

/** How a position reads to a person; the same words as the analysis brief's verdict. */
const POSITION_LABELS: Record<string, string> = {
  yes: "Yes",
  yes_with_conditions: "Yes, with conditions",
  no: "No",
  unclear: "Unclear",
};

const POSITION_TONES: Record<string, BadgeTone> = {
  yes: "success",
  yes_with_conditions: "warning",
  no: "danger",
  unclear: "neutral",
};

/** A position as a person reads it; an unknown value (an older vote) is shown as it is. */
export function positionLabel(position: string): string {
  return POSITION_LABELS[position] ?? position;
}

export function positionTone(position: string): BadgeTone {
  return POSITION_TONES[position] ?? "neutral";
}
