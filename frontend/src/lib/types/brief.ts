/**
 * The brief a person reads of an analysis or a RoadMap (`backend/app/schemas/briefs.py`): the human
 * revision's payload. The ids carry the traceability back to the technical revision and are never
 * shown as text.
 */

export type BriefVerdict = "yes" | "yes_with_conditions" | "no" | "unclear";
export type ObstacleLevel = "business" | "technical" | "security" | "legal" | "people_time";
export type SizeKind = "small" | "medium" | "large";

export interface BriefObstacle {
  level: ObstacleLevel;
  text: string;
  finding_ids: string[];
}

export interface BriefPoint {
  text: string;
  finding_ids: string[];
}

export interface BriefDecision {
  question: string;
  finding_ids: string[];
}

/** How big the work is: a kind a person can compare, and one sentence why. */
export interface BriefSize {
  kind: SizeKind;
  text: string;
}

/**
 * The analysis brief, a sign: `verdict_line` and `size` are absent (or empty) in a brief written
 * before the sign existed, and such a brief may hold more items than a new one may.
 */
export interface HumanBrief {
  schema_version: number;
  obstacles: BriefObstacle[];
  pros: BriefPoint[];
  cons: BriefPoint[];
  decisions: BriefDecision[];
  size?: BriefSize | null | undefined;
  verdict: BriefVerdict;
  verdict_line?: string | undefined;
  verdict_reason: string;
  summary: string;
  recommendation: string;
}

export interface BriefPhaseStep {
  phase_id: string;
  what_happens: string;
  done_when: string;
}

export interface BriefPart {
  text: string;
  phase_ids: string[];
  ticket_ids: string[];
}

export interface BriefRisk {
  text: string;
  phase_ids: string[];
}

export interface RoadmapBrief {
  schema_version: number;
  order: BriefPhaseStep[];
  your_part: BriefPart[];
  could_block: BriefRisk[];
  summary: string;
}
