import { http } from "msw";
import { describe, expect, it } from "vitest";
import { api, ApiError } from "@/lib/api";
import { describeError, fieldErrors, TRY_AGAIN } from "@/lib/describeError";
import { apiPath, failure } from "./msw/envelope";
import { server } from "./msw/server";

/** The error creating an agent rejects with when the server answers with `answer`. */
async function refusal(answer: () => ReturnType<typeof failure>): Promise<ApiError> {
  server.use(http.post(apiPath("/agents"), answer));
  const error = await api.createAgent({ name: "Otter" }).then(
    () => null,
    (rejected: unknown) => rejected,
  );
  if (error instanceof ApiError) return error;
  throw new Error("expected the request to fail with an ApiError");
}

describe("describeError", () => {
  it("names the field a refusal gives in details.field", async () => {
    const error = await refusal(() =>
      failure(422, "validation_failed", "Must be at most 8192 for this preset", {
        field: "max_output_tokens",
      }),
    );

    expect(describeError(error)).toBe("max_output_tokens: Must be at most 8192 for this preset");
    expect(fieldErrors(error)).toEqual([
      { field: "max_output_tokens", message: "Must be at most 8192 for this preset" },
    ]);
  });

  it("names what details.missing says is missing", async () => {
    const error = await refusal(() =>
      failure(409, "document_missing", "Approve the Info first", { missing: "info" }),
    );

    expect(describeError(error)).toBe("info: Approve the Info first");
  });

  it("reads the validation handler's pydantic errors, each with its own message", async () => {
    // As `main.validation_handler` writes them: a list of {loc, msg, type}; a `loc` that is only
    // the source names no field.
    const error = await refusal(() =>
      failure(422, "validation_failed", "Request validation failed", [
        { loc: ["body", "max_output_tokens"], msg: "Input should be greater than 0", type: "gt" },
        { loc: ["body", "lists", 0, "name"], msg: "Field required", type: "missing" },
        { loc: ["body"], msg: "Invalid JSON", type: "json_invalid" },
      ]),
    );

    expect(describeError(error)).toBe(
      "max_output_tokens: Input should be greater than 0; lists.0.name: Field required",
    );
  });

  it("reads pydantic errors wrapped in details.errors, and a lone loc with the envelope's message", () => {
    const wrapped = new ApiError("Invalid query", {
      code: "validation_failed",
      status: 422,
      details: { errors: [{ loc: ["query", "limit"], msg: "Input should be a valid integer" }] },
    });
    const lone = new ApiError("Out of range", {
      code: "validation_failed",
      status: 422,
      details: { loc: ["body", "temperature"] },
    });

    expect(describeError(wrapped)).toBe("limit: Input should be a valid integer");
    expect(describeError(lone)).toBe("temperature: Out of range");
  });

  it("reads an error without details, or whose details name no field, as before", async () => {
    const plain = await refusal(() =>
      failure(409, "conflict", "An agent with this name already exists"),
    );
    const unnamed = new ApiError("An agent with this name already exists", {
      code: "conflict",
      status: 409,
      details: { name: "Otter" },
    });

    expect(describeError(plain)).toBe("An agent with this name already exists");
    expect(describeError(plain, undefined)).toBe("An agent with this name already exists");
    expect(describeError(unnamed)).toBe("An agent with this name already exists");
    expect(fieldErrors(plain)).toEqual([]);
  });

  it("falls back for an error that is not the API's", () => {
    const offline = new TypeError("Failed to fetch");

    expect(describeError(offline)).toBe(TRY_AGAIN);
    expect(describeError(offline, "Agent unavailable.")).toBe("Agent unavailable.");
    expect(describeError(offline, undefined)).toBeUndefined();
    expect(fieldErrors(offline)).toEqual([]);
  });
});
