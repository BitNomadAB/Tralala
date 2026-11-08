import { describe, expect, it } from "vitest";
import {
  ASK_NOT_STARTED,
  ASK_SENTENCE,
  askBlocked,
  askRequest,
  askTitle,
  discussionWaitsFor,
  MOST_ASKED,
  NO_ASKABLE_AGENT,
  noTicketDiscussion,
  ticketDiscussionAside,
  ticketDiscussionMark,
  ticketDiscussionMeta,
  ticketDiscussionPath,
  ticketDiscussionsInOrder,
} from "@/features/discussions/inboxRules";
import { formatDate } from "@/lib/utils";
import { discussion } from "./msw/discussions";
import { MEMBER } from "./msw/session";
import { ticketThread } from "./msw/ticketDiscussions";

const ASKED = formatDate(discussion().created_at);

describe("who a Ticket's discussion waits for", () => {
  it.each([
    [{ run_state: "running" }, "agents"],
    [{ run_state: "paused" }, "agents"],
    [{ status: "approved" }, "nobody"],
    [{ status: "vetoed" }, "nobody"],
    [{ status: "rework_requested" }, "nobody"],
    [{ status: "cancelled" }, "nobody"],
    [{ status: "discussing" }, "your_decision"],
    [{ status: "open", round_count: 0, synthesis: null }, "your_decision"],
  ] as const)("%o waits for %s", (extra, waits) => {
    expect(discussionWaitsFor(discussion(extra))).toBe(waits);
  });

  it("lists decisions first, then the agents talking, then the decided, newest activity first", () => {
    const ordered = ticketDiscussionsInOrder([
      ticketThread("decided-new", 50, null, { status: "approved" }),
      ticketThread("decided-old", 5, null, { status: "vetoed" }),
      ticketThread("wait-old", 10, null),
      ticketThread("talk", 40, null, { run_state: "paused" }),
      ticketThread("wait-new", 30, null),
    ]);
    expect(ordered.map((thread) => thread.id)).toEqual([
      "wait-new",
      "wait-old",
      "talk",
      "decided-new",
      "decided-old",
    ]);
  });
});

describe("a row of the Ticket's Discussions tab", () => {
  it("marks the state while the agents answer, else the verdict, else No answer yet", () => {
    expect(ticketDiscussionMark(discussion({ run_state: "running" }))).toEqual({
      word: "Agents are answering",
      tone: "neutral",
    });
    expect(ticketDiscussionMark(discussion({ run_state: "paused" }))).toEqual({
      word: "Paused",
      tone: "neutral",
    });
    expect(ticketDiscussionMark(discussion())).toEqual({
      word: "Yes, with conditions",
      tone: "warning",
    });
    expect(ticketDiscussionMark(discussion({ synthesis: null }))).toEqual({
      word: "No answer yet",
      tone: "neutral",
    });
  });

  it.each([
    [{}, "Waits for your decision"],
    [{ run_state: "running" }, "Waits for the agents"],
    [{ run_state: "paused" }, "Waits for you to resume"],
    [{ status: "vetoed", decided_by_name: "Mike" }, "Vetoed by Mike"],
    [{ status: "approved", decided_by_name: null }, "Approved"],
    [{ status: "rework_requested", decided_by_name: "Grace" }, "Rework requested by Grace"],
    [{ status: "cancelled" }, "Cancelled"],
  ] as const)("with %o says %s at the right", (extra, aside) => {
    expect(ticketDiscussionAside(discussion(extra))).toBe(aside);
  });

  it("counts the agents and the sides taken, the round, who asked and when", () => {
    expect(ticketDiscussionMeta(ticketThread("a", 1, { go: 3, stop: 1 }))).toBe(
      `4 agents · 3 for · 1 against · round 2 of 4 · asked by ${MEMBER.name} · ${ASKED}`,
    );
    // A side nobody took is left out; who cannot tell is counted.
    expect(ticketDiscussionMeta(discussion({ participant_count: 1 }))).toBe(
      `1 agent · 1 cannot tell · round 2 of 4 · asked by ${MEMBER.name} · ${ASKED}`,
    );
    expect(ticketDiscussionMeta(discussion({ round_count: 0, synthesis: null }))).toBe(
      `4 agents · no round yet · asked by ${MEMBER.name} · ${ASKED}`,
    );
  });

  it("leads to the Ticket's dialog over the Kanban, or to the discussion's page", () => {
    expect(ticketDiscussionPath("modal", "b 1", "l1", "c1", "d1")).toBe(
      "/boards/b%201/loops/l1?card=c1&discussion=d1",
    );
    expect(ticketDiscussionPath("page", "b1", "l1", "c1", "d1")).toBe(
      "/boards/b1/loops/l1/tickets/c1/discussions/d1",
    );
  });

  it("says when the Ticket has none, shorter on a read-only Ticket", () => {
    expect(noTicketDiscussion(false)).toBe("No discussion yet. Ask the agents what they think.");
    expect(noTicketDiscussion(true)).toBe("No discussion yet.");
  });
});

describe("asking the agents", () => {
  it("says what happens and what the person sees when something goes wrong", () => {
    expect(ASK_SENTENCE).toBe(
      "Ask one thing. The agents you choose answer in one round, and you decide what follows.",
    );
    expect(NO_ASKABLE_AGENT).toBe(
      "No agent can answer on this board. Add one in Settings → Agents and select it on the board.",
    );
    expect(ASK_NOT_STARTED).toBe("The agents could not start answering");
  });

  it.each([
    ["Why?", 1, 0, NO_ASKABLE_AGENT],
    ["   ", 1, 2, "Write the question first"],
    ["Why?", 0, 2, "Choose at least one agent"],
    ["Why?", MOST_ASKED + 1, 20, "Choose at most 12 agents"],
    ["Why?", MOST_ASKED, 20, null],
    ["Why?", 1, 1, null],
  ] as const)("%j with %i of %i agents chosen: %s", (question, chosen, agents, reason) => {
    expect(askBlocked(question, chosen, agents)).toBe(reason);
  });

  it("titles the thread with the question's first 80 characters, on one line", () => {
    expect(askTitle("  Should we\n  rotate it?  ")).toBe("Should we rotate it?");
    const long = "word ".repeat(30);
    const title = askTitle(long);
    expect(title).toHaveLength(80);
    expect(title.endsWith("…")).toBe(true);
    expect(askTitle("x".repeat(80))).toBe("x".repeat(80));
  });

  it("creates a roundtable on the Ticket with the chosen agents and the default round cap", () => {
    expect(askRequest("c1", "  Rotate it?  ", ["a1", "a2"])).toEqual({
      card_id: "c1",
      title: "Rotate it?",
      goal: "Rotate it?",
      mode: "roundtable",
      participant_ids: ["a1", "a2"],
    });
  });
});
