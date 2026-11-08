export type BoardStatus = "active" | "archived" | "maintenance" | "error" | "migration_failed";

export type Priority = "none" | "low" | "medium" | "high" | "urgent";

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
  /** The globs of each linked repository that has any; a repository without an entry is read whole. */
  repository_paths: Record<string, RepositoryPaths>;
}

/** Which files of one linked repository a Loop's analysis reads; both empty reads all of them. */
export interface RepositoryPaths {
  /** When not empty, only files one of these globs matches are read. */
  focus_paths: string[];
  /** Files one of these globs matches are never read. */
  exclude_paths: string[];
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

/** A person a Ticket may be given to (`GET /boards/{id}/actors`, `people`). */
export interface BoardPerson {
  id: string;
  name: string;
  type: "user";
  role: string;
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
  labels: { name: string; color: string }[];
  created_at: string;
  updated_at: string;
  list_count: number;
}

/** How a repository is read: the GitHub API, or a Tralala-managed mirror of an HTTPS Git host. */
export type RepositoryProvider = "github" | "git_https";

export interface Repository {
  id: string;
  name: string;
  provider: RepositoryProvider;
  url: string;
  branch: string | null;
  enabled: boolean;
  has_token: boolean;
  token_hint: string | null;
  boards: { id: string; name: string }[];
  last_checked_at: string | null;
  last_check_status: string | null;
  last_check_detail: string | null;
  /** The branch the remote's HEAD names, as the last check or fetch found it (git_https). */
  default_branch?: string | null | undefined;
  /** The mirror's last good fetch: its commit, when, and its size on disk (git_https). */
  last_sha?: string | null | undefined;
  fetched_at?: string | null | undefined;
  mirror_bytes?: number | null | undefined;
  /** Why the last fetch failed, or `mirror_cleanup_failed` when the mirror could not be removed. */
  mirror_error?: string | null | undefined;
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
  artifacts: {
    id: string;
    filename: string;
    media_type: string;
    content_hash: string;
    size_bytes: number;
    inclusion: string;
  }[];
}

export const PRIORITIES: Priority[] = ["none", "low", "medium", "high", "urgent"];
