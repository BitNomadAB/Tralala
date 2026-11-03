import { ApiError } from "./api";

/** What a failed request reads as when the error did not come from the API. */
export const TRY_AGAIN = "Please try again.";

/** One request field the server named in a refusal, with what it said about it. */
export interface FieldError {
  /** The field as the request spells it, e.g. `max_output_tokens` or `lists.0.name`. */
  field: string;
  message: string;
}

/** Where FastAPI says a value came from: the first part of a `loc`, not part of the field. */
const SOURCES: ReadonlySet<string> = new Set(["body", "query", "path", "header", "cookie"]);

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isList(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

/** A `details.field` or `details.missing`: one name, or several read as one. */
function named(value: unknown): string | null {
  if (isText(value)) return value;
  if (!isList(value)) return null;
  const names = value.filter(isText);
  return names.length > 0 ? names.join(", ") : null;
}

/** The field of a pydantic `loc` (`["body", "max_output_tokens"]`), without its source. */
function locField(loc: unknown): string | null {
  if (!isList(loc)) return null;
  const parts = loc
    .filter((part): part is string | number => typeof part === "string" || typeof part === "number")
    .map(String);
  const [first, ...rest] = parts;
  const path = first !== undefined && SOURCES.has(first) ? rest : parts;
  return path.length > 0 ? path.join(".") : null;
}

/** One pydantic error entry (`{loc, msg}`); its own `msg` is more precise than the envelope's. */
function locError(entry: unknown, message: string): FieldError | null {
  if (!isRecord(entry)) return null;
  const field = locField(entry.loc);
  if (field === null) return null;
  return { field, message: isText(entry.msg) ? entry.msg : message };
}

function locErrors(entries: readonly unknown[], message: string): FieldError[] {
  return entries.flatMap((entry) => {
    const found = locError(entry, message);
    return found ? [found] : [];
  });
}

/**
 * The fields an API error names: `details.field`, `details.missing`, or the `loc` of each pydantic
 * error (the 422 `validation_failed` envelope carries a list of them, a service may wrap them in
 * `details.errors`). Empty for an error that names none, or that is not the API's.
 */
export function fieldErrors(error: unknown): FieldError[] {
  if (!(error instanceof ApiError)) return [];
  const { details, message } = error;
  if (isList(details)) return locErrors(details, message);
  if (!isRecord(details)) return [];
  const field = named(details.field) ?? named(details.missing);
  if (field !== null) return [{ field, message }];
  if (isList(details.errors)) return locErrors(details.errors, message);
  const single = locError(details, message);
  return single ? [single] : [];
}

/**
 * How a failed request reads in a toast or beside a form: `"<field>: <message>"` for each field the
 * error names, else the API's message, else `fallback`. Pass `undefined` as the fallback where an
 * error that is not the API's should leave the description out.
 */
export function describeError(error: unknown, fallback: undefined): string | undefined;
export function describeError(error: unknown, fallback?: string): string;
export function describeError(
  error: unknown,
  ...fallback: [fallback?: string | undefined]
): string | undefined {
  const fields = fieldErrors(error);
  if (fields.length > 0) {
    return fields.map(({ field, message }) => `${field}: ${message}`).join("; ");
  }
  if (error instanceof ApiError) return error.message;
  // Not a default parameter: that would also replace an explicit `undefined`, which means "none".
  return fallback.length > 0 ? fallback[0] : TRY_AGAIN;
}
