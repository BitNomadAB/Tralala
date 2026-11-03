import type { Agent, AgentDirectoryEntry, AgentTestResult, ConnectionType } from "../types";
import { json, request, type QueryValue } from "./client";

export interface AgentPayload {
  name?: string;
  description?: string;
  role_template_id?: string | null;
  role_prompt_override?: string | null;
  connection_type?: ConnectionType;
  base_url?: string;
  model?: string | null;
  api_key?: string | null;
  clear_api_key?: boolean;
  temperature?: number | null;
  max_output_tokens?: number | null;
  timeout_seconds?: number;
  enabled?: boolean;
}

/** AI agents: their configuration, the directory and the connection tests. */
export const agentsApi = {
  async listAgents(params: { q?: string; enabled?: boolean } = {}): Promise<Agent[]> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    return json(await request<Agent[]>(`/agents?${query.toString()}`));
  },

  async getAgent(agentId: string): Promise<Agent> {
    return json(await request<Agent>(`/agents/${agentId}`));
  },

  async listAgentDirectory(): Promise<AgentDirectoryEntry[]> {
    return json(await request<AgentDirectoryEntry[]>("/agents/directory"));
  },

  async createAgent(payload: AgentPayload): Promise<Agent> {
    return json(await request<Agent>("/agents", { method: "POST", body: payload }));
  },

  async updateAgent(agentId: string, payload: AgentPayload): Promise<Agent> {
    return json(await request<Agent>(`/agents/${agentId}`, { method: "PATCH", body: payload }));
  },

  async duplicateAgent(agentId: string, name?: string): Promise<Agent> {
    return json(
      await request<Agent>(`/agents/${agentId}/duplicate`, {
        method: "POST",
        body: name ? { name } : {},
      }),
    );
  },

  async testAgent(
    agentId: string,
    payload: {
      connection_type?: ConnectionType;
      base_url?: string;
      model?: string;
      api_key?: string;
      no_api_key?: boolean;
    } = {},
  ): Promise<AgentTestResult> {
    return json(
      await request<AgentTestResult>(`/agents/${agentId}/test`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  /** Test a configuration that has not been saved: nothing is written on success or failure. */
  async probeAgent(payload: {
    connection_type?: ConnectionType;
    base_url?: string;
    model?: string;
    api_key?: string;
    no_api_key?: boolean;
    timeout_seconds?: number;
  }): Promise<AgentTestResult> {
    return json(
      await request<AgentTestResult>("/agents/test", {
        method: "POST",
        body: payload,
      }),
    );
  },

  async deleteAgent(agentId: string): Promise<void> {
    await request(`/agents/${agentId}`, { method: "DELETE" });
  },
};
