import { describe, expect, it } from "vitest";
import { runText } from "@/features/discussions/discussionData";
import {
  controlledText,
  failedLine,
  isTalking,
  outcomeLine,
  outcomeWords,
  progressLine,
  replyNeedsRound,
  roundsLeft,
  runControls,
  stateOf,
  talkBlocked,
  talkRequest,
  talkRounds,
  talkSentence,
} from "@/features/discussions/discussionRules";
import { eventsByRun, runView } from "@/features/discussions/runEvents";
import { ended, event, RUN_ID, talkEvents, talking, talkRun } from "./msw/discussionRuns";
import { discussion } from "./msw/discussions";
import { MEMBER } from "./msw/session";

const run = talkRun;

describe("the outcome words", () => {
  it("says no agent could be reached when every agent failed", () => {
    const failed = run({ status: "failed", stop_reason: "all_participants_failed" });
    expect(outcomeWords(failed)).toBe("No agent could be reached");
  });

  it("says the budget ran out, for tokens and for time", () => {
    expect(outcomeWords(run({ status: "budget_exhausted", stop_reason: "token_budget" }))).toBe(
      "The budget ran out",
    );
    expect(outcomeWords(run({ status: "budget_exhausted", stop_reason: "time_budget" }))).toBe(
      "The budget ran out",
    );
  });

  it("says the agents repeated themselves", () => {
    expect(outcomeWords(run({ status: "no_progress", stop_reason: "duplicate_answers" }))).toBe(
      "The agents repeated themselves, so the run stopped",
    );
  });

  it("says the agents agree", () => {
    expect(outcomeWords(run({ status: "completed", stop_reason: "consensus" }))).toBe(
      "The agents agree",
    );
  });

  it("says stopped, by whom when it is known", () => {
    const stopped = run({ status: "stopped", stop_reason: "human_stop" });
    expect(outcomeWords(stopped)).toBe("Stopped");
    expect(outcomeWords(stopped, "Ada Member")).toBe("Stopped by Ada Member");
  });

  it("says the rounds were used up", () => {
    expect(outcomeWords(run({ status: "completed", stop_reason: "rounds_completed" }))).toBe(
      "Rounds used up",
    );
  });

  it("says a run broke off, and says nothing while it runs", () => {
    expect(outcomeWords(run({ status: "failed", stop_reason: "error" }))).toBe(
      "The run broke off with an error",
    );
    expect(outcomeWords(run({ status: "failed", stop_reason: "process_restart" }))).toBe(
      "The run broke off when the server restarted",
    );
    expect(outcomeWords(run({ status: "paused", stop_reason: "paused_by_user" }))).toBe("Paused");
    expect(outcomeWords(run({ status: "something_new" }))).toBe("The run ended");
    expect(outcomeWords(run())).toBeNull();
  });

  it("puts a line under the sign only when there is something to tell", () => {
    expect(outcomeLine(null, null)).toBeNull();
    expect(outcomeLine(run(), null)).toBeNull();
    expect(outcomeLine(run({ status: "completed", stop_reason: "consensus" }), null)).toBeNull();
    const asked = run({ status: "completed", stop_reason: "rounds_completed", autonomy: false });
    expect(outcomeLine(asked, null)).toBeNull();
    const talked = run({ status: "completed", stop_reason: "rounds_completed" });
    expect(outcomeLine(talked, null)).toBe("Rounds used up");
    const failed = run({
      status: "failed",
      stop_reason: "all_participants_failed",
      autonomy: false,
    });
    expect(outcomeLine(failed, null)).toBe("No agent could be reached");
    expect(outcomeLine(run({ status: "stopped" }), "Ada Member")).toBe("Stopped by Ada Member");
  });

  it("names an agent that could not be reached", () => {
    expect(failedLine("Bravo")).toBe("No answer from Bravo: the agent could not be reached.");
  });

  it("tells the progress of a round", () => {
    expect(progressLine(2, 3)).toBe("2 of 3 agents have answered this round");
    expect(progressLine(0, 1)).toBe("0 of 1 agent has answered this round");
  });

  it("confirms Pause, Resume and Stop", () => {
    expect(controlledText("pause")).toBe("The run is paused");
    expect(controlledText("resume")).toBe("The agents go on");
    expect(controlledText("stop")).toBe("The run is stopped");
  });
});

describe("the state while the agents talk", () => {
  it("says which round they answer, or that they paused", () => {
    expect(stateOf(talking())).toMatchObject({
      word: "Agents are answering",
      reason: "round 3 of 4",
    });
    expect(stateOf(talking("paused")).word).toBe("Paused");
    expect(stateOf(ended({ status: "stopped" }), { stoppedBy: "Ada Member" }).word).toBe(
      "Stopped by Ada Member",
    );
  });

  it("offers Pause while they answer, Resume while paused, and Stop in the rail", () => {
    expect(isTalking(talking())).toBe(true);
    expect(isTalking(talking("paused"))).toBe(true);
    expect(isTalking(discussion())).toBe(false);
    expect(runControls(talking()).map((item) => item.label)).toEqual(["Pause while they talk"]);
    expect(runControls(talking("paused"), true).map((item) => item.label)).toEqual([
      "Resume",
      "Stop the run",
    ]);
    expect(runControls(discussion(), true)).toEqual([]);
  });
});

