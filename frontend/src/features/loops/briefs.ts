import type { MarkTone } from "@/components/ui/chip";
import type { BriefVerdict, HumanBrief, ObstacleLevel, RoadmapBrief, SizeKind } from "@/lib/types";

/**
 * Reading a brief and the technical revision it was written from. The ids of an analysis brief's
 * items lead back to findings; a person sees their titles, never the ids.
 */

export const VERDICT_TEXT: Record<BriefVerdict, string> = {
  yes: "Yes",
  yes_with_conditions: "Yes, with conditions",
  no: "No",
  unclear: "Unclear",
};

/** The verdict as the sign's mark: go, go with care, stop. */
export const VERDICT_MARK: Record<BriefVerdict, MarkTone> = {
  yes: "success",
  yes_with_conditions: "warning",
  no: "danger",
  unclear: "warning",
};

export const SIZE_TEXT: Record<SizeKind, string> = {
  small: "Small",
  medium: "Medium",
  large: "Large",
};

export const LEVEL_TEXT: Record<ObstacleLevel, string> = {
  business: "Business",
  technical: "Technical",
  security: "Security",
  legal: "Legal",
  people_time: "People and time",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** The analysis brief a revision carries as its payload; the server validated its shape. */
export function isHumanBrief(value: unknown): value is HumanBrief {
  return isRecord(value) && typeof value.verdict === "string" && Array.isArray(value.obstacles);
}

/** The RoadMap brief a revision carries as its payload. */
export function isRoadmapBrief(value: unknown): value is RoadmapBrief {
  return isRecord(value) && typeof value.goal === "string";
}

/**
 * The goal a RoadMap brief shows: its goal, or the summary of a brief written before the goal
 * (schema version 1, which also listed the order of work); null for anything else.
 */
export function roadmapGoal(value: unknown): string | null {
  if (isRoadmapBrief(value)) return value.goal;
  return isRecord(value) && Array.isArray(value.order) && typeof value.summary === "string"
    ? value.summary
    : null;
}

/** Each finding of a technical analysis by id: its title. */
export function findingTitles(technical: unknown): Map<string, string> {
  const titles = new Map<string, string>();
  if (!isRecord(technical)) return titles;
  for (const finding of records(technical.findings)) {
    titles.set(text(finding.id), text(finding.title) || "A finding without a title");
  }
  return titles;
}

/** A finding of a technical analysis as the Raw text view lists it, every field as written. */
export interface RawFinding {
  id: string;
  category: string;
  title: string;
  technical_detail: string;
  plain_language: string;
}

/** The findings of a technical analysis, in its order. */
export function findingsOf(technical: unknown): RawFinding[] {
  if (!isRecord(technical)) return [];
  return records(technical.findings).map((finding) => ({
    id: text(finding.id),
    category: text(finding.category),
    title: text(finding.title),
    technical_detail: text(finding.technical_detail),
    plain_language: text(finding.plain_language),
  }));
}
