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
 * "decided in a coding session through the key Laptop" for a decision the person took in their
 * editor (`taken_through`, the one key that brought the answer), or null for one taken in Tralala.
 */
export function takenThroughText(changes: Record<string, unknown>): string | null {
  const taken = changes.taken_through;
  if (typeof taken !== "object" || taken === null) return null;
  const name = "key_name" in taken ? taken.key_name : null;
  return `decided in a coding session through the key ${typeof name === "string" && name !== "" ? name : "(unnamed)"}`;
}

/**
 * What a decision's history adds after what was done: where it was decided and who asked, or
 * null for a decision taken in Tralala that nobody asked for.
 */
export function decisionTrail(changes: Record<string, unknown>): string | null {
  const parts = [takenThroughText(changes), askedThroughText(changes)].filter(
    (part): part is string => part !== null,
  );
  return parts.length > 0 ? parts.join(", ") : null;
}

/**
 * Who took a Loop's decision and how, for the Loop page while the Loop is live: "Approved by Ada",
 * "Changes requested by Ada" or "Accepted by Ada" (the implementation), followed by the trail
 * (`decisionTrail`) the documents route reads from the board's rows. Null when there is none.
 */
export function decidedByText(approval: Record<string, unknown> | null | undefined): string | null {
  if (!approval) return null;
  const name =
    typeof approval.reviewer_name === "string" && approval.reviewer_name !== ""
      ? approval.reviewer_name
      : "a person";
  const what =
    approval.scope === "implementation" || approval.scope === "qa"
      ? "Accepted"
      : approval.decision === "changes_requested"
        ? "Changes requested"
        : "Approved";
  const trail = decisionTrail(approval);
  return trail ? `${what} by ${name}, ${trail}` : `${what} by ${name}`;
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
    const asked = decisionTrail(changes);
    if (what && asked) lines.push(`${what}, ${asked}`);
  }
  for (const approval of entries(envelope.approvals)) {
    if (approval.decision !== "approved") continue;
    const what = decisionText(`approval.${String(approval.scope)}`, approval.decision);
    const asked = decisionTrail(fields(approval.revisions));
    if (what && asked) lines.push(`${what}, ${asked}`);
  }
  return lines;
}
