import type { ModelContextApi, ModelContextToolDefinition } from "./capability";

export interface ToolRegistration {
  registered: string[];
  unregistered: string[];
}

export interface WebMcpRegistry {
  register: (tools: ModelContextToolDefinition[]) => Promise<void>;
  unregister: (names: string[]) => Promise<void>;
  registeredNames: () => string[];
  dispose: () => void;
}

/**
 * Thin adapter around the browser tool registry.
 *
 * Registration is context-scoped: each React context owns one registry, registers only the
 * tools valid for that context, and disposes it (AbortController + unregisterTool) on exit.
 */
export function createRegistry(api: ModelContextApi): WebMcpRegistry {
  const controller = new AbortController();
  const active = new Map<string, ModelContextToolDefinition>();
  let disposed = false;

  async function register(tools: ModelContextToolDefinition[]) {
    for (const tool of tools) {
      if (disposed || active.has(tool.name)) continue;
      active.set(tool.name, tool);
      try {
        await api.registerTool(tool, { signal: controller.signal });
      } catch {
        active.delete(tool.name);
      }
    }
  }

  async function unregister(names: string[]) {
    for (const name of names) {
      if (!active.has(name)) continue;
      active.delete(name);
      if (api.unregisterTool) {
        try {
          await api.unregisterTool(name);
        } catch {
          // Best-effort cleanup; the browser may already have dropped the registration.
        }
      }
    }
  }

  return {
    register,
    unregister,
    registeredNames: () => [...active.keys()],
    dispose: () => {
      disposed = true;
      controller.abort();
      const names = [...active.keys()];
      active.clear();
      if (api.unregisterTool) {
        for (const name of names) {
          try {
            void api.unregisterTool(name);
          } catch {
            // ignore
          }
        }
      }
    },
  };
}
