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

export interface DiscussionBoard {
  board_id: string;
  board_name: string;
  status: string;
  discussion_count: number;
  open_count: number;
  last_activity_at: string | null;
  /** Tickets in the board: a discussion needs one, so a board with none cannot host one yet. */
  ticket_count: number;
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
  participants: DiscussionParticipant[];
  messages: DiscussionMessage[];
  active_run?: DiscussionRun | null;
  runs?: DiscussionRun[];
  /** Set on a message response: started, already_running, thread_closed or no_participants. */
  auto_run?: string | null;
  votes?: {
    participant_id: string;
    display_name: string | null;
    position: string;
    justification: string;
    round_number: number;
    created_at: string;
  }[];
}
