/**
 * What the worker hands in during the planning journey (`worker-planning.spec.ts`): the Info, the
 * technical analysis with its brief for people, and the RoadMap with its brief. The texts are what
 * the journey then looks for on the Loop page.
 */

/** The scopes the journey's key holds: reading, the Loop's documents and plan, and its Tickets. */
export const WORKER_SCOPES = [
  "boards:read",
  "loops:read",
  "loops:write",
  "loops:generate",
  "cards:read",
  "cards:write",
  "comments:write",
];

export const INFO =
  "Idle sessions must end after 30 minutes. Out of scope: single sign-on. A person decides " +
  "whether open sessions are ended when the change ships.";

export const FINDING_RISK = "Open sessions stay valid after the change";
export const TECHNICAL_DETAIL = "The session table has no last-seen column; add one and index it.";

export const ANALYSIS = {
  outcome: "Idle sessions end after 30 minutes",
  scope: ["idle timeout for browser sessions"],
  non_goals: ["single sign-on"],
  findings: [
    {
      id: "risk-1",
      title: FINDING_RISK,
      category: "risk",
      technical_detail: TECHNICAL_DETAIL,
      plain_language: "People who are signed in now stay signed in until their session expires.",
    },
    {
      id: "reuse-1",
      title: "The sign-in check can be extended",
      category: "reuse",
      technical_detail: "The request guard already loads the session on every call.",
      plain_language: "The check that runs on every page can also look at the idle time.",
    },
  ],
  assumptions: ["Thirty minutes suits every team"],
  open_questions: [],
  recommendation: "Add the idle check to the existing guard.",
  verification: ["A session idle for 31 minutes is refused"],
};

export const ANALYSIS_SUMMARY = "Sessions nobody uses end by themselves after half an hour.";
export const OBSTACLE = "People signed in today stay signed in until their session runs out.";

export const ANALYSIS_BRIEF = {
  obstacles: [{ level: "security", text: OBSTACLE, finding_ids: ["risk-1"] }],
  pros: [{ text: "The check that already runs can be extended.", finding_ids: ["reuse-1"] }],
  cons: [],
  decisions: [],
  verdict: "yes_with_conditions",
  verdict_reason: "It can be done once open sessions are dealt with.",
  summary: ANALYSIS_SUMMARY,
  recommendation: "Go ahead and end open sessions when the change ships.",
};

/** The three planned Tickets: one ready, one after it, one waiting for an answer. */
export const READY = "Add the idle check";
export const AFTER = "Announce the timeout";
export const WAITING = "Agree the browser list";
export const WAITING_REASON = "Which browsers must the timeout warning support?";

export const ROADMAP = {
  summary: "Add the check, agree the browsers, then announce it.",
  phases: [
    {
      id: "p1",
      number: 1,
      name: "Idle check",
      objective: "Sessions end after 30 idle minutes",
      tickets: [
        {
          id: "t1",
          title: READY,
          summary: "The check that runs on every call also ends idle sessions.",
          objective: "End idle sessions",
          instructions: "Extend the request guard with the idle time.",
          acceptance_criteria: ["A session idle for 31 minutes is refused"],
          workplace: "codebase",
          labels: ["Development"],
        },
        {
          id: "t3",
          title: WAITING,
          summary: "The browsers the warning supports are agreed.",
          workplace: "outside",
          waiting_for: "information",
          waiting_reason: WAITING_REASON,
          labels: ["UX"],
        },
      ],
    },
    {
      id: "p2",
      number: 2,
      name: "Roll-out",
      objective: "People know about the timeout",
      tickets: [
        {
          id: "t2",
          title: AFTER,
          summary: "People are told that idle sessions now end.",
          prerequisite_ticket_ids: ["t1"],
          workplace: "outside",
          labels: ["Communication"],
        },
      ],
    },
  ],
};

export const ORDER_STEP = "The idle check is added and the browsers are agreed.";

export const ROADMAP_BRIEF = {
  order: [
    { phase_id: "p1", what_happens: ORDER_STEP, done_when: "Idle sessions end." },
    { phase_id: "p2", what_happens: "People are told.", done_when: "The notice is out." },
  ],
  your_part: [],
  could_block: [{ text: "The browser list is not agreed in time.", phase_ids: ["p1"] }],
  summary: "Two Phases: the check first, then the announcement.",
};

export const WAIT_REASON = "Should a warning show one minute before the session ends?";
export const COMMENT = "The guard now reads the last-seen time on every call.";
export const FOLLOW_UP = "Show the remaining session time";
export const NOTE = "Baseline: the unit suite passed before the idle check went in.";
export const FILE_NAME = "timeout-notes.txt";
export const FILE_TEXT = "Measured idle times\nmedian 12 minutes\n";
