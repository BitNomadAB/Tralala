import type { PageMeta } from "../types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly details: unknown;
  /** The id the server logged this request under; null when no response named one. */
  readonly requestId: string | null;

  constructor(
    message: string,
    options: {
      code: string;
      status: number;
      retryable?: boolean | undefined;
      details?: unknown;
      requestId?: string | null | undefined;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable ?? false;
    this.details = options.details;
    this.requestId = options.requestId ?? null;
  }
}

interface Envelope<T> {
  success: boolean;
  data: T;
  request_id: string;
  meta?: PageMeta;
}

interface ErrorEnvelope {
  success: false;
  error: { code: string; message: string; retryable?: boolean; details?: unknown };
  request_id: string;
}

export interface ApiResult<T> {
  data: T;
  meta?: PageMeta | undefined;
}

function readCookie(name: string): string | null {
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

/**
 * A query parameter before it is sent. Optional parameters can hold `undefined` at run time, which
 * the type `Object.entries` infers for them leaves out, so the filters below name it.
 */
export type QueryValue = string | number | boolean | undefined;

/** Where every route below is served; a link to a route (a download) starts with it too. */
export const API_BASE = "/api/v1";

export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {},
): Promise<ApiResult<T>> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCookie("tralala_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let body: BodyInit | null = null;
  if (options.body instanceof Blob || options.body instanceof ArrayBuffer) {
    body = options.body as BodyInit;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
    credentials: "include",
  });

  if (response.status === 204) {
    return { data: undefined as T };
  }

  const payload = (await response.json().catch(() => null)) as Envelope<T> | ErrorEnvelope | null;

  if (!response.ok || !payload?.success) {
    const error = (payload as ErrorEnvelope | null)?.error;
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent("tralala:unauthorized"));
    }
    throw new ApiError(error?.message ?? `Request failed (${response.status})`, {
      code: error?.code ?? `http_${response.status}`,
      status: response.status,
      retryable: error?.retryable,
      details: error?.details,
      // The envelope names it; the server's X-Request-ID header covers a body that is not JSON.
      requestId: payload?.request_id ?? response.headers.get("X-Request-ID"),
    });
  }

  return { data: payload.data, meta: payload.meta };
}

export const json = <T>(result: ApiResult<T>): T => result.data;
