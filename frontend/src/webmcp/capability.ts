/**
 * WebMCP is an experimental browser capability. Everything here is feature-detected and
 * isolated so the application keeps working through the normal UI and REST API when the
 * API is unavailable.
 */

export interface ModelContextToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  execute: (input: Record<string, unknown>) => unknown | Promise<unknown>;
}

export interface ModelContextApi {
  registerTool: (
    tool: ModelContextToolDefinition,
    options?: { signal?: AbortSignal },
  ) => void | Promise<void>;
  unregisterTool?: (name: string) => void | Promise<void>;
}

interface ModelContextHost {
  modelContext?: ModelContextApi;
}

export function getModelContext(): ModelContextApi | null {
  if (typeof navigator === "undefined" || typeof document === "undefined") return null;
  const candidates: ModelContextHost[] = [navigator as unknown as ModelContextHost];
  if (typeof document !== "undefined") {
    candidates.push(document as unknown as ModelContextHost);
  }
  for (const candidate of candidates) {
    const api = candidate.modelContext;
    if (api && typeof api.registerTool === "function") return api;
  }
  return null;
}

export function isWebMcpAvailable(): boolean {
  return getModelContext() !== null;
}
