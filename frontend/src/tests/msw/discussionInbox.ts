import { http } from "msw";
import type { DiscussionInboxRow } from "@/lib/types";
import { apiPath, ok } from "./envelope";

/** An inbox row that waits for a decision on board-1's Ticket; `extra` replaces any field. */
export function inboxRow(id: string, extra: Partial<DiscussionInboxRow> = {}): DiscussionInboxRow {
  return {
    discussion_id: id,
    board_id: "board-1",
    board_name: "Platform",
    loop_id: "loop-1",
    loop_key: "SES-1",
    loop_name: "Session expiry",
    card_id: "card-1",
    ticket_key: "SES-1-PH01-001",
    card_title: "Rotate the signing key",
    question: `Question ${id}?`,
    status: "consensus_proposed",
    run_state: "idle",
    verdict: "yes_with_conditions",
    counts: { go: 3, stop: 0, unclear: 0, missing: 0 },
    participant_count: 3,
    round_count: 2,
    max_rounds: 4,
    asked_by_name: "Ada Member",
    last_activity_at: "2026-11-08T10:00:00Z",
    decided_by_name: null,
    waits_for: "your_decision",
    ...extra,
  };
}

/** `GET /discussions/inbox` answering these rows; `requests` counts the calls. */
export function inboxHandler(rows: DiscussionInboxRow[], total = rows.length) {
  const state = { requests: 0 };
  const handler = http.get(apiPath("/discussions/inbox"), () => {
    state.requests += 1;
    return ok({ items: rows, total });
  });
  return { state, handler };
}
