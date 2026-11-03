import { HttpResponse } from "msw";
import type { PageMeta } from "@/lib/types";

/** The request id every answer below carries, in the envelope and in the `X-Request-ID` header. */
export const REQUEST_ID = "req-test";

/** A handler path as the client sends it: `apiPath("/auth/me")` is `/api/v1/auth/me`. */
export const apiPath = (path: string): string => `/api/v1${path}`;

/** The API path of an intercepted request without the base and the query, e.g. "/boards". */
export function requestPath(request: Request): string {
  return new URL(request.url).pathname.replace(/^\/api\/v1/, "");
}

interface SuccessEnvelope {
  success: true;
  data: unknown;
  request_id: string;
  meta?: PageMeta;
}

interface ErrorEnvelope {
  success: false;
  error: { code: string; message: string; retryable: boolean };
  request_id: string;
}

/** A success as the backend writes it (`core/responses.envelope`): `meta` only on a paged list. */
export function ok(data: unknown, meta?: PageMeta) {
  const body: SuccessEnvelope = {
    success: true,
    data,
    request_id: REQUEST_ID,
    ...(meta ? { meta } : {}),
  };
  return HttpResponse.json(body, { headers: { "X-Request-ID": REQUEST_ID } });
}

/** An error as the backend's handlers write it; a 401 also names the scheme, as the server does. */
export function failure(status: number, code: string, message: string) {
  const body: ErrorEnvelope = {
    success: false,
    error: { code, message, retryable: false },
    request_id: REQUEST_ID,
  };
  const headers: Record<string, string> = { "X-Request-ID": REQUEST_ID };
  if (status === 401) headers["WWW-Authenticate"] = "Bearer";
  return HttpResponse.json(body, { status, headers });
}
