import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { apiPath, failure, ok, REQUEST_ID } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";

/** The error a call rejects with, so a test can read every field of it. */
async function failureOf(call: () => Promise<unknown>): Promise<ApiError> {
  const error = await call().then(
    () => null,
    (rejected: unknown) => rejected,
  );
  if (error instanceof ApiError) return error;
  throw new Error("expected the request to fail with an ApiError");
}

describe("request", () => {
  afterEach(() => {
    document.cookie = "tralala_csrf=; max-age=0";
  });

  it("unwraps the envelope and keeps the page meta of a list", async () => {
    const page = { total: 3, limit: 1, offset: 0, has_more: true };
    server.use(http.get(apiPath("/boards"), () => ok([{ id: "board-1", name: "Roadmap" }], page)));

    const result = await api.listBoards({ limit: 1 });

    expect(result.items).toEqual([{ id: "board-1", name: "Roadmap" }]);
    expect(result.meta).toEqual(page);
  });

  it("sends a body as JSON with the CSRF cookie as header, and a read without either", async () => {
    document.cookie = "tralala_csrf=csrf-cookie-1";
    const sent: { method: string; type: string | null; csrf: string | null; body: unknown }[] = [];
    const record = async (request: Request) => {
      const body: unknown = request.body ? await request.json() : null;
      const type = request.headers.get("Content-Type");
      sent.push({ method: request.method, type, csrf: request.headers.get("X-CSRF-Token"), body });
    };
    server.use(
      http.post(apiPath("/auth/login"), async ({ request }) => {
        await record(request);
        return ok({ actor: MEMBER, csrf_token: "csrf-next" });
      }),
      http.get(apiPath("/auth/me"), async ({ request }) => {
        await record(request);
        return ok(MEMBER);
      }),
    );

    expect(await api.login("ada", "a password, with ünïcode")).toEqual(MEMBER);
    expect(await api.me()).toEqual(MEMBER);

    expect(sent).toEqual([
      {
        method: "POST",
        type: "application/json",
        csrf: "csrf-cookie-1",
        body: { username: "ada", password: "a password, with ünïcode" },
      },
      { method: "GET", type: null, csrf: null, body: null },
    ]);
  });

  it("trusts the envelope, not only the status: a 200 that reports a failure rejects", async () => {
    server.use(
      http.get(apiPath("/auth/me"), () =>
        HttpResponse.json({
          success: false,
          error: { code: "conflict", message: "Changed elsewhere", retryable: true },
          request_id: REQUEST_ID,
        }),
      ),
    );

    const error = await failureOf(() => api.me());
    expect(error).toMatchObject({ code: "conflict", status: 200, retryable: true });
    expect(error.message).toBe("Changed elsewhere");
  });

  it("tells the app about a 401, and only about a 401", async () => {
    const heard = vi.fn();
    window.addEventListener("tralala:unauthorized", heard);
    server.use(
      http.get(apiPath("/auth/me"), () => failure(401, "unauthorized", "Authentication required")),
      http.get(apiPath("/meta"), () => failure(403, "forbidden", "Not allowed")),
    );

    try {
      expect(await failureOf(() => api.me())).toMatchObject({ status: 401, code: "unauthorized" });
      expect(heard).toHaveBeenCalledTimes(1);
      expect(await failureOf(() => api.meta())).toMatchObject({ status: 403, code: "forbidden" });
      expect(heard).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("tralala:unauthorized", heard);
    }
  });
});

describe("ApiError", () => {
  it("carries the request id the error envelope names", async () => {
    server.use(
      http.get(apiPath("/auth/me"), () =>
        HttpResponse.json(
          {
            success: false,
            error: { code: "not_found", message: "Board not found" },
            request_id: "from-envelope",
          },
          { status: 404, headers: { "X-Request-ID": "from-header" } },
        ),
      ),
    );

    const error = await failureOf(() => api.me());
    expect(error.message).toBe("Board not found");
    expect(error.code).toBe("not_found");
    expect(error.requestId).toBe("from-envelope");
  });

  it("reads the request id from the header when the body is not JSON", async () => {
    server.use(
      http.get(
        apiPath("/auth/me"),
        () =>
          new HttpResponse("Bad gateway", { status: 502, headers: { "X-Request-ID": "hdr-1" } }),
      ),
    );

    const error = await failureOf(() => api.me());
    expect(error.code).toBe("http_502");
    expect(error.requestId).toBe("hdr-1");
  });

  it("has no request id when the response names none", async () => {
    server.use(
      http.get(apiPath("/auth/me"), () => new HttpResponse("Bad gateway", { status: 502 })),
    );

    expect((await failureOf(() => api.me())).requestId).toBeNull();
  });
});
