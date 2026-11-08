import type { MarkTone } from "@/components/ui/chip";
import type { BriefVerdict, HumanBrief, ObstacleLevel, RoadmapBrief, SizeKind } from "@/lib/types";

/**
 * Reading a brief and the technical revision it was written from. The ids of a brief's items lead
 * back to findings, Phases and Tickets; a person sees their titles, never the ids.
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
  return isRecord(value) && Array.isArray(value.order) && typeof value.summary === "string";
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

export interface PlanTitles {
  phases: Map<string, { number: number; title: string }>;
  tickets: Map<string, string>;
}

/** Each Phase ("Phase 2 — Sign-in") and Ticket ("AN001-3 Confirm") of a technical RoadMap by id. */
export function planTitles(technical: unknown): PlanTitles {
  const phases = new Map<string, { number: number; title: string }>();
  const tickets = new Map<string, string>();
  if (!isRecord(technical)) return { phases, tickets };
  for (const phase of records(technical.phases)) {
    const number = typeof phase.number === "number" ? phase.number : 0;
    phases.set(text(phase.id), { number, title: `Phase ${number} — ${text(phase.name)}` });
    for (const ticket of records(phase.tickets)) {
      const key = text(ticket.key);
      tickets.set(text(ticket.id), key ? `${key} ${text(ticket.title)}` : text(ticket.title));
    }
  }
  return { phases, tickets };
}

const GONE = "No longer in the technical version";

/** The titles an item's ids stand for, in its order; an id the technical revision lacks says so. */
export function sourcesOf(ids: readonly string[], titles: ReadonlyMap<string, string>): string[] {
  return ids.map((id) => titles.get(id) ?? GONE);
}

export function phaseSources(ids: readonly string[], plan: PlanTitles): string[] {
  return ids.map((id) => plan.phases.get(id)?.title ?? GONE);
}

/** The brief's Phases in the plan's order, as the server renders them. */
export function orderedSteps(brief: RoadmapBrief, plan: PlanTitles): RoadmapBrief["order"] {
  const number = (id: string) => plan.phases.get(id)?.number ?? 0;
  return [...brief.order].sort((left, right) => number(left.phase_id) - number(right.phase_id));
}
