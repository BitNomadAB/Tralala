import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import {
  approvalLine,
  approveRoadmapLabel,
  planFace,
  reviewPlan,
  rowLine,
  ticketCount,
  waitLine,
} from "@/features/loops/roadmapPlan";
import type { DocumentKind, GenerationRun, LoopDocument } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { apiPath, ok } from "./msw/envelope";
import {
  DOCUMENTS,
  emptyDocument,
  generationRun,
  LOOP_ID,
  LOOP_PATH,
  NOW,
  planningDialogHandlers,
} from "./msw/loops";
import { server } from "./msw/server";
import { renderDocuments } from "./renderDocuments";

const FIVE = [
  "Ask for the address when a person signs up.",
  "Send a mail with a confirmation link.",
  "Mark the address as confirmed when the link is opened.",
  "Show a reminder to people who have not confirmed.",
  "Stop sending mail to addresses that never confirm.",
];
const face = (summary: string, steps: string[]) => ({
  summary,
  why: "Nobody knows today whether an address is real.",
  if_skipped: "Mail keeps going to addresses nobody reads.",
  pros: ["Fewer returned mails."],
  cons: ["One more step at sign-up.", "Some people never confirm."],
  steps,
});
const PLAN = {
  schema_version: 1,
  summary: "Confirm addresses, then sign the policy.",
  phases: [
    {
      id: "p2",
      number: 2,
      name: "Policy",
      objective: "The retention policy is signed",
      tickets: [
        {
          id: "t3",
          key: "SES-1-PH02-001",
          title: "Sign the retention policy",
          required_actor: "human",
          workplace: "outside",
          waiting_for: "decision",
          waiting_reason: "Who signs for the company",
          acceptance_criteria: ["policy signed"],
          ...face("A person signs how long addresses are kept.", ["Sign the policy."]),
        },
      ],
    },
    {
      id: "p1",
      number: 1,
      name: "Mail",
      objective: "Every address is confirmed by mail",
      tickets: [
        {
          id: "t1",
          key: "SES-1-PH01-001",
          title: "Confirm the address",
          required_actor: "any",
          workplace: "codebase",
          waiting_for: "nothing",
          acceptance_criteria: ["confirmed column exists"],
          ...face("People confirm their address by opening a link.", FIVE),
        },
        {
          id: "t2",
          key: "SES-1-PH01-002",
          title: "Remind the unconfirmed",
          workplace: "unknown",
          ...face("People who never confirm get one reminder.", ["Send one reminder."]),
        },
      ],
    },
  ],
};
const OLD_PLAN = {
  phases: [
    {
      id: "p1",
      number: 1,
      name: "Mail",
      tickets: [
        {
          id: "t1",
          key: "SES-1-PH01-001",
          title: "Confirm the address",
          objective: "Store whether an address was confirmed",
          acceptance_criteria: ["confirmed column exists", "a link confirms it"],
        },
      ],
    },
  ],
};

function revision(kind: DocumentKind, extra: Partial<LoopDocument>): LoopDocument {
  return {
    ...emptyDocument(kind),
    state: "ready_for_review",
    current_revision_id: `${kind}-rev-2`,
    current_revision_number: 2,
    current_created_at: NOW,
    current_content: "text",
    ...extra,
  };
}

function documents(plan: Record<string, unknown>): Record<DocumentKind, LoopDocument> {
  return {
    ...DOCUMENTS,
    info: revision("info", {}),
    analysis_ai: revision("analysis_ai", {}),
    analysis: revision("analysis", { state: "approved" }),
    roadmap_ai: revision("roadmap_ai", { current_payload: plan }),
    roadmap: revision("roadmap", {
      current_content: "# RoadMap",
      current_provenance: { rendered: true },
    }),
  };
}

function open(plan: Record<string, unknown> = PLAN, runs: GenerationRun[] = []) {
  const { state, handlers } = planningDialogHandlers(runs);
  const reviews: unknown[] = [];
  server.use(
    http.get(apiPath(`${LOOP_PATH}/documents`), () =>
      ok({ loop_id: LOOP_ID, loop_version: 1, documents: documents(plan), approvals: {} }),
    ),
    http.post(apiPath(`${LOOP_PATH}/reviews/roadmap`), async ({ request }) => {
      reviews.push(await request.json());
      return ok({ id: "approval-1", loop_id: LOOP_ID, scope: "roadmap", decision: "approved" });
    }),
    ...handlers,
  );
  renderDocuments("roadmap");
  return { state, reviews, user: userEvent.setup() };
}

