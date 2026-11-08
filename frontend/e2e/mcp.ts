import { expect, type Page } from "playwright/test";

/** A tool's answer: the `structuredContent` of a successful `tools/call`. */
export type ToolAnswer = Record<string, unknown>;

let nextId = 1;

/** One JSON-RPC message to `/mcp` with the worker's key; the `result`, or a failed expectation. */
async function rpc(page: Page, token: string, method: string, params: unknown): Promise<unknown> {
  const response = await page.request.post("/mcp", {
    headers: { Authorization: `Bearer ${token}` },
    data: { jsonrpc: "2.0", id: nextId++, method, params },
  });
  expect(response.status(), await response.text()).toBe(200);
  const message = (await response.json()) as { result?: unknown; error?: { message: string } };
  if (message.error) throw new Error(`${method} failed: ${message.error.message}`);
  return message.result;
}

/** The names `tools/list` offers this key. */
export async function mcpToolNames(page: Page, token: string): Promise<string[]> {
  const result = (await rpc(page, token, "tools/list", {})) as { tools: { name: string }[] };
  return result.tools.map((tool) => tool.name);
}

/** Calls one tool and returns its answer; a tool error fails the step with the server's words. */
export async function mcpCall(
  page: Page,
  token: string,
  name: string,
  args: Record<string, unknown> = {},
): Promise<ToolAnswer> {
  const result = (await rpc(page, token, "tools/call", { name, arguments: args })) as {
    isError: boolean;
    content: { text: string }[];
    structuredContent?: ToolAnswer;
  };
  if (result.isError) throw new Error(`${name} failed: ${result.content[0]?.text ?? ""}`);
  return result.structuredContent ?? {};
}

/** The error a refused tool call answers with: its code, its message and its details. */
export interface ToolRefusal {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

/** Calls one tool that must be refused and returns the refusal; an answer fails the step. */
export async function mcpRefusal(
  page: Page,
  token: string,
  name: string,
  args: Record<string, unknown> = {},
): Promise<ToolRefusal> {
  const result = (await rpc(page, token, "tools/call", { name, arguments: args })) as {
    isError: boolean;
    content: { text: string }[];
  };
  const text = result.content[0]?.text ?? "";
  expect(result.isError, `${name} was not refused: ${text}`).toBe(true);
  return (JSON.parse(text) as { error: ToolRefusal }).error;
}

/** A list in a tool's answer, as rows of the given shape. */
export function rowsOf<Row>(answer: ToolAnswer, field: string): Row[] {
  const value = answer[field];
  if (!Array.isArray(value)) throw new Error(`${field} is not a list: ${JSON.stringify(answer)}`);
  return value as Row[];
}
