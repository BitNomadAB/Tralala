import { expect, type Page } from "playwright/test";

/** A tool's answer: the `structuredContent` of a successful `tools/call`. */
export type ToolAnswer = Record<string, unknown>;

/** The one MCP revision `/mcp` speaks; every request states it, in `_meta` and in a header. */
const PROTOCOL_VERSION = "2026-07-28";

let nextId = 1;

/** A header value as MCP carries it: plain when it is header-safe ASCII, else its Base64 form. */
function headerValue(value: string): string {
  const sentinel = value.startsWith("=?base64?") && value.endsWith("?=");
  if (/^[\x20-\x7e]*$/.test(value) && value === value.trim() && !sentinel) return value;
  return `=?base64?${Buffer.from(value, "utf8").toString("base64")}?=`;
}

/** One JSON-RPC request to `/mcp` with the worker's key; the `result`, or a failed expectation. */
async function rpc(
  page: Page,
  token: string,
  method: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: "application/json, text/event-stream",
    "MCP-Protocol-Version": PROTOCOL_VERSION,
    "Mcp-Method": method,
  };
  if (method === "tools/call" && typeof params.name === "string") {
    headers["Mcp-Name"] = headerValue(params.name);
  }
  const _meta = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": { name: "tralala-e2e", version: "1.0.0" },
    "io.modelcontextprotocol/clientCapabilities": {},
  };
  const response = await page.request.post("/mcp", {
    headers,
    data: { jsonrpc: "2.0", id: nextId++, method, params: { ...params, _meta } },
  });
  expect(response.status(), await response.text()).toBe(200);
  const message = (await response.json()) as {
    result?: { resultType?: string };
    error?: { message: string };
  };
  if (message.error) throw new Error(`${method} failed: ${message.error.message}`);
  expect(message.result?.resultType, `${method} did not complete`).toBe("complete");
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

/**
 * Reads the instructions a board agent works under for `purpose` (`read_instructions`) and
 * returns the whole answer; its `instructions_id` goes with what the worker writes to them.
 */
export async function readInstructions(
  page: Page,
  token: string,
  boardId: string,
  loopId: string,
  purpose: string,
): Promise<ToolAnswer & { instructions_id: string }> {
  const answer = await mcpCall(page, token, "read_instructions", {
    board_id: boardId,
    loop_id: loopId,
    purpose,
  });
  expect(typeof answer.instructions_id).toBe("string");
  return { ...answer, instructions_id: String(answer.instructions_id) };
}
