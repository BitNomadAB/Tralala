import { ApiError } from "@/lib/api";
import { describeError } from "@/lib/describeError";

/**
 * Why QA cannot be accepted while its cycle has no scenarios, and the way to close the Loop
 * without them: the acceptance under 1 takes a person's own word that it was tested.
 */
export const NO_SCENARIOS =
  "This Loop's QA has no scenarios, so there is nothing to accept here. To close the Loop on your own word, choose “Tested and passed outside Tralala” under 1.";

/** What each of the server's reasons means for the scenario it names. */
const REASONS: Readonly<Record<string, string>> = {
  not_run: "no result recorded",
  failed: "failed",
  blocked: "blocked",
  not_applicable_requires_human_approval: "recorded as not applicable; choose its waiver to accept",
  instructions_revised: "its result is from earlier instructions; record it again",
};

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** One of the refusal's blockers as a line: the scenario's id and title, then what is unresolved. */
function line(blocker: Readonly<Record<string, unknown>>, titles: ReadonlyMap<string, string>) {
  const reason = typeof blocker.reason === "string" ? blocker.reason : "";
  if (reason === "instructions_missing") return NO_SCENARIOS;
  const id = typeof blocker.scenario_id === "string" ? blocker.scenario_id : "";
  const title = titles.get(id);
  const name = [id, title].filter(Boolean).join(" ") || "A scenario";
  const detail = typeof blocker.detail === "string" && blocker.detail !== "" ? blocker.detail : "";
  const words = REASONS[reason] ?? reason.replaceAll("_", " ");
  return detail ? `${name}: ${words} (${detail})` : `${name}: ${words}`;
}

/**
 * What a refused QA decision says in the dialog: one line for each thing the server names as
 * unresolved (`409 qa_incomplete` carries them as `details.blockers`), so the person reads which
 * scenario holds the acceptance up and why. Any other refusal is its own message.
 */
export function qaRefusal(error: unknown, titles: ReadonlyMap<string, string>): string[] {
  if (error instanceof ApiError && error.code === "qa_incomplete" && isRecord(error.details)) {
    const blockers: unknown = error.details.blockers;
    const lines = Array.isArray(blockers)
      ? blockers.filter(isRecord).map((blocker) => line(blocker, titles))
      : [];
    if (lines.length > 0) return [...new Set(lines)];
  }
  return [describeError(error)];
}
