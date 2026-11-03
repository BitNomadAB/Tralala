import type { ModelContextToolDefinition } from "./capability";

export interface McpTool extends ModelContextToolDefinition {
  requiredScope?: string;
}

export const stringSchema = (description: string) => ({ type: "string", description });

export const boardIdSchema = stringSchema("Board identifier");

/**
 * An optional string argument, or undefined when it is absent or empty. The input schemas declare
 * these as strings, so anything else an agent sends is treated as absent, never as "[object Object]".
 */
export function optionalText(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}
