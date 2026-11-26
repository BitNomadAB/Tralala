/**
 * A POC decision (`kind` `decision`): a choice an agent took without stopping because it can be
 * changed afterwards. Something missing from a person (`missing`: an API key, an account) is
 * recorded the same way while the work goes around it. Neither blocks anything; a person answers
 * each later, with OK or with feedback that becomes a new Ticket.
 */
export type PocKind = "decision" | "missing";

/** Open until a person answers; OK may later become feedback, feedback is final. */
export type PocStatus = "open" | "ok" | "feedback";

/**
 * One record as `GET /boards/{id}/loops/{id}/poc-decisions` lists it. For kind `missing` the
 * fields mean: `missing` what a person has to provide, `reason` why it is needed, `chosen` how the
 * work went around it, `change_path` what is done once it is there. Every field but `details` is
 * plain text for a person; `details` is the agent's raw text.
 */
export interface PocDecision {
  id: string;
  /** `<LoopKey>-POC-<nnn>`. */
  key: string;
  loop_id: string;
  /** The Ticket it was taken on, if any. */
  card_id: string | null;
  ticket_key: string | null;
  ticket_title: string | null;
  /** The Phase of that Ticket, when it is planned. */
  phase_number: number | null;
  phase_complete: boolean | null;
  kind: PocKind;
  title: string;
  chosen: string;
  reason: string;
  alternative: string;
  change_path: string;
  missing: string;
  /** What other work builds on it; empty when nothing does. */
  builds_on: string;
  built_on: boolean;
  details: string;
  status: PocStatus;
  feedback: string;
  /** The Ticket the feedback became. */
  feedback_ticket: { id: string; key: string | null } | null;
  /**
   * Open, and every Ticket of the Loop is done, or other work builds on it and the Phase of its
   * Ticket is complete: it waits for a review now.
   */
  due: boolean;
  created_at: string;
  created_by: { name: string; type: string };
  answered_at: string | null;
  answered_by_name: string | null;
}

/** A Loop's records counted, as the list and each Loop summary give them. */
export interface PocCounts {
  open: number;
  built_on_open: number;
  missing_open: number;
  due: number;
  answered: number;
}

/** The Loop's records in review order, and the counts over all of them. */
export interface PocDecisionList {
  items: PocDecision[];
  counts: PocCounts;
}

/** What `POST .../poc-decisions` records; a person may record one too. */
export interface PocDecisionPayload {
  kind: PocKind;
  card_id?: string | undefined;
  title: string;
  chosen: string;
  reason: string;
  alternative?: string | undefined;
  change_path: string;
  missing?: string | undefined;
  builds_on?: string | undefined;
  details?: string | undefined;
}

/** A person's answer: OK, or feedback of 1 to 2,000 characters. */
export type PocAnswer = { answer: "ok" } | { answer: "feedback"; feedback: string };

/**
 * A Loop's stop list: the only things an agent stops and waits for a person for. `is_default`
 * while no person has written one for the Loop.
 */
export interface StopList {
  stops: string[];
  is_default: boolean;
}
