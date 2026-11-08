import { http } from "msw";
import type { AskableAgent, Discussion, DiscussionPosition, DiscussionStance } from "@/lib/types";
import { CARD_ID } from "./cards";
import { after, discussion, type DiscussionApiState } from "./discussions";
import { apiPath, ok } from "./envelope";
import { BOARD_ID } from "./loops";

/** The agents the board may ask: two with a role, one without. */
export const ASKABLE: AskableAgent[] = [
  { id: "agent-Alpha", name: "Alpha", role_template_name: "Product Owner" },
  { id: "agent-Bravo", name: "Bravo", role_template_name: "Backend Developer" },
  { id: "agent-Charlie", name: "Charlie", role_template_name: null },
];

function stance(name: string, position: DiscussionPosition): DiscussionStance {
  return {
    participant_id: `agent-${name}`,
    participant: name,
    position,
    recommendation: "Keep it short.",
    confidence: null,
    format: "structured",
    message_id: `m-${name}`,
    round_number: 1,
  };
}

/**
 * One of the Ticket's threads, in the shape the list or the detail answers: the fixture's thread
 * under `id`, last active at `minute`, with `go` agents for and `stop` against after its newest
 * round (no synthesis when both are null), and `extra` on top.
 */
export function ticketThread(
  id: string,
  minute: number,
  sides: { go: number; stop: number } | null,
  extra: Partial<Discussion> = {},
): Discussion {
  const base = discussion();
  const at = `2026-11-08T11:${String(minute).padStart(2, "0")}:00Z`;
  const synthesis =
    sides === null || !base.synthesis
      ? null
      : {
          ...base.synthesis,
          go: Array.from({ length: sides.go }, (_, index) => stance(`Go${String(index)}`, "yes")),
          stop: Array.from({ length: sides.stop }, (_, index) =>
            stance(`No${String(index)}`, "no"),
          ),
          unclear: [],
        };
  return {
    ...base,
    id,
    goal: `Question ${id}?`,
    last_activity_at: at,
    updated_at: at,
    synthesis,
    ...extra,
  };
}

/** A thread just asked from the Ticket: no round yet, three rounds at most, nobody answering. */
export function askedThread(extra: Partial<Discussion> = {}): Discussion {
  return {
    ...discussion(),
    mode: "roundtable",
    status: "open",
    run_state: "idle",
    round_count: 0,
    max_rounds: 3,
    participant_count: 3,
    messages: [],
    runs: [],
    active_run: null,
    synthesis: null,
    positions: [],
    ...extra,
  };
}

/** `POST /boards/{id}/discussions`: the body lands in `state.bodies` as "create". */
export function createHandler(state: DiscussionApiState) {
  return http.post(apiPath(`/boards/${BOARD_ID}/discussions`), async ({ request }) => {
    const body: unknown = await request.json();
    state.bodies.push({ route: "create", body, csrf: request.headers.get("X-CSRF-Token") });
    return ok({ ...after(state, "create"), card_id: CARD_ID });
  });
}
