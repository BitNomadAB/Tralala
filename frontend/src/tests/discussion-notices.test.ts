import { describe, expect, it } from "vitest";
import {
  discussionNotices,
  endedNotice,
  liveState,
  REPLY_SENT,
  talkStartedNotice,
  type LiveState,
} from "@/features/discussions/discussionNotices";
import { runView } from "@/features/discussions/runEvents";
import type { Discussion, DiscussionEvent } from "@/lib/types";
import { ended, event, RUN_ID, talkEvents, talking, talkRun } from "./msw/discussionRuns";
import { discussion } from "./msw/discussions";
import { MEMBER } from "./msw/session";

function look(thread: Discussion, events: DiscussionEvent[] = []): LiveState {
  return liveState(thread, runView(thread, events));
}

/** What is said going from the first look to the second. */
function said(before: LiveState, after: LiveState): string[] {
  return discussionNotices(before, after);
}

const ANSWERING = "Agents are answering, round 3 of 4";

describe("what a screen reader is told as the agents answer", () => {
  it("says nothing on the first look, for another discussion, or when nothing changed", () => {
    const now = look(talking(), talkEvents());
    expect(discussionNotices(null, now)).toEqual([]);
    expect(said({ ...now, discussionId: "another" }, now)).toEqual([]);
    expect(said(now, look(talking(), talkEvents()))).toEqual([]);
  });

  it("says the round has started when the agents start answering", () => {
    expect(said(look(discussion()), look(talking()))).toEqual([ANSWERING]);
  });

  it("says when the next round starts, and not again for a run that goes on after a pause", () => {
    const third = look(talking());
    const fourth = look({ ...talking(), round_count: 3 });
    expect(said(third, fourth)).toEqual(["Agents are answering, round 4 of 4"]);
    expect(said(third, look(talking("paused")))).toEqual([]);
    expect(said(look(talking("paused")), third)).toEqual([]);
  });

  it("counts the agents that have answered the round, once more of them have", () => {
    const start = [event(1, "run_started", { run_id: RUN_ID }, MEMBER.name)];
    const none = look(talking(), start);
    const alpha = event(3, "agent_completed", { participant_id: "agent-Alpha", round_number: 1 });
    const one = look(talking(), [...start, alpha]);
    expect(said(none, one)).toEqual(["1 of 4 agents have answered this round"]);
    const bravo = event(4, "agent_completed", { participant_id: "agent-Bravo", round_number: 1 });
    expect(said(one, look(talking(), [...start, alpha, bravo]))).toEqual([
      "2 of 4 agents have answered this round",
    ]);
    // Fewer, as when a new round's events come in, is no news.
    expect(said(one, none)).toEqual([]);
  });

  it("names an agent that could not be reached, once", () => {
    const events = talkEvents();
    const before = look(talking(), events.slice(0, 4));
    const after = look(talking(), events);
    expect(said(before, after)).toEqual(["No answer from Bravo: the agent could not be reached."]);
    expect(said(after, look(talking(), events))).toEqual([]);
  });

  it("tells how the run ended and where that leaves the discussion", () => {
    const failed = ended({ status: "failed", stop_reason: "all_participants_failed" });
    expect(said(look(talking()), look(failed))).toEqual([
      "No agent could be reached. Tralala's suggestion after round 2: Yes, with conditions.",
    ]);
    const agreed = ended({ status: "completed", stop_reason: "consensus" });
    expect(said(look(talking("paused")), look(agreed))).toEqual([
      "The agents agree. Tralala's suggestion after round 2: Yes, with conditions.",
    ]);
  });

  it("tells the end of a run too short to be seen running", () => {
    const asked = { ...discussion(), runs: [talkRun({ status: "completed", autonomy: false })] };
    expect(said(look(discussion()), look(asked))).toEqual([
      "The agents have answered. Tralala's suggestion after round 2: Yes, with conditions.",
    ]);
  });

  it("words the end from the run and the suggestion", () => {
    const stopped = talkRun({ status: "stopped" });
    expect(endedNotice(discussion(), stopped, MEMBER.name)).toBe(
      "Stopped by Ada Member. Tralala's suggestion after round 2: Yes, with conditions.",
    );
    expect(endedNotice(discussion({ synthesis: null }), null, null)).toBe(
      "The agents have answered.",
    );
  });

  it("confirms a reply and a talk that started", () => {
    expect(REPLY_SENT).toBe("Reply sent");
    expect(talkStartedNotice(2)).toBe(
      "Talk started: the agents answer each other for up to 2 rounds.",
    );
    expect(talkStartedNotice(1)).toContain("for up to 1 round.");
  });
});