const phase = (name: RegExp) => screen.getByRole("region", { name });

describe("the RoadMap review", () => {
  it("shows the plan in short, then each Phase with a row per Ticket", async () => {
    open();
    const short = await screen.findByRole("region", { name: "In short" });
    expect(within(short).getByText("Confirm addresses, then sign the policy.")).toBeVisible();
    expect(screen.getAllByRole("region", { name: /^Phase / })).toHaveLength(2);
    // In the plan's order, with the count of Tickets after the name.
    expect(screen.getByRole("heading", { name: "Phase 1 · Mail 2" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Phase 2 · Policy 1" })).toBeInTheDocument();
    const mail = phase(/^Phase 1 · Mail/);
    expect(within(mail).getByText("Every address is confirmed by mail")).toBeVisible();
    expect(within(mail).getByText("Confirm the address")).toBeVisible();
    expect(within(mail).getByText("People confirm their address by opening a link.")).toBeVisible();
    expect(within(mail).getByText("In the code base")).toBeVisible();
    expect(within(mail).getByText("Unknown")).toBeVisible();
    expect(within(mail).queryByText("Needs a person")).not.toBeInTheDocument();
    const policy = phase(/^Phase 2 · Policy/);
    expect(within(policy).getByText("Needs a person")).toBeVisible();
    expect(within(policy).getByText("Outside")).toBeVisible();
    expect(
      within(policy).getByText("Waits for a decision: Who signs for the company"),
    ).toBeVisible();
    // The AI's acceptance criteria are not part of the face.
    expect(screen.queryByText("confirmed column exists")).not.toBeInTheDocument();
  });

  it("expands a row to its five steps and the face's sections, read only", async () => {
    const { user } = open();
    await user.click(await screen.findByText("Confirm the address"));
    const row = screen.getByText("Confirm the address").closest("details");
    if (!row) throw new Error("the row is an expander");
    expect(row.open).toBe(true);
    const steps = within(row).getByRole("list", { name: "Steps" });
    expect(
      within(steps)
        .getAllByRole("listitem")
        .map((step) => step.textContent),
    ).toEqual(FIVE.map((step, index) => `${index + 1}${step}`));
    for (const title of ["Why it is needed", "If we skip it", "Pro and con"]) {
      expect(within(row).getByText(title)).toBeVisible();
    }
    expect(within(row).getByText("1 for, 2 against")).toBeVisible();
    expect(within(row).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("counts the Tickets on the approval and sends it with the revisions on screen", async () => {
    const { reviews, user } = open();
    const approve = await screen.findByRole("button", { name: "Approve RoadMap · 3 Tickets" });
    expect(
      screen.getByText(
        `Revision 2 of ${formatDate(NOW)}. Approving publishes its 3 Tickets to the Kanban.`,
      ),
    ).toBeInTheDocument();
    await user.click(approve);
    await waitFor(() => expect(reviews).toHaveLength(1));
    expect(reviews[0]).toMatchObject({
      decision: "approved",
      version: 1,
      revisions: { roadmap_ai: "roadmap_ai-rev-2", roadmap: "roadmap-rev-2" },
    });
  });

  it("writes the RoadMap again with the feedback, which the run is given", async () => {
    const { user } = open();
    const started: unknown[] = [];
    const run = generationRun("queued", null, { purpose: "roadmap" });
    server.use(
      http.post(apiPath(`${LOOP_PATH}/generation-runs`), async ({ request }) => {
        started.push(await request.json());
        return ok(run);
      }),
      http.get(apiPath(`${LOOP_PATH}/generation-runs/run-1`), () => ok(run)),
    );
    await screen.findByRole("button", { name: "Approve RoadMap · 3 Tickets" });
    expect(screen.getByText(/its Tickets nobody has touched are removed/)).toBeInTheDocument();
    const feedback = "One person does the work; there is no legal team.";
    await user.type(screen.getByLabelText("Feedback (optional)"), feedback);
    await user.click(screen.getByRole("button", { name: "Regenerate RoadMap" }));
    await waitFor(() => expect(started).toEqual([{ purpose: "roadmap", instructions: feedback }]));
    // The feedback went to the run; the field is empty for the next decision.
    await waitFor(() => expect(screen.getByLabelText("Feedback (optional)")).toHaveValue(""));
  });

  it("offers the reset as a button of its own, as the analysis does, confirmed first", async () => {
    const { state, user } = open();
    await screen.findByRole("button", { name: "Approve RoadMap · 3 Tickets" });
    expect(screen.queryByRole("button", { name: "RoadMap actions" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset RoadMap" }));
    expect(screen.getByText(/Resetting clears the RoadMap/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset and clear" }));
    await waitFor(() =>
      expect(state.requests).toContain(`POST ${LOOP_PATH}/reviews/roadmap/reset`),
    );
  });

  it("shows the objective and the criteria behind More for a plan written before faces", async () => {
    const { user } = open(OLD_PLAN);
    const mail = await screen.findByRole("region", { name: /^Phase 1 · Mail/ });
    expect(within(mail).getByText("Store whether an address was confirmed")).toBeVisible();
    expect(within(mail).queryByRole("list", { name: "Steps" })).not.toBeInTheDocument();
    await user.click(within(mail).getByText("More"));
    const criteria = within(mail).getByRole("list", { name: "Accepted when" });
    expect(within(criteria).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Approve RoadMap · 1 Ticket" })).toBeInTheDocument();
  });

  it("shows the plan as indented JSON under Raw text", async () => {
    const { user } = open();
    await user.click(await screen.findByRole("tab", { name: "Raw text" }));
    expect(screen.getByText("RoadMap (AI)")).toBeInTheDocument();
    const raw = screen.getByLabelText("The plan as JSON");
    expect(raw.tagName).toBe("PRE");
    expect(raw.textContent).toBe(JSON.stringify(PLAN, null, 2));
    // The hidden For you panel leaves the accessibility tree.
    expect(screen.queryByRole("region", { name: "In short" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "For you" }));
    expect(screen.getByRole("region", { name: "In short" })).toBeVisible();
  });

  it("shows a kept RoadMap as Phases and Tickets, with its JSON behind Raw text", async () => {
    open(PLAN, [
      generationRun("failed", "generating", {
        purpose: "roadmap",
        error_code: "generation_input_changed",
        output: { stale_candidate: PLAN },
      }),
    ]);
    const kept = await screen.findByRole("region", { name: "Kept RoadMap result" });
    expect(within(kept).getByRole("region", { name: /^Phase 1 · Mail/ })).toBeInTheDocument();
    expect(within(kept).getByText("Raw text")).toBeInTheDocument();
    expect(kept.querySelector("pre code")).toHaveTextContent('"name": "Policy"');
  });
});

describe("reading a plan for its review", () => {
  it("orders the Phases, counts the Tickets and reads a face only when it has one", () => {
    const phases = reviewPlan(PLAN);
    expect(phases?.map((entry) => entry.number)).toEqual([1, 2]);
    expect(ticketCount(phases)).toBe(3);
    expect(reviewPlan({ phases: [] })).toBeNull();
    expect(reviewPlan("text")).toBeNull();
    expect(planFace({ summary: "Only a summary." })).toBeNull();
    const old = reviewPlan(OLD_PLAN)?.[0]?.tickets[0];
    if (!old) throw new Error("the old plan has a Ticket");
    expect(old.face).toBeNull();
    expect(old.workplace).toBe("unknown");
    expect(rowLine(old)).toBe("Store whether an address was confirmed");
  });

  it("says the decision, the revision and the wait in words", () => {
    expect(approveRoadmapLabel(1)).toBe("Approve RoadMap · 1 Ticket");
    expect(approveRoadmapLabel(0)).toBe("Approve RoadMap");
    expect(approvalLine(undefined, 3)).toBeNull();
    expect(approvalLine({ ...emptyDocument("roadmap"), current_revision_number: 4 }, 0)).toBe(
      "Revision 4. Approving publishes its Tickets to the Kanban.",
    );
    expect(waitLine({ waitingFor: "nothing", waitingReason: "" })).toBeNull();
    expect(waitLine({ waitingFor: "third_party", waitingReason: "" })).toBe(
      "Waits for a third party",
    );
  });
});
