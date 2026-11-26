/**
 * A decision that answered a question a coding session asked its person carries `asked_through`
 * in its history: one entry per key that asked (`decision_requests.py`). These are the words the
 * Ticket's history and the board's history page say about it.
 */

interface AskedKey {
  key_name: string | null;
}

function askedKeys(value: unknown): AskedKey[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown) => {
    if (typeof item !== "object" || item === null) return [];
    const name = "key_name" in item ? item.key_name : null;
    return [{ key_name: typeof name === "string" && name !== "" ? name : null }];
  });
}

/** "the key Laptop", "the keys Laptop and Desktop", "the keys A, B and C". */
export function keysText(names: readonly string[]): string {
  if (names.length === 1) return `the key ${names[0] ?? ""}`;
  return `the keys ${names.slice(0, -1).join(", ")} and ${names[names.length - 1] ?? ""}`;
}

/**
 * "asked from a coding session through the key Laptop" for the changes of a decision that
 * answered a question, or null for one nobody asked for.
 */
export function askedThroughText(changes: Record<string, unknown>): string | null {
  const keys = askedKeys(changes.asked_through);
  if (keys.length === 0) return null;
  const names = keys.map((key) => key.key_name ?? "(unnamed)");
  return `asked from a coding session through ${keysText(names)}`;
}

/**
 * The decisions of a completed Loop that answered a question a coding session asked its person,
 * read from the record's snapshot: the history rows of the reviews, the Ticket decisions and a
 * rejected QA, and the decision rows of the implementation and an accepted QA, which carry the
 * keys themselves. A decision nobody asked for is not listed here.
 */

interface SnapshotEntry {
  action?: unknown;
  scope?: unknown;
  decision?: unknown;
  changes?: unknown;
  revisions?: unknown;
}

/** What a decision in the snapshot was, in words. */
function decisionText(action: string, decision: unknown): string | null {
  const reviewed = decision === "changes_requested" ? "Changes were requested to" : "Approved";
  switch (action) {
    case "loop.analysis_reviewed":
      return `${reviewed} the analysis`;
    case "loop.roadmap_reviewed":
      return `${reviewed} the RoadMap`;
    case "loop.qa_rejected":
      return "Rejected QA";
    case "card.wait_cleared":
      return "Cleared a wait";
    case "card.human_confirmed":
      return "Confirmed a person's task";
    case "approval.implementation":
      return "Accepted the implementation";
    case "approval.qa":
      return "Accepted QA";
    default:
      return null;
  }
}

function fields(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function entries(value: unknown): SnapshotEntry[] {
  return Array.isArray(value) ? value.map((item: unknown) => fields(item)) : [];
}

/** One sentence per decision that answered a coding session's question, oldest first. */
export function askedDecisions(envelope: Record<string, unknown>): string[] {
  const lines: string[] = [];
  for (const entry of entries(envelope.activity)) {
    const changes = fields(entry.changes);
    const what = decisionText(String(entry.action), changes.decision);
    const asked = askedThroughText(changes);
    if (what && asked) lines.push(`${what}, ${asked}`);
  }
  for (const approval of entries(envelope.approvals)) {
    if (approval.decision !== "approved") continue;
    const what = decisionText(`approval.${String(approval.scope)}`, approval.decision);
    const asked = askedThroughText(fields(approval.revisions));
    if (what && asked) lines.push(`${what}, ${asked}`);
  }
  return lines;
}
