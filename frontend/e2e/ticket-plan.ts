/**
 * What the worker hands in for the Ticket journey (`ticket-view.spec.ts`): a RoadMap of two
 * Tickets with faces, one with five steps and one with two, and the Ticket written outside the
 * plan without a face. The Info and the analysis are `worker-plan.ts`'s.
 */

export const FIVE_STEPS = "Add the idle check";
export const TWO_STEPS = "Announce the timeout";
export const FIVE_SUMMARY = "Sessions nobody uses end by themselves after thirty minutes.";
export const TWO_SUMMARY = "People are told that idle sessions now end.";
export const CRITERION = "A session idle for 31 minutes is refused";
export const WHY = "An idle session stays valid for hours today.";
export const IF_SKIPPED = "Idle sessions keep working until they run out.";
export const PRO = "Idle sessions end by themselves.";
export const CON = "A person who pauses for half an hour signs in again.";

export const STEPS = [
  "Note the time of each request a person makes.",
  "End a session that has been idle for more than thirty minutes.",
  "Tell the person on their next click that the session ended because it was idle.",
  "Bring the person back to the page they were on after they sign in again.",
  "Count the sessions that end this way, so the limit can be judged.",
];

const announce = {
  id: "t2",
  title: TWO_STEPS,
  summary: TWO_SUMMARY,
  workplace: "outside",
  labels: ["Communication"],
  why: "People who are signed out without warning think something broke.",
  if_skipped: "Support gets the questions the announcement would have answered.",
  pros: ["One message reaches everyone before the change."],
  cons: ["The message has to go out before the check is switched on."],
  steps: ["Write the announcement about the idle timeout.", "Send it to everyone who signs in."],
};

/** The RoadMap with a step for a person; `announceSteps` replaces the second Ticket's steps. */
export function roadmap(announceSteps: string[] = announce.steps) {
  return {
    summary: "Add the check, then announce it.",
    phases: [
      {
        id: "p1",
        number: 1,
        name: "Idle check",
        objective: "Sessions end after 30 idle minutes",
        tickets: [
          {
            id: "t1",
            title: FIVE_STEPS,
            summary: FIVE_SUMMARY,
            objective: "End idle sessions",
            instructions: "Extend the request guard with the idle time.",
            acceptance_criteria: [CRITERION],
            workplace: "codebase",
            labels: ["Development"],
            why: WHY,
            if_skipped: IF_SKIPPED,
            pros: [PRO, "The same guard that runs today does the work."],
            cons: [CON],
            steps: STEPS,
          },
        ],
      },
      {
        id: "p2",
        number: 2,
        name: "Roll-out",
        objective: "People know about the timeout",
        tickets: [{ ...announce, steps: announceSteps }],
      },
    ],
  };
}

/** A second step that names a file: the server refuses the whole RoadMap. */
export const STEP_WITH_FILE = "Add the notice to Banner.tsx.";

export const ROADMAP_GOAL = "Idle sessions end on their own and people are told before it happens.";

export const ROADMAP_BRIEF = { goal: ROADMAP_GOAL };

/** The Ticket written outside the plan, without a face. */
export const UNPLANNED = "Show the remaining session time";
export const UNPLANNED_TEXT = "Found while adding the idle check.";

export const NOTE = "Ask support how often people complain about being signed out.";
export const NOTE_EDITED = "Ask support how often people complain about being signed out early.";