describe("Let them talk it out", () => {
  it("offers the rounds left, at most four", () => {
    expect(roundsLeft(discussion())).toBe(2);
    expect(talkRounds(discussion())).toBe(2);
    expect(talkRounds(discussion({ max_rounds: 9, round_count: 1 }))).toBe(4);
    expect(roundsLeft(discussion({ round_count: 6 }))).toBe(0);
  });

  it("says what happens in one sentence", () => {
    expect(talkSentence(2)).toBe(
      "The agents answer each other for up to 2 rounds and stop when they agree or when the budget is spent.",
    );
    expect(talkSentence(1)).toContain("for up to 1 round and stop");
  });

  it("is blocked with the reason when no round is left or the discussion is decided", () => {
    expect(talkBlocked(discussion())).toBeNull();
    expect(talkBlocked(discussion({ round_count: 4 }))).toBe(
      "No round is left: the discussion has had all 4",
    );
    expect(talkBlocked(discussion({ status: "approved" }))).toBe("The discussion is decided");
    expect(talkBlocked(discussion({ status: "cancelled" }))).toBe("The discussion was cancelled");
    expect(talkBlocked(talking())).toBe("The agents are already answering");
  });

  it("sends the rounds, and a budget only where one was given", () => {
    const blank = { rounds: "2", tokens: "", seconds: "" };
    expect(talkRequest(blank, 2)).toEqual({ autonomous: true, rounds: 2 });
    expect(Object.keys(talkRequest(blank, 2) ?? {})).toEqual(["autonomous", "rounds"]);
    expect(talkRequest({ rounds: "1", tokens: " 8000 ", seconds: "120" }, 2)).toEqual({
      autonomous: true,
      rounds: 1,
      token_budget: 8000,
      time_budget_seconds: 120,
    });
  });

  it("refuses rounds outside what is left and budgets that are not whole numbers", () => {
    expect(talkRequest({ rounds: "3", tokens: "", seconds: "" }, 2)).toBeNull();
    expect(talkRequest({ rounds: "0", tokens: "", seconds: "" }, 2)).toBeNull();
    expect(talkRequest({ rounds: "", tokens: "", seconds: "" }, 2)).toBeNull();
    expect(talkRequest({ rounds: "2", tokens: "1.5", seconds: "" }, 2)).toBeNull();
    expect(talkRequest({ rounds: "2", tokens: "", seconds: "3601" }, 2)).toBeNull();
  });
});

describe("a reply's round", () => {
  it("is started by the UI only where the server did not start or refuse one", () => {
    expect(replyNeedsRound(discussion({ mode: "manual", auto_run: null }))).toBe(true);
    expect(replyNeedsRound(discussion({ auto_run: "started" }))).toBe(false);
    expect(replyNeedsRound(discussion({ auto_run: "already_running" }))).toBe(false);
    expect(replyNeedsRound(discussion({ auto_run: null, status: "approved" }))).toBe(false);
  });
});

describe("the run's events", () => {
  it("cuts the events by run", () => {
    const events = [event(9, "run_started", { run_id: "run-9" }), ...talkEvents()];
    const byRun = eventsByRun(events);
    expect([...byRun.keys()]).toEqual([RUN_ID, "run-9"]);
    expect(byRun.get(RUN_ID)).toHaveLength(6);
  });

  it("counts who answered the round under way and who could not be reached", () => {
    const view = runView(talking(), talkEvents());
    expect(view.run?.id).toBe(RUN_ID);
    expect(view.answered).toBe(1);
    expect([...view.failed]).toEqual([["agent-Bravo", "Bravo"]]);
    expect(view.failures.get(RUN_ID)).toEqual([
      { participantId: "agent-Bravo", name: "Bravo", error: "connection_refused", round: 1 },
    ]);
  });

  it("keeps the failures of the last completed round once the run is over, and who stopped it", () => {
    const events = [
      ...talkEvents(),
      event(7, "agent_completed", { participant_id: "agent-Charlie", round_number: 1 }),
      event(8, "round_completed", { run_id: RUN_ID, round_number: 1 }),
      event(9, "run_finished", { run_id: RUN_ID, run_status: "stopped" }, MEMBER.name),
    ];
    const view = runView(ended({ status: "stopped" }), events);
    expect(view.answered).toBe(0);
    expect([...view.failed.keys()]).toEqual(["agent-Bravo"]);
    expect(view.stoppedBy).toBe(MEMBER.name);
  });

  it("starts a new round's progress at nought and drops the old round's failures", () => {
    const events = [
      ...talkEvents(),
      event(8, "round_completed", { run_id: RUN_ID, round_number: 1 }),
      event(9, "agent_started", { participant_id: "agent-Alpha", round_number: 2 }),
    ];
    const view = runView(talking(), events);
    expect(view.answered).toBe(0);
    expect(view.failed.size).toBe(0);
  });

  it("reads nothing before the first run", () => {
    const view = runView(discussion({ runs: [] }), []);
    expect(view.run).toBeNull();
    expect(view.stoppedBy).toBeNull();
  });
});

describe("the run log", () => {
  it("writes a run with its codes, budgets, error and failed agents", () => {
    const failed = talkRun({
      status: "failed",
      stop_reason: "all_participants_failed",
      error: null,
      rounds_completed: 1,
    });
    const text = runText(failed, 3, [
      { participantId: "agent-Bravo", name: "Bravo", error: "connection_refused", round: 1 },
    ]);
    expect(text).toContain(
      "Run 3 · 2026-11-08T10:10:00Z · failed · autonomous · rounds 1 of 2 · answers 0 · failures 0 · repeats 0 · 0 tokens · token budget 20000 · 0 ms · time budget 300 s · stop: all_participants_failed · error: none · started by Ada Member",
    );
    expect(text).toContain("  Failed in round 1 · Bravo · connection_refused");
  });
});
