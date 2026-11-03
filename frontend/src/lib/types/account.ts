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
  /** Sent to an administrator only: the generated first password is still in the data directory. */
  bootstrap_password_file_present?: boolean | undefined;
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
