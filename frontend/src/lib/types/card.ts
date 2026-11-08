import type { Label, Priority } from "./board";
import type { LoopBlocker } from "./loop";
import type { TicketState, WaitingFor, Workplace } from "./work";

/** The face for people (`FaceView` on the server): what a person reads first, summary included. */
export interface TicketFace {
  summary: string;
  why: string;
  if_skipped: string;
  pros: string[];
  cons: string[];
  steps: string[];
}

export interface Card {
  id: string;
  board_id: string;
  loop_id: string;
  list_id: string;
  title: string;
  description: string;
  /** What the Ticket is about in a sentence or two; empty when nobody has written one. */
  summary: string;
  summary_source: "" | "plan" | "person" | "agent";
  /** The title or description changed after the summary was written. */
  summary_stale: boolean;
  /** The face for people; null for a Ticket written without one. */
  face: TicketFace | null;
  position: number;
  priority: Priority;
  due_at: string | null;
  completed_at: string | null;
  /** Who owns the Ticket: a person's or an agent's actor id; null when nobody does. */
  assignee_actor_id: string | null;
  assignee_type: string | null;
  assignee_name: string | null;
  assigned_at: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  version: number;
  labels: Label[];
  checklist_total: number;
  checklist_completed: number;
  comment_count: number;
  ticket_key: string | null;
  kind: "ticket" | "qa" | "manual";
  phase_number: number | null;
  required_actor: "any" | "human";
  execution_mode: "normal" | "pre_phase_gate";
  human_action_required: boolean;
  human_action_reason: string;
  human_instructions: string;
  human_confirmed_at: string | null;
  acceptance_criteria: string[];
  expected_evidence: string[];
  ready: boolean;
  blockers: LoopBlocker[];
  downstream_phase_numbers: number[];
  plan_item_id: string | null;
  workplace: Workplace;
  waiting_for: WaitingFor;
  /** Why it waits; empty when it waits for nothing. */
  waiting_reason: string;
  waiting_set_at: string | null;
  /** The actor id of whoever set the wait. */
  waiting_set_by: string | null;
  /** Null on a completed Ticket. */
  state: TicketState | null;
  /** It needs input, or it is ready and the task itself is a person's. */
  needs_person: boolean;
}

export interface ChecklistItem {
  id: string;
  checklist_id: string;
  text: string;
  completed: boolean;
  position: number;
}

export interface Checklist {
  id: string;
  card_id: string;
  title: string;
  position: number;
  items: ChecklistItem[];
}

export interface Comment {
  id: string;
  card_id: string;
  actor_id: string;
  actor_name: string | null;
  actor_type: string | null;
  content: string;
  created_at: string;
  updated_at: string;
  /** Written (or last edited) after the Ticket's Loop was completed: not in the Loop's history. */
  after_loop_completed: boolean;
}

export type MentionStatus = "queued" | "running" | "completed" | "failed";

export interface MentionJob {
  id: string;
  card_id: string;
  comment_id: string;
  agent_id: string;
  agent_name: string;
  status: MentionStatus;
  attempts: number;
  error: string | null;
  response_comment_id: string | null;
  tokens_used: number;
  role_template_id: string | null;
  role_template_name: string | null;
  role_source: string | null;
  system_prompt_sha256: string | null;
  requested_by_actor_id: string;
  requested_by_type: string;
  requested_by_name: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  can_retry: boolean;
}

export interface CardDetail extends Card {
  checklists?: Checklist[];
  comments?: Comment[];
}

export interface ActivityEntry {
  id: string;
  actor_id: string;
  actor_type: "user" | "agent" | "service";
  action: string;
  entity_type: string;
  entity_id: string;
  request_id: string | null;
  timestamp: string;
  changes: Record<string, unknown>;
}
