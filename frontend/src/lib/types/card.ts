import type { Label, Priority } from "./board";
import type { LoopBlocker } from "./loop";

export interface Card {
  id: string;
  board_id: string;
  loop_id: string;
  list_id: string;
  title: string;
  description: string;
  position: number;
  priority: Priority;
  due_at: string | null;
  completed_at: string | null;
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
