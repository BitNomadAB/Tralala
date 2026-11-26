import { expect, type Page } from "playwright/test";

/** A tool's answer: the `structuredContent` of a successful `tools/call`. */
export type ToolAnswer = Record<string, unknown>;

/** The MCP revision these helpers speak; every request states it, in `_meta` and in a header. */
const PROTOCOL_VERSION = "2026-07-28";

/** The older revision `/mcp` speaks on the same address; its client opens with `initialize`. */
export const LEGACY_VERSION = "2025-06-18";

let nextId = 1;

/** A header value as MCP carries it: plain when it is header-safe ASCII, else its Base64 form. */
function headerValue(value: string): string {
  const sentinel = value.startsWith("=?base64?") && value.endsWith("?=");
  if (/^[\x20-\x7e]*$/.test(value) && value === value.trim() && !sentinel) return value;
  return `=?base64?${Buffer.from(value, "utf8").toString("base64")}?=`;
}

/** What a request declares and brings beyond its params: its client's capabilities. */
interface RequestOptions {
  capabilities?: Record<string, unknown>;
}

/** One JSON-RPC request to `/mcp` with the worker's key; the `result`, or a failed expectation. */
async function rpc(
  page: Page,
  token: string,
  method: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  const result = (await rpcResult(page, token, method, params)) as { resultType?: string };
  expect(result.resultType, `${method} did not complete`).toBe("complete");
  return result;
}

/** One JSON-RPC request to `/mcp`: the `result` whatever its `resultType`, or a failed step. */
async function rpcResult(
  page: Page,
  token: string,
  method: string,
  params: Record<string, unknown>,
  options: RequestOptions = {},
): Promise<unknown> {
  const message = await rpcMessage(page, token, method, params, options);
  if (message.error) throw new Error(`${method} failed: ${message.error.message}`);
  return message.result;
}

/** One JSON-RPC request to `/mcp` and the whole answer, an error included. */
async function rpcMessage(
  page: Page,
  token: string,
  method: string,
  params: Record<string, unknown>,
  options: RequestOptions = {},
): Promise<{ result?: unknown; error?: { code: number; message: string; data?: unknown } }> {
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
    "io.modelcontextprotocol/clientCapabilities": options.capabilities ?? {},
  };
  const response = await page.request.post("/mcp", {
    headers,
    data: { jsonrpc: "2.0", id: nextId++, method, params: { ...params, _meta } },
  });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as {
    result?: unknown;
    error?: { code: number; message: string; data?: unknown };
  };
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

/** What a tool that asks for input answers: a complete result, or `input_required`. */
export interface AskedResult {
  resultType: "complete" | "input_required";
  inputRequests?: Record<string, { method: string; params: Record<string, unknown> }>;
  requestState?: string;
  structuredContent?: ToolAnswer;
  isError?: boolean;
  content?: { text: string }[];
}

/** What a client of 2026-07-28 brings to a tool that may ask: its modes, answers and state. */
export interface AskOptions {
  /** The elicitation modes the client declares, e.g. `{ url: {} }`; none when absent. */
  elicitation?: Record<string, unknown>;
  inputResponses?: Record<string, Record<string, unknown>>;
  requestState?: string;
}

function askParams(name: string, args: Record<string, unknown>, options: AskOptions) {
  return {
    name,
    arguments: args,
    ...(options.inputResponses ? { inputResponses: options.inputResponses } : {}),
    ...(options.requestState !== undefined ? { requestState: options.requestState } : {}),
  };
}

function askCapabilities(options: AskOptions): RequestOptions {
  return options.elicitation ? { capabilities: { elicitation: options.elicitation } } : {};
}

/**
 * Calls a tool that may ask the client for input (`ask_person`), declaring the elicitation modes
 * and repeating a call with `inputResponses` and `requestState`; the result as it came.
 */
export async function mcpAsk(
  page: Page,
  token: string,
  name: string,
  args: Record<string, unknown>,
  options: AskOptions = {},
): Promise<AskedResult> {
  const params = askParams(name, args, options);
  const result = (await rpcResult(
    page,
    token,
    "tools/call",
    params,
    askCapabilities(options),
  )) as AskedResult;
  // A tool that failed says why in its content; the step that called it names that, not a missing
  // field further on.
  if (result.isError) throw new Error(`${name} failed: ${result.content?.[0]?.text ?? ""}`);
  return result;
}

/** Calls a tool that may ask and must be refused at the protocol level; the JSON-RPC error. */
export async function mcpAskError(
  page: Page,
  token: string,
  name: string,
  args: Record<string, unknown>,
  options: AskOptions = {},
): Promise<{ code: number; message: string; data?: unknown }> {
  const params = askParams(name, args, options);
  const message = await rpcMessage(page, token, "tools/call", params, askCapabilities(options));
  expect(message.error, `${name} was not refused: ${JSON.stringify(message.result)}`).toBeDefined();
  return message.error ?? { code: 0, message: "" };
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

/** What `initialize` answers a client of revision 2025-06-18. */
export interface LegacyInitialize {
  protocolVersion: string;
  capabilities: Record<string, unknown>;
  serverInfo: { name: string; version: string };
  instructions: string;
}

/**
 * One POST as a client of revision 2025-06-18 sends it: no `_meta`, no `Mcp-Method`, and after
 * `initialize` the version it negotiated in `MCP-Protocol-Version`.
 */
export async function legacyPost(
  page: Page,
  token: string,
  message: Record<string, unknown>,
  version?: string,
) {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: "application/json, text/event-stream",
  };
  if (version !== undefined) headers["MCP-Protocol-Version"] = version;
  return page.request.post("/mcp", { headers, data: { jsonrpc: "2.0", ...message } });
}

/** One 2025-06-18 request after the handshake; its `result`, or a failed expectation. */
export async function legacyRpc(
  page: Page,
  token: string,
  method: string,
  params?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const message = { id: nextId++, method, ...(params ? { params } : {}) };
  const response = await legacyPost(page, token, message, LEGACY_VERSION);
  expect(response.status(), await response.text()).toBe(200);
  const answer = (await response.json()) as {
    result?: Record<string, unknown>;
    error?: { message: string };
  };
  if (answer.error) throw new Error(`${method} failed: ${answer.error.message}`);
  expect(answer.result, `${method} has no result`).toBeDefined();
  return answer.result ?? {};
}

/**
 * Connects as a client of revision 2025-06-18 does: `initialize` without any MCP header, then
 * `notifications/initialized` with the negotiated version. Returns what `initialize` answered
 * and the session id the server sent, which must be none.
 */
export async function legacyConnect(
  page: Page,
  token: string,
): Promise<{ initialize: LegacyInitialize; sessionId: string | undefined }> {
  const opened = await legacyPost(page, token, {
    id: nextId++,
    method: "initialize",
    params: {
      protocolVersion: LEGACY_VERSION,
      capabilities: {},
      clientInfo: { name: "tralala-e2e-legacy", version: "1.0.0" },
    },
  });
  expect(opened.status(), await opened.text()).toBe(200);
  const initialize = ((await opened.json()) as { result: LegacyInitialize }).result;
  const initialized = await legacyPost(
    page,
    token,
    { method: "notifications/initialized" },
    initialize.protocolVersion,
  );
  expect(initialized.status()).toBe(202);
  return { initialize, sessionId: opened.headers()["mcp-session-id"] };
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
