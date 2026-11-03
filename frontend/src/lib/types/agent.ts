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
  /** The last connection test found that the model calls tools, so a run lets it read repositories. */
  supports_tools: boolean;
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
  /** The model answered the test's dummy tool with a call to it. */
  supports_tools?: boolean;
  /** The tiny real chat completion behind the test; absent for an A2A agent. */
  completion?: {
    ok: boolean;
    status: string;
    message: string;
    latency_ms: number | null;
  } | null;
}
