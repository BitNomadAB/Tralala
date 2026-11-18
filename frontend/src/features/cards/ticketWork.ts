import type { BadgeTone } from "@/components/ui/badge";
import type { TicketState, Wait, Workplace } from "@/lib/types";

/** Why a button cannot be pressed while the change before it is still being saved. */
export const SAVING = "Saving…";

/** Why the head's Mark as waiting cannot be pressed: the Ticket waits already. */
export const ALREADY_WAITS = "It already waits; clear the wait in the rail.";

/** Why an action that is planned but not built yet (Move to another Loop) cannot be pressed. */
export const NOT_YET = "Not available yet";

/** The server's limit on a wait's reason (`WAITING_REASON_CHARS`). */
export const WAITING_REASON_MAX = 500;

export const WORKPLACES: readonly Workplace[] = ["codebase", "outside", "unknown"];

/** Where the work is done, as a person reads it. */
export const WORKPLACE_LABELS: Record<Workplace, string> = {
  codebase: "In the code base",
  outside: "Outside the code base",
  unknown: "Not decided",
};

export const WAITS: readonly Wait[] = ["decision", "information", "access", "third_party"];

/** What a Ticket waits for, as a person reads it. */
export const WAIT_LABELS: Record<Wait, string> = {
  decision: "A decision",
  information: "Information",
  access: "Access",
  third_party: "A third party",
};

/** What each kind of wait covers, shown under the kind while a wait is being set. */
export const WAIT_HINTS: Record<Wait, string> = {
  decision: "Someone has to choose before the work goes on.",
  information: "Something has to be found out or answered.",
  access: "A system, key, account, setting or machine.",
  third_party: "A supplier, a customer, a lawyer or someone else outside the team.",
};

export const STATE_LABELS: Record<TicketState, string> = {
  ready: "Ready",
  needs_input: "Needs input",
  blocked: "Blocked",
};

export const STATE_TONES: Record<TicketState, BadgeTone> = {
  ready: "success",
  needs_input: "warning",
  blocked: "neutral",
};

/** One sentence on what the state means for the person who owns the Ticket. */
export const STATE_HINTS: Record<TicketState, string> = {
  ready: "Nothing holds it up.",
  needs_input: "It waits for an answer a person can give now.",
  blocked: "It waits for earlier work or a third party.",
};
