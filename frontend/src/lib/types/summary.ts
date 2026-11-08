import type { DocumentKind, LoopStage } from "./loop";

/** Who a Loop waits for now: a person's decision, an agent's document, anyone, or nobody. */
export type LoopWaitingOn = "person" | "agent" | "anyone" | "nobody";

/**
 * One Loop as `GET /boards/{id}/loop-summaries` gives it (the rows of the `loop_summaries` tool):
 * computed by the server from what the Loop records, never written by anyone.
 */
export interface LoopSummary {
  id: string;
  key: string;
  name: string;
  goal: string;
  stage: LoopStage;
  /** One sentence for a worker; the UI words its own line from the fields below. */
  next: string;
  waiting_on: LoopWaitingOn;
  execution_allowed: boolean;
  tickets: {
    ready: number;
    needs_input: number;
    blocked: number;
    completed: number;
    total: number;
    /** Needs input, or ready and a person's task. */
    needs_person: number;
    by_column: Record<string, number>;
  };
  /** Each document's state and current revision, e.g. `approved r3` or `empty`. */
  documents: Record<DocumentKind, string>;
}

export interface LoopSummaries {
  board_id: string;
  loops: LoopSummary[];
  count: number;
}
