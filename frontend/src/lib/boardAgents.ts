import type { Agent, ConnectionType } from "./types";

/** Transports that can execute a generation request, mirroring `runtime.EXECUTABLE_CONNECTION_TYPES`. */
export const EXECUTABLE_CONNECTION_TYPES: ConnectionType[] = ["openai_compatible", "a2a"];

export interface GenerationCandidates {
  agents: Agent[];
  /** True when the board narrowed the list; false when every enabled generator is offered. */
  restrictedToBoard: boolean;
}

/**
 * Agents a Loop's generation may run on. A board that lists agents narrows the choice to those,
 * which is what the server enforces too; a board with an empty selection keeps every enabled
 * board profile whose transport can execute a request, so existing boards keep working. Organisation profiles
 * (Coordinator, Architect) are never offered: their job is the whole installation, not one Loop.
 */
export function generationAgents(
  agents: Agent[],
  boardAgentIds: string[] | undefined,
): GenerationCandidates {
  const usable = agents
    .filter(
      (agent) =>
        agent.enabled &&
        EXECUTABLE_CONNECTION_TYPES.includes(agent.connection_type) &&
        agent.role_template_scope !== "organisation",
    )
    .sort((left, right) => left.name.localeCompare(right.name));
  const selected = boardAgentIds ?? [];
  if (selected.length === 0) {
    return { agents: usable, restrictedToBoard: false };
  }
  return {
    agents: usable.filter((agent) => selected.includes(agent.id)),
    restrictedToBoard: true,
  };
}
