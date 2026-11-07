/**
 * Where a Ticket's work is done and what it waits for. Both describe the work and assign nothing:
 * a person owns every Ticket.
 */

/** Where the work is done; `unknown` until someone says, so nothing claims what nobody said. */
export type Workplace = "codebase" | "outside" | "unknown";

/** A wait someone sets: `access` is a system, key, account, setting or machine. */
export type Wait = "decision" | "information" | "access" | "third_party";

export type WaitingFor = "nothing" | Wait;

/**
 * Computed by the server on every read: `needs_input` when a person can answer a wait now,
 * `blocked` by earlier work or a third party, `ready` otherwise. A completed Ticket has none.
 */
export type TicketState = "ready" | "needs_input" | "blocked";
