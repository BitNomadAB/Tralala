export type BoardStatus =
  | "active"
  | "archived"
  | "maintenance"
  | "error"
  | "migration_failed";
export type Priority = "none" | "low" | "medium" | "high" | "urgent";

export interface UserPreferences {
  theme_mode: "dark" | "light" | "system" | null;
  theme_kit: "carenomad" | "matchmap" | "classic" | null;
}

export interface Actor {
  id: string;
  type: "user" | "agent" | "service";
  name: string;
  role?: string | null;
  scopes: string[];
  preferences?: UserPreferences | null;
}

export interface Board {
  id: string;
  name: string;
  description: string;
  status: BoardStatus;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  schema_version: number;
  schema_revision: string | null;
  list_count: number;
  card_count: number;
}

export interface BoardList {
  id: string;
  board_id: string;
  name: string;
  position: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  card_count: number;
}

export interface Label {
  id: string;
  name: string;
  color: string;
}

export interface BoardTemplate {
  id: string;
  name: string;
  description: string;
  lists: string[];
  labels: Array<{ name: string; color: string }>;
  created_at: string;
  updated_at: string;
  list_count: number;
}

export interface RoleTemplate {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  built_in: boolean;
  builtin_key: string | null;
  customized: boolean;
  agent_count: number;
  created_at: string;
  updated_at: string;
}

export type ConnectionType = "openai_compatible" | "a2a";

export interface Agent {
  id: string;
  name: string;
  description: string;
  role_template_id: string | null;
  role_template_name: string | null;
  role_template_updated_at: string | null;
  has_role_override: boolean;
  connection_type: ConnectionType;
  base_url: string;
  model: string | null;
  has_api_key: boolean;
  api_key_hint: string | null;
  temperature: number | null;
  max_output_tokens: number | null;
  timeout_seconds: number;
  enabled: boolean;
  last_test_status: string | null;
  last_test_message: string | null;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentDirectoryEntry {
  id: string;
  name: string;
  role_template_id: string | null;
  role_template_name: string | null;
}

export interface AgentTestResult {
  ok: boolean;
  status: string;
  message: string;
  latency_ms: number | null;
  models: string[];
}

export interface Card {
  id: string;
  board_id: string;
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

export interface Credential {
  id: string;
  actor_id: string;
  actor_name: string | null;
  name: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  token?: string;
}

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  [key: string]: unknown;
}

export const SCOPES = [
  "boards:read",
  "boards:write",
  "boards:admin",
  "cards:read",
  "cards:write",
  "comments:write",
  "agents:read",
  "agents:write",
  "agents:admin",
  "discussions:read",
  "discussions:write",
  "discussions:admin",
  "discussions:vote",
] as const;

export const ROLES = ["admin", "member"] as const;

export type Role = (typeof ROLES)[number];

export interface UserAccount {
  id: string;
  name: string;
  role: Role;
  created_at: string;
  disabled: boolean;
}

export const PRIORITIES: Priority[] = ["none", "low", "medium", "high", "urgent"];

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
  votes: Array<{ participant_id: string; position: string }>;
  failures: Array<{ agent: string; error: string }>;
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
}

export interface Discussion {
  id: string;
  card_id: string;
  card_title: string | null;
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
  votes?: Array<{
    participant_id: string;
    display_name: string | null;
    position: string;
    justification: string;
    round_number: number;
    created_at: string;
  }>;
}

