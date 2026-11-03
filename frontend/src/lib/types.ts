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
  loop_count: number;
  list_count: number;
  card_count: number;
  repository_ids: string[];
  agent_ids: string[];
}

export interface LoopAgentPreferences {
  loop_id: string;
  analysis_agent_id: string | null;
  roadmap_agent_id: string | null;
  qa_agent_id: string | null;
}

export interface BoardList {
  id: string;
  board_id: string;
  loop_id: string;
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

export type RoleScope = "board" | "organisation";

export interface RoleTemplate {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  built_in: boolean;
  builtin_key: string | null;
  scope: RoleScope;
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
  role_template_scope: RoleScope;
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
  role_template_scope: RoleScope;
}

export interface AgentTestResult {
  ok: boolean;
  status: string;
  message: string;
  latency_ms: number | null;
  models: string[];
  /** The tiny real chat completion behind the test; absent for an A2A agent. */
  completion?: {
    ok: boolean;
    status: string;
    message: string;
    latency_ms: number | null;
  } | null;
}

export type LoopStage =
  | "draft"
  | "analysis_review"
  | "planning"
  | "roadmap_review"
  | "ready"
  | "in_progress"
  | "replanning"
  | "awaiting_qa"
  | "completed"
  | "cancelled";

export type DocumentKind = "info" | "analysis_ai" | "analysis" | "roadmap_ai" | "roadmap";

export type DocumentState =
  | "empty"
  | "draft"
  | "ready_for_review"
  | "approved"
  | "changes_requested"
  | "stale";

export interface LoopDocument {
  loop_id: string;
  kind: DocumentKind;
  state: DocumentState;
  current_revision_id: string | null;
  current_revision_number: number | null;
  current_content: string | null;
  current_payload: Record<string, unknown> | null;
  current_created_at: string | null;
  approved_revision_id: string | null;
  approved_revision_number: number | null;
  approved_content: string | null;
  stale: boolean;
  stale_reasons: string[];
  revisions: Array<{
    id: string;
    revision_number: number;
    status: string;
    author_name: string;
    author_actor_type: string;
    created_at: string;
  }>;
}

export interface LoopDocuments {
  loop_id: string;
  loop_version: number;
  documents: Record<DocumentKind, LoopDocument>;
  approvals: Record<string, Record<string, unknown> | null>;
}

export interface LoopApproval {
  id: string;
  loop_id: string;
  scope: string;
  decision: string;
  reviewer_actor_id: string;
  reviewer_name: string;
  feedback: string;
  revisions: Record<string, string>;
  created_at: string;
}

export interface LoopBlocker {
  type: "phase" | "ticket";
  id: string;
  key?: string | null;
  title?: string;
  name?: string;
  reason: string;
  phase_number?: number | null;
}

export interface PlanTicketView {
  id: string;
  key: string;
  title: string;
  phase_id: string;
  phase_number: number;
  objective: string;
  instructions: string;
  required_actor: "any" | "human";
  execution_mode: "normal" | "pre_phase_gate";
  acceptance_criteria: string[];
  expected_evidence: string[];
  human_action_reason: string;
  human_instructions: string;
  prerequisite_ticket_ids: string[];
  prerequisite_phase_ids: string[];
  card_id: string | null;
  completed_at: string | null;
  ready: boolean;
  blockers: LoopBlocker[];
  human_action_required: boolean;
  downstream_phase_numbers: number[];
}

export interface PlanPhaseView {
  id: string;
  number: number;
  name: string;
  objective: string;
  entry_conditions: string[];
  exit_conditions: string[];
  prerequisite_phase_ids: string[];
  prerequisite_ticket_ids: string[];
  state: "pending" | "active" | "complete";
  blocked_by: LoopBlocker[];
  tickets: PlanTicketView[];
}

export interface LoopPlanView {
  loop_id: string;
  plan_id: string | null;
  revision_number: number | null;
  status: string;
  activated_at: string | null;
  approved_at: string | null;
  phases: PlanPhaseView[];
  warnings: Array<{ code: string; message: string }>;
}

export interface LoopReadiness {
  loop_id: string;
  stage: LoopStage;
  execution_allowed: boolean;
  blocked_reason: { code: string; message: string; stage?: string } | null;
  items: PlanTicketView[];
  phases: PlanPhaseView[];
}

export interface QaCycle {
  id: string;
  loop_id: string;
  cycle_number: number;
  status: string;
  card_id: string | null;
  instruction_revision: number;
  delivery_baseline: string;
  ai_instructions: Record<string, unknown>;
  human_instructions: Record<string, unknown>;
  results: Array<{
    id: string;
    scenario_id: string;
    status: string;
    reason: string;
    evidence: string;
    actor_name: string;
    actor_type: string;
    tested_baseline: string;
    created_at: string;
  }>;
  created_at: string;
  updated_at: string;
  decided_at: string | null;
  decision_note: string;
}

export interface Loop {
  id: string;
  board_id: string;
  name: string;
  goal: string;
  key: string;
  key_prefix: string;
  sequence: number;
  stage: LoopStage;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  cancelled_at: string | null;
  completed_at: string | null;
  history_id: string | null;
  documents: Record<DocumentKind, LoopDocument>;
  plan: {
    plan_id: string;
    revision_number: number;
    activated_at: string | null;
    phase_count: number;
    ticket_total: number;
    ticket_completed: number;
  } | null;
  qa: {
    cycle_id: string;
    cycle_number: number;
    status: string;
    card_id: string | null;
    open: boolean;
  } | null;
  progress: {
    ticket_total: number;
    ticket_completed: number;
    ticket_archived_incomplete: number;
  };
  warnings: Array<{ code: string; message: string; kind?: string; reasons?: string[] }>;
}

export interface GenerationRunRepository {
  id: string;
  name: string;
  branch: string | null;
  commit_sha: string | null;
  file_count: number;
  truncated: boolean;
  error?: string;
}

export interface GenerationRun {
  id: string;
  loop_id: string;
  purpose: "analysis" | "roadmap" | "qa";
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  /** The step the run reached: reading_info, analysing_repository, generating (null before 0010). */
  phase: string | null;
  error_code: string | null;
  error_message: string | null;
  attempts: number;
  output: Record<string, unknown>;
  /** Document revision ids, plus the repositories the run was based on (name, commit, file count). */
  source_revisions: Record<string, string | null | GenerationRunRepository[]>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  model: string | null;
  agent_name: string | null;
  usage: Record<string, unknown>;
}

export interface Repository {
  id: string;
  name: string;
  provider: "github";
  url: string;
  branch: string | null;
  enabled: boolean;
  has_token: boolean;
  token_hint: string | null;
  boards: Array<{ id: string; name: string }>;
  last_checked_at: string | null;
  last_check_status: string | null;
  last_check_detail: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoryCheck {
  status: string;
  detail: string | null;
  default_branch: string | null;
  private: boolean | null;
  size_kb: number | null;
  checked_at: string;
}

export interface HistorySummary {
  id: string;
  source_kind: "native" | "imported_legacy";
  conformance: string;
  board_id: string;
  loop_id: string | null;
  loop_key: string | null;
  loop_name: string;
  qa_status: string;
  completed_at: string | null;
  imported_at: string | null;
  created_at: string;
  content_hash: string;
  warnings: string[];
  label: string;
}

export interface HistoryDetail extends HistorySummary {
  envelope: Record<string, unknown>;
  artifacts: Array<{
    id: string;
    filename: string;
    media_type: string;
    content_hash: string;
    size_bytes: number;
    inclusion: string;
  }>;
}

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

export interface Credential {
  id: string;
  actor_id: string;
  actor_name: string | null;
  owner_actor_id: string | null;
  owner_name: string | null;
  name: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  token?: string;
}

export interface ApiMeta {
  api_version: string;
  scopes: string[];
  token_scopes: string[];
  member_token_scopes: string[];
  member_token_limits: { live: number; default_days: number; max_days: number };
  can_issue_tokens: boolean;
  features: Record<string, unknown>;
}

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  [key: string]: unknown;
}

export const ROLES = ["admin", "member"] as const;

export type Role = (typeof ROLES)[number];

export interface InviteCreated {
  user_id: string;
  user_name: string;
  token: string;
  path: string;
  expires_at: string;
  warning: string;
}

export interface UserAccount {
  id: string;
  name: string;
  role: Role;
  created_at: string;
  disabled: boolean;
  agent_access_count: number;
  agent_access_last_used_at: string | null;
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
  votes?: Array<{
    participant_id: string;
    display_name: string | null;
    position: string;
    justification: string;
    round_number: number;
    created_at: string;
  }>;
}

