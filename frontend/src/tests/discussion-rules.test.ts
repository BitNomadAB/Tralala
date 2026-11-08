import { describe, expect, it } from "vitest";
import { roundLines, stanceRows } from "@/features/discussions/discussionData";
import {
  askedLine,
  confidenceText,
  decisionAllowed,
  decisionBlocked,
  discussionPagePath,
  holdOutsLine,
  positionLabel,
  positionTone,
  replyHint,
  reviewedText,
  roundsText,
  stateOf,
  ticketOnLoopPath,
  tokensText,
} from "@/features/discussions/discussionRules";
import type { Discussion } from "@/lib/types";
import { discussion } from "./msw/discussions";
import { MEMBER } from "./msw/session";

const RUN = discussion().runs?.[0] ?? null;

function thread(extra: Partial<Discussion> = {}): Discussion {
  return discussion(extra);
}

function word(extra: Partial<Discussion>, names = {}) {
  const state = stateOf(thread(extra), names);
  return state.reason ? `${state.word} · ${state.reason}` : state.word;
}

describe("the state words", () => {
  it("waits for your decision once there is a synthesis and no decision", () => {
    expect(word({})).toBe("Waits for your decision · after round 2");
    expect(stateOf(thread()).tone).toBe("warning");
  });

  it("says the agents are answering and which round", () => {
    expect(word({ run_state: "running" })).toBe("Agents are answering · round 3 of 4");
    expect(word({ run_state: "running", round_count: 4 })).toBe(
      "Agents are answering · round 4 of 4",
    );
  });

  it("says Paused", () => {
    expect(word({ run_state: "paused" })).toBe("Paused");
  });

  it("says who approved, vetoed or asked for rework when it is known", () => {
    expect(word({ status: "approved" }, { decidedBy: "Mike" })).toBe("Approved by Mike");
    expect(word({ status: "vetoed" }, { decidedBy: "Mike" })).toBe("Vetoed by Mike");
    expect(word({ status: "rework_requested" }, { decidedBy: "Mike" })).toBe(
      "Rework requested by Mike",
    );
    expect(stateOf(thread({ status: "approved" })).tone).toBe("success");
    expect(stateOf(thread({ status: "vetoed" })).tone).toBe("danger");
  });

  it("leaves the name out when nobody is named", () => {
    expect(word({ status: "approved" })).toBe("Approved");
    expect(word({ status: "vetoed" })).toBe("Vetoed");
    expect(word({ status: "rework_requested" })).toBe("Rework requested");
    expect(word({ run_state: "stopped" })).toBe("Stopped");
  });

  it("says Cancelled", () => {
    expect(word({ status: "cancelled", run_state: "running" })).toBe("Cancelled");
  });

  it("says No answer yet before the first synthesis", () => {
    expect(word({ synthesis: null, status: "open" })).toBe("No answer yet");
    expect(stateOf(thread({ synthesis: null })).tone).toBe("neutral");
  });

  it("says who stopped the run", () => {
    expect(word({ run_state: "stopped" }, { stoppedBy: "Mike" })).toBe("Stopped by Mike");
  });

  it("never shows a database status", () => {
    for (const status of ["open", "discussing", "consensus_proposed", "human_review"]) {
      expect(word({ status })).not.toContain(status);
    }
  });
});

describe("the decision", () => {
  it("is allowed after a round with no run active", () => {
    expect(decisionAllowed(thread())).toBe(true);
    expect(decisionAllowed(thread({ status: "consensus_proposed" }))).toBe(true);
  });

  it("says why it is not allowed", () => {
    expect(decisionBlocked(thread({ run_state: "running" }))).toBe(
      "The agents are still answering",
    );
    expect(decisionBlocked(thread({ run_state: "paused" }))).toBe("Stop the run before you decide");
    expect(decisionBlocked(thread({ active_run: RUN }))).toBe("Stop the run before you decide");
    expect(decisionBlocked(thread({ synthesis: null }))).toBe(
      "There is no answer to decide on yet",
    );
    expect(decisionBlocked(thread({ status: "open" }))).toBe("There is no answer to decide on yet");
    expect(decisionBlocked(thread({ status: "approved" }))).toBe("The discussion is decided");
    expect(decisionBlocked(thread({ status: "cancelled" }))).toBe("The discussion was cancelled");
    expect(decisionBlocked(thread({ status: "rework_requested" }))).toBe(
      "Ask again first: you asked for rework",
    );
    expect(decisionAllowed(thread({ run_state: "running" }))).toBe(false);
  });

  it("is told in the toast once recorded", () => {
    expect(reviewedText("approve")).toBe("Discussion approved");
    expect(reviewedText("veto")).toBe("Discussion vetoed");
    expect(reviewedText("rework")).toBe("Rework requested");
  });
});

