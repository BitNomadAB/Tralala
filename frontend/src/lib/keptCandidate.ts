import type { GenerationRun } from "@/lib/types";

/** The error code of a run whose answer arrived after the documents it read had changed. */
export const INPUT_CHANGED = "generation_input_changed";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The result a run kept instead of promoting.
 *
 * When the answer arrives the server compares the documents the run read with the documents as they
 * are now; a run that finds them changed fails as `generation_input_changed` and keeps the validated
 * answer under `output.stale_candidate`, so nothing lands on an Info nobody saw it written from.
 */
export function staleCandidate(
  run: Pick<GenerationRun, "status" | "error_code" | "output"> | undefined,
): Record<string, unknown> | null {
  if (run?.status !== "failed" || run.error_code !== INPUT_CHANGED) return null;
  const candidate = run.output.stale_candidate;
  return isRecord(candidate) ? candidate : null;
}

/** The candidate as the technical view shows a generated draft: its JSON in a fenced block. */
export function candidateMarkdown(candidate: Record<string, unknown>): string {
  return "```json\n" + JSON.stringify(candidate, null, 2) + "\n```\n";
}
