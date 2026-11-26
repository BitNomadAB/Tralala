import { describe, expect, it } from "vitest";
import {
  boardDiscussionMark,
  boardDiscussionMeta,
  newDiscussionRequest,
  newestFirst,
  noBoardDiscussion,
} from "@/features/discussions/boardDiscussionRules";
import { boardThread } from "./msw/boardDiscussions";

describe("the words of the board's discussions", () => {
  it("marks a row Closed, by the agents' state or verdict, Open for people only, else No answer yet", () => {
    expect(boardDiscussionMark(boardThread({ status: "closed" })).word).toBe("Closed");
    expect(boardDiscussionMark(boardThread({ run_state: "running" })).word).toBe(
      "Agents are answering",
    );
    expect(boardDiscussionMark(boardThread()).word).toBe("Yes, with conditions");
    const asked = { synthesis: null, participant_count: 2 };
    expect(boardDiscussionMark(boardThread(asked)).word).toBe("No answer yet");
    expect(boardDiscussionMark(boardThread({ ...asked, participant_count: 0 })).word).toBe("Open");
  });

  it("says who asked, how many agents and messages, and what an empty filter holds", () => {
    expect(boardDiscussionMeta(boardThread({ participant_count: 1, message_count: 1 }))).toBe(
      "Asked by Ada Member · 1 agent · 1 message",
    );
    expect(boardDiscussionMeta(boardThread({ participant_count: 0, message_count: 3 }))).toBe(
      "Asked by Ada Member · no agents · 3 messages",
    );
    expect(noBoardDiscussion("open", false)).toBe(
      "No open discussion on this board. Start one with New discussion.",
    );
    expect(noBoardDiscussion("open", true)).toBe("No open discussion on this board.");
    expect(noBoardDiscussion("closed", false)).toBe("No closed discussion on this board.");
  });

  it("lists the newest activity first", () => {
    const old = boardThread({ id: "a", last_activity_at: "2026-11-08T10:00:00Z" });
    const recent = boardThread({ id: "b", last_activity_at: "2026-11-08T11:00:00Z" });
    expect(newestFirst([old, recent]).map((thread) => thread.id)).toEqual(["b", "a"]);
  });

  it("asks the chosen agents in a roundtable, or nobody in particular without them", () => {
    expect(newDiscussionRequest(" Export ", " Where? ", ["agent-1"])).toEqual({
      title: "Export",
      goal: "Where?",
      mode: "roundtable",
      participant_ids: ["agent-1"],
    });
    expect(newDiscussionRequest("Export", "Where?", [])).toEqual({
      title: "Export",
      goal: "Where?",
      mode: "manual",
      participant_ids: [],
    });
  });
});
