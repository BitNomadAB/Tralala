import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";

function respondWith(response: Response) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

/** The error a request rejects with, so a test can read every field of it. */
async function failure(): Promise<ApiError> {
  const error = await api.me().then(
    () => null,
    (rejected: unknown) => rejected,
  );
  if (error instanceof ApiError) return error;
  throw new Error("expected the request to fail with an ApiError");
}

describe("ApiError", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("carries the request id the error envelope names", async () => {
    respondWith(
      Response.json(
        {
          success: false,
          error: { code: "not_found", message: "Board not found" },
          request_id: "from-envelope",
        },
        { status: 404, headers: { "X-Request-ID": "from-header" } },
      ),
    );

    const error = await failure();
    expect(error.message).toBe("Board not found");
    expect(error.code).toBe("not_found");
    expect(error.requestId).toBe("from-envelope");
  });

  it("reads the request id from the header when the body is not JSON", async () => {
    respondWith(new Response("Bad gateway", { status: 502, headers: { "X-Request-ID": "hdr-1" } }));

    const error = await failure();
    expect(error.code).toBe("http_502");
    expect(error.requestId).toBe("hdr-1");
  });

  it("has no request id when the response names none", async () => {
    respondWith(new Response("Bad gateway", { status: 502 }));

    expect((await failure()).requestId).toBeNull();
  });
});
