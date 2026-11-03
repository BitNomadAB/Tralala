export interface LoopAgentPreferences {
  loop_id: string;
  analysis_agent_id: string | null;
  roadmap_agent_id: string | null;
  qa_agent_id: string | null;
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
  "empty" | "draft" | "ready_for_review" | "approved" | "changes_requested" | "stale";

export interface LoopDocument {
  loop_id: string;
  kind: DocumentKind;
  state: DocumentState;
  current_revision_id: string | null;
  current_revision_number: number | null;
  current_content: string | null;
  current_payload: Record<string, unknown> | null;
  current_created_at: string | null;
  /**
   * How the current revision came about: a run's agent and model, `rendered` for a view rendered
   * from the structure, `written` for one a board agent wrote for people (absent before PLN-007).
   */
  current_provenance?: Record<string, unknown> | undefined;
  approved_revision_id: string | null;
  approved_revision_number: number | null;
  approved_content: string | null;
  stale: boolean;
  stale_reasons: string[];
  revisions: {
    id: string;
    revision_number: number;
    status: string;
    author_name: string;
    author_actor_type: string;
    created_at: string;
  }[];
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
  warnings: { code: string; message: string }[];
}

/** A Ticket added outside the plan while it executes; it never blocks the plan or completion. */
export interface UnplannedTicket {
  id: string;
  key: string | null;
  title: string;
  completed_at: string | null;
  archived_at: string | null;
}

/** A note in a Loop's log: what belongs to the Loop and to no single Ticket. */
export interface LoopNote {
  id: string;
  loop_id: string;
  author_actor_id: string;
  author_actor_type: string;
  author_name: string;
  content: string;
  created_at: string;
}

/** A page of notes, oldest first, and how many the Loop holds. */
export interface LoopNotePage {
  notes: LoopNote[];
  count: number;
}

export interface LoopReadiness {
  loop_id: string;
  stage: LoopStage;
  execution_allowed: boolean;
  blocked_reason: { code: string; message: string; stage?: string } | null;
  items: PlanTicketView[];
  phases: PlanPhaseView[];
  unplanned: UnplannedTicket[];
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
  results: {
    id: string;
    scenario_id: string;
    status: string;
    reason: string;
    evidence: string;
    actor_name: string;
    actor_type: string;
    tested_baseline: string;
    created_at: string;
  }[];
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
  warnings: { code: string; message: string; kind?: string; reasons?: string[] }[];
}

export interface GenerationRunRepository {
  id: string;
  name: string;
  branch: string | null;
  commit_sha: string | null;
  /** How it was read: `git_https` through the mirror (absent on GitHub entries of older runs). */
  provider?: string;
  /** When the mirror was last brought up to date. */
  fetched_at?: string;
  /** The fetch before this run failed, so the run read the mirror from `fetched_at`. */
  stale_mirror?: boolean;
  file_count: number;
  truncated: boolean;
  /** The repository's share of the run's context budget, in characters (runs since AGL-004). */
  budget_chars?: number;
  /** What its files took of that share. */
  snapshot_chars_included?: number;
  /** Not even one file fitted in the share. */
  content_omitted?: boolean;
  /** `tools` when the model read the repository itself; `file_count` is then what it could read.
   * Absent on a repository sent as a snapshot. */
  reading?: "tools";
  /** Files too large for the workspace (a run that read through tools). */
  left_out?: number;
  error?: string;
}

/** The stages of a run's process tree, in the order a run reaches them. */
export type RunStage = "documents" | "repository" | "writing" | "checking" | "saving";

/** What one step of the tree is: a stage's own line, a tool call, the model's note, a repair round,
 * a limit the run reached, or why something failed. */
export type RunTraceStepKind = "step" | "tool" | "note" | "repair" | "limit" | "error";

/** One step of a run's process tree: a plain-language sentence, never a file's content. */
export interface RunTraceStep {
  stage: RunStage;
  kind: RunTraceStepKind;
  text: string;
  at: string;
  /** A tool call: the tool, its arguments, and what the answer held (sizes and counts). */
  tool?: string;
  arguments?: Record<string, unknown>;
  answer?: {
    summary?: string;
    chars?: number;
    files_read?: string[];
    lines?: [number, number] | null;
    entries?: number;
    matches?: number;
    truncated?: boolean;
    error?: string | null;
  };
}

/** What a generation run writes; `analysis_human` is the analysis written for people. */
export type GenerationPurpose = "analysis" | "analysis_human" | "roadmap" | "qa";

export interface GenerationRun {
  id: string;
  loop_id: string;
  purpose: GenerationPurpose;
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
  /** The run's process tree, written step by step while it works (absent before revision 0013). */
  trace?: RunTraceStep[] | undefined;
}