describe("the words of the view", () => {
  it("reads a position as the brief's verdict words", () => {
    expect(positionLabel("yes")).toBe("Yes");
    expect(positionLabel("yes_with_conditions")).toBe("Yes, with conditions");
    expect(positionLabel("no")).toBe("No");
    expect(positionLabel("unclear")).toBe("Unclear");
    expect(positionLabel("approve")).toBe("Unclear");
    expect(positionTone("yes")).toBe("success");
    expect(positionTone("yes_with_conditions")).toBe("warning");
    expect(positionTone("no")).toBe("danger");
    expect(positionTone("unclear")).toBe("neutral");
  });

  it("reads the confidence, the counts and the rounds", () => {
    expect(confidenceText("high")).toBe("High confidence");
    expect(confidenceText("low")).toBe("Low confidence");
    expect(confidenceText(null)).toBeNull();
    expect(tokensText(12400)).toBe("12 400");
    expect(tokensText(1234567)).toBe("1 234 567");
    expect(tokensText(980)).toBe("980");
    expect(roundsText(thread())).toBe("2 of 4");
    expect(askedLine(thread())).toBe("Asked by Ada Member · 4 agents · round 2 of 4");
    expect(askedLine(thread({ round_count: 0, participants: [] }))).toBe(
      "Asked by Ada Member · 0 agents · no round yet",
    );
  });

  it("names who cannot tell and who has not answered", () => {
    const synthesis = thread().synthesis;
    if (!synthesis) throw new Error("the fixture has a synthesis");
    expect(holdOutsLine(synthesis)).toBe("Cannot tell yet: Charlie · No answer yet from Delta");
    expect(holdOutsLine({ ...synthesis, unclear: [], missing: [] })).toBeNull();
  });

  it("hints that a reply is a new round, and why it waits while the agents answer", () => {
    expect(replyHint(thread())).toBe("The agents answer in a new round.");
    expect(replyHint(thread({ mode: "manual" }))).toBe("The agents answer in a new round.");
    expect(replyHint(thread({ run_state: "running" }))).toBe(
      "The agents are answering. Reply once they are done.",
    );
    expect(replyHint(thread({ run_state: "paused" }))).toBe(
      "The agents are answering. Reply once they are done.",
    );
  });

  it("builds the discussion's page and the Ticket over the Kanban", () => {
    expect(discussionPagePath("b", "l", "c", "d")).toBe(
      "/boards/b/loops/l/tickets/c/discussions/d",
    );
    expect(ticketOnLoopPath("b", "l", "c")).toBe("/boards/b/loops/l?card=c");
  });
});

describe("the rows and the rounds", () => {
  it("reads each participant's latest answer, prose or nothing", () => {
    const rows = stanceRows(thread());
    expect(rows.map((row) => [row.name, row.kind])).toEqual([
      ["Alpha", "answer"],
      ["Bravo", "answer"],
      ["Charlie", "prose"],
      ["Delta", "none"],
    ]);
    expect(rows[0]?.answer?.open_questions).toEqual(["Who rewrites a wrong assumption?"]);
  });

  it("reads an answer from before the standard as prose", () => {
    const base = thread();
    const rows = stanceRows({
      ...base,
      positions: [],
      messages: base.messages.map((message) => ({ ...message, answer: null })),
    });
    expect(rows.map((row) => row.kind)).toEqual(["prose", "prose", "prose", "none"]);
  });

  it("says who started each round, how many answered and the verdict after it", () => {
    const lines = roundLines(thread(), MEMBER.id);
    expect(lines.map((line) => line.number)).toEqual([1, 2]);
    expect(lines[0]?.text).toBe("You asked the question · 3 answers · Unclear");
    expect(lines[1]?.text).toMatch(/^Grace Hopper replied "What if .{40,60}…" · 3 answers/);
    expect(roundLines(thread(), "someone-else")[0]?.text).toMatch(/^Ada Member asked/);
  });

  it("says the agents answered each other when no person started the round", () => {
    const base = thread();
    const lines = roundLines(
      { ...base, messages: base.messages.filter((message) => message.author_type === "agent") },
      MEMBER.id,
    );
    expect(lines[0]?.text).toBe("The agents answered each other · 3 answers · Unclear");
  });
});
