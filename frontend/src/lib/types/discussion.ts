export interface DiscussionParticipant {
  id: string;
  participant_id: string;
  participant_type: string;
  display_name: string;
  role_template_name: string | null;
  role_source: string;
  system_prompt_sha256: string;
  snapshot_at: string;
}

/** A participant's position on the thread's goal: the analysis brief's verdict set. */
export type DiscussionPosition = "yes" | "yes_with_conditions" | "no" | "unclear";

/**
 * A participant's answer in the standard (version 1), stored beside its prose. `format` says how it
 * was read: at once, after one repair, or never (then it is prose with the position `unclear`).
 */
export interface DiscussionAnswer {
  version: number;
  format: "structured" | "repaired" | "prose";
  position: DiscussionPosition;
  recommendation: string;
  pros: string[];
  cons: string[];
  conditions: string[];
  open_questions: string[];
  confidence: "high" | "medium" | "low" | null;
  problem: string | null;
}

/** One participant's latest answer: where it stands and what it recommends. */
export interface DiscussionStance {
  participant_id: string;
  participant: string;
  position: DiscussionPosition;
  recommendation: string;
  confidence: string | null;
  format: string;
  message_id: string;
  round_number: number;
}

/** A condition or an open question, with the participants who named it. */
export interface DiscussionPoint {
  text: string;
  participants: string[];
}

/** Decision support Tralala computes after a round; its verdict is a suggestion, never a decision. */
export interface DiscussionSynthesis {
  version: number;
  kind: "decision_support";
  written_by: string;
  round_id?: string | null;
  round_number: number;
  thread_round: number;
  suggestion: { verdict: DiscussionPosition; reason: string };
  counts: Record<string, number>;
  go: DiscussionStance[];
  stop: DiscussionStance[];
  unclear: DiscussionStance[];
  conditions: DiscussionPoint[];
  open_questions: DiscussionPoint[];
  missing: string[];
}

export interface DiscussionMessage {
  id: string;
  parent_message_id: string | null;
  author_actor_id: string;
  author_type: string;
  author_name: string;
  author_role: string | null;
  content: string;
  status: string;
  model: string | null;
  round_number: number;
  created_at: string;
  /** A participant's structured answer; null for a person's message and an older answer. */
  answer?: DiscussionAnswer | null;
}

export interface DiscussionRound {
  id: string;
  run_id: string;
  round_number: number;
  status: string;
  answers: number;
  failures: number;
  repeats: number;
  tokens_used: number;
  elapsed_ms: number;
  created_at: string;
  finished_at: string;
  synthesis?: DiscussionSynthesis | null;
}

export interface DiscussionRun {
  id: string;
  discussion_id: string;
  status: string;
  autonomy: boolean;
  rounds_requested: number;
  rounds_completed: number;
  token_budget: number | null;
  tokens_used: number;
  time_budget_seconds: number | null;
  elapsed_ms: number;
  stop_reason: string | null;
  error: string | null;
  started_by_name: string;
  created_at: string;
  started_at: string;
  finished_at: string | null;
  rounds: DiscussionRound[];
}

export interface DiscussionRunSummary {
  discussion_id: string;
  run_id: string;
  status: string;
  thread_status: string;
  run_state: string;
  run_status: string;
  rounds_requested: number;
  rounds_completed: number;
  round_number: number;
  tokens_used: number;
  elapsed_ms: number;
  stop_reason: string | null;
  answers: number;
  round_status: string | null;
  votes: { participant_id: string; position: string }[];
  failures: { agent: string; error: string }[];
  pending: boolean;
  run: DiscussionRun;
}

/** Who an inbox row waits for: the person's decision, the agents talking, or nobody (decided). */
export type DiscussionWaitsFor = "your_decision" | "agents" | "nobody";

/** One thread in the Discussions inbox, on any board the person may read. */
export interface DiscussionInboxRow {
  discussion_id: string;
  board_id: string;
  board_name: string;
  loop_id: string | null;
  loop_key: string | null;
  loop_name: string | null;
  card_id: string | null;
  ticket_key: string | null;
  card_title: string | null;
  /** The question the person asked (the thread's goal). */
  question: string;
  status: string;
  run_state: string;
  /** The newest round's suggested verdict; null before a round. */
  verdict: string | null;
  /** For going ahead, against, cannot tell, not answered, after the newest round. */
  counts: { go: number; stop: number; unclear: number; missing: number };
  participant_count: number;
  round_count: number;
  max_rounds: number;
  asked_by_name: string;
  last_activity_at: string;
  decided_by_name: string | null;
  waits_for: DiscussionWaitsFor;
}

/** At most 200 rows, decision first, then talking, then decided; `total` counts them all. */
export interface DiscussionInbox {
  items: DiscussionInboxRow[];
  total: number;
}

export interface Discussion {
  id: string;
  card_id: string;
  card_title: string | null;
  ticket_key: string | null;
  loop_id: string | null;
  loop_key: string | null;
  loop_name: string | null;
  title: string;
  goal: string;
  mode: string;
  status: string;
  run_state: string;
  created_by_name: string;
  max_rounds: number;
  round_count: number;
  tokens_used: number;
  elapsed_ms: number;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  participant_count: number;
  message_count: number;
  /** Who recorded the newest decision (approve, veto, rework); null before any. */
  decided_by_name?: string | null;
  participants: DiscussionParticipant[];
  messages: DiscussionMessage[];
  active_run?: DiscussionRun | null;
  runs?: DiscussionRun[];
  /** Set on a message response: started, already_running, thread_closed or no_participants. */
  auto_run?: string | null;
  /** The newest round's decision support; null before the first round. */
  synthesis?: DiscussionSynthesis | null;
  /** Each participant's current position, derived from its latest structured answer. */
  positions?: DiscussionStance[];
  votes?: {
    participant_id: string;
    display_name: string | null;
    position: string;
    justification: string;
    round_number: number;
    created_at: string;
  }[];
}
