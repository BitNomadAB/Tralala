import { describe, expect, it } from "vitest";
import {
  INBOX_GROUPS,
  inboxAside,
  inboxMark,
  inboxMeta,
  inboxPath,
  WAITS_ON_DISCUSSION,
} from "@/features/discussions/discussionRules";
import { formatDate } from "@/lib/utils";
import { inboxRow } from "./msw/discussionInbox";

const WHEN = formatDate("2026-11-08T10:00:00Z");

describe("the inbox's words", () => {
  it("names the three sections in order, each with what it says while empty", () => {
    expect(INBOX_GROUPS.map((group) => [group.waitsFor, group.title, group.empty])).toEqual([
      ["your_decision", "Waits for your decision", "Nothing waits for your decision."],
      ["agents", "Agents are talking", "No agents are talking now."],
      ["nobody", "Decided", "Nothing decided yet."],
    ]);
    expect(WAITS_ON_DISCUSSION).toBe("Waits for your decision on a discussion");
  });

  it("marks a row with its verdict, the round while the agents talk, or No answer yet", () => {
    expect(inboxMark(inboxRow("a"))).toEqual({ word: "Yes, with conditions", tone: "warning" });
    expect(inboxMark(inboxRow("a", { verdict: "no", waits_for: "nobody" }))).toEqual({
      word: "No",
      tone: "danger",
    });
    expect(inboxMark(inboxRow("a", { verdict: null }))).toEqual({
      word: "No answer yet",
      tone: "neutral",
    });
    const talking = inboxRow("a", { waits_for: "agents", run_state: "running", round_count: 1 });
    expect(inboxMark(talking)).toEqual({ word: "Round 2 of 4", tone: "neutral" });
    // The last round never reads past the cap.
    expect(inboxMark({ ...talking, round_count: 4 }).word).toBe("Round 4 of 4");
  });

  it("says at the right when, that the agents answer now, or who decided", () => {
    expect(inboxAside(inboxRow("a"))).toBe(WHEN);
    expect(inboxAside(inboxRow("a", { waits_for: "agents", run_state: "running" }))).toBe(
      "Answering now",
    );
    expect(inboxAside(inboxRow("a", { waits_for: "agents", run_state: "paused" }))).toBe(
      `Paused · ${WHEN}`,
    );
    const decided = { waits_for: "nobody" as const, decided_by_name: "Grace Hopper" };
    expect(inboxAside(inboxRow("a", { ...decided, status: "approved" }))).toBe(
      `Approved by Grace Hopper · ${WHEN}`,
    );
    expect(inboxAside(inboxRow("a", { ...decided, status: "rework_requested" }))).toBe(
      `Rework requested by Grace Hopper · ${WHEN}`,
    );
    expect(inboxAside(inboxRow("a", { waits_for: "nobody", status: "vetoed" }))).toBe(
      `Vetoed · ${WHEN}`,
    );
  });

  it("puts where it belongs, the agents, the sides and the round in the meta line", () => {
    const row = inboxRow("a", { counts: { go: 1, stop: 2, unclear: 1, missing: 1 } });
    expect(inboxMeta(row)).toBe(
      "SES-1-PH01-001 · Session expiry · Platform · 3 agents · 1 for · 2 against · 1 cannot tell · round 2 of 4",
    );
    const bare = inboxRow("a", {
      ticket_key: null,
      loop_name: null,
      participant_count: 1,
      counts: { go: 0, stop: 0, unclear: 0, missing: 1 },
      round_count: 0,
    });
    expect(inboxMeta(bare)).toBe("Platform · 1 agent · no round yet");
  });

  it("leads to the discussion as a page of its Ticket, or to the board without one", () => {
    expect(inboxPath(inboxRow("d 1"))).toBe(
      "/boards/board-1/loops/loop-1/tickets/card-1/discussions/d%201",
    );
    expect(inboxPath(inboxRow("d", { loop_id: null }))).toBe("/boards/board-1");
  });
});
